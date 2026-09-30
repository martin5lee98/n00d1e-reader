"""
fetch.py

Entry point for the GitHub Actions fetcher. Run as:

    python fetch.py --tier fast     # e.g. news-paced columns, every 15 min
    python fetch.py --tier slow     # e.g. culture/books columns, every few hours
    python fetch.py --column thepaper-sixiang-shichang   # single column, for local dev/debugging

Responsibilities:
  1. Pull active columns (optionally filtered by tier or a single column_key) from D1.
  2. For each, call the matching scraper from scrapers/registry.py.
  3. Upsert resulting articles into D1 (dedup on url; see upsert_articles for the
     fetched_at-preservation logic).
  4. Record success/failure back onto the columns row (last_fetched_at,
     last_fetch_status, last_fetch_error) so a stale-column monitor can query it.

Deliberately sequential (not concurrent) across columns for a first version --
simpler to reason about and debug, and column counts are small enough that
runtime isn't a concern yet. Revisit with asyncio/threading if the column list
grows large enough that a single run doesn't finish within its interval.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime, timezone

from d1_client import D1Client, D1Statement, D1Error
from scrapers.registry import COLUMNS
from scrapers.base import RawArticle
from scrapers.summaries import trim_summary


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_due_columns(db: D1Client, tier: str | None, column_key: str | None) -> list[dict]:
    """
    Pull active columns from D1, optionally filtered.

    Tiers are just a convention encoded in fetch_interval_minutes (e.g. 15 for
    "fast", 360 for "slow") -- see the tier -> interval mapping below. This
    keeps scheduling logic in the workflow file (which cron runs which tier)
    rather than adding a separate "tier" column that could drift out of sync
    with fetch_interval_minutes.
    """
    TIER_INTERVALS = {
        "fast": (0, 30),      # up to 30 min: news-paced (Tencent Tech, Yicai, etc)
        "slow": (30, 100000), # anything slower: culture/books/opinion columns
    }

    if column_key:
        result = db.execute(
            "SELECT id, site, column_key FROM columns WHERE column_key = ?1 AND active = 1",
            [column_key],
        )
        return result["results"]

    if tier:
        if tier not in TIER_INTERVALS:
            raise ValueError(f"Unknown tier {tier!r}, expected one of {list(TIER_INTERVALS)}")
        lo, hi = TIER_INTERVALS[tier]
        result = db.execute(
            """
            SELECT id, site, column_key
            FROM columns
            WHERE active = 1
              AND fetch_interval_minutes > ?1
              AND fetch_interval_minutes <= ?2
            """,
            [lo, hi],
        )
        return result["results"]

    result = db.execute("SELECT id, site, column_key FROM columns WHERE active = 1")
    return result["results"]


def articles_to_statements(column_id: int, articles: list[RawArticle]) -> list[D1Statement]:
    statements = []
    for a in articles:
        statements.append(D1Statement(
            sql="""
                INSERT INTO articles (
                    column_id, url, title, description, image_url,
                    author, raw_author, published_at, extra
                )
                VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    description = excluded.description,
                    image_url = excluded.image_url
                    -- author / raw_author / published_at / extra deliberately NOT
                    -- overwritten -- first-seen values are trusted; re-scrapes only
                    -- refresh display fields that legitimately change (e.g. a typo fix)
                    -- fetched_at is NOT in this statement at all, so it keeps its
                    -- original INSERT-time default on conflict, which is what makes
                    -- "column last updated" reflect genuinely new articles only.
            """,
            params=[
                column_id, a.url, a.title, a.description, a.image_url,
                a.author, a.raw_author_string, a.published_at,
                json.dumps(a.extra, ensure_ascii=False) if a.extra else None,
            ],
        ))
    return statements


def mark_fetch_result(db: D1Client, column_id: int, status: str, error: str | None):
    db.execute(
        """
        UPDATE columns
        SET last_fetched_at = ?1, last_fetch_status = ?2, last_fetch_error = ?3
        WHERE id = ?4
        """,
        [now_iso(), status, error, column_id],
    )


def run_column(db: D1Client, column_row: dict) -> tuple[int, int]:
    """Returns (n_articles_fetched, n_statements_written)."""
    column_key = column_row["column_key"]
    column_id = column_row["id"]

    config = COLUMNS.get(column_key)
    if config is None:
        # Registry/DB drift: a column exists in D1 but has no matching Python
        # scraper entry. Don't crash the whole run over one bad column.
        mark_fetch_result(db, column_id, "error", f"no registry entry for column_key={column_key!r}")
        print(f"  [SKIP] {column_key}: no registry entry", file=sys.stderr)
        return (0, 0)

    try:
        # Each registry entry's fetch is a zero-arg closure that already has
        # everything it needs baked in (site-specific params like node_id/
        # media_id/tag/programa, plus whichever http client shape that site
        # module requires) -- see scrapers/registry.py. fetch.py deliberately
        # knows nothing about the different client shapes (http_get vs
        # http_get_json vs http_post_json) needed across sites; that's the
        # registry's job to wire up, not this file's.
        articles = config["fetch"]()
    except Exception as e:
        err = f"{type(e).__name__}: {e}"
        mark_fetch_result(db, column_id, "error", err[:500])
        print(f"  [FAIL] {column_key}: {err}", file=sys.stderr)
        traceback.print_exc()
        return (0, 0)

    if not articles:
        # Not necessarily an error -- a column can legitimately have no new
        # items this run -- but zero items on every run for a while is a
        # signal worth noticing via the stale-column monitor, so we still
        # mark this as "ok" (fetch succeeded, just nothing returned) rather
        # than conflating "fetch failed" with "fetch found nothing".
        mark_fetch_result(db, column_id, "ok", None)
        print(f"  [OK]   {column_key}: 0 articles")
        return (0, 0)

    # One summary-length rule for every source (scrapers/summaries.py).
    for a in articles:
        a.description = trim_summary(a.description)

    if not config.get("store_images", True):
        # See the "store_images" note in scrapers/registry.py.
        for a in articles:
            a.image_url = None

    statements = articles_to_statements(column_id, articles)
    try:
        db.batch_chunked(statements)
    except D1Error as e:
        err = f"D1 write failed: {e}"
        mark_fetch_result(db, column_id, "error", err[:500])
        print(f"  [FAIL] {column_key}: {err}", file=sys.stderr)
        return (len(articles), 0)

    mark_fetch_result(db, column_id, "ok", None)
    print(f"  [OK]   {column_key}: {len(articles)} articles")
    return (len(articles), len(statements))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", choices=["fast", "slow"], default=None)
    parser.add_argument("--column", dest="column_key", default=None)
    args = parser.parse_args()

    with D1Client() as db:
        columns = fetch_due_columns(db, tier=args.tier, column_key=args.column_key)
        if not columns:
            print("No matching active columns found.")
            return

        print(f"Fetching {len(columns)} column(s)...")

        total_articles = 0
        total_written = 0
        n_failed = 0

        for row in columns:
            n_articles, n_written = run_column(db, row)
            total_articles += n_articles
            total_written += n_written

        print(
            f"\nDone. {len(columns)} columns processed, "
            f"{total_articles} articles fetched, {total_written} statements written."
        )


if __name__ == "__main__":
    main()
