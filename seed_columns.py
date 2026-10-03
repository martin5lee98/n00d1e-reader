"""
seed_columns.py

Syncs the `columns` table in D1 from scrapers/registry.py. fetch.py only
scrapes columns that exist in D1, so run this once after applying
schema.sql, and again whenever you add/edit a column in the registry.

    python seed_columns.py            # upsert every registry column
    python seed_columns.py --dry-run  # print what would be written

Needs the same env vars as fetch.py:
    CLOUDFLARE_ACCOUNT_ID, D1_DATABASE_ID, CLOUDFLARE_API_TOKEN

Tiers (see fetch.py's TIER_INTERVALS and .github/workflows/fetch.yml):
    fetch_interval_minutes <= 30  -> "fast" tier, runs every 15 min
    fetch_interval_minutes  > 30  -> "slow" tier, runs every 6 hours

Upsert semantics: existing rows keep their id (so articles.column_id stays
valid), their `active` flag and their last_fetch_* status; only the
display/config fields below are refreshed from the registry. Columns that
exist in D1 but were removed from the registry are NOT deleted (their
articles reference them) -- they are set to active = 0, which hides them
from the site and stops fetch.py from scraping them. Re-adding a key to the
registry does not reactivate it automatically; run
UPDATE columns SET active = 1 WHERE column_key = '...' if you want it back.
"""

from __future__ import annotations

import argparse

from d1_client import D1Client, D1Statement
from scrapers.registry import COLUMNS

DEFAULT_INTERVAL = 360

UPSERT_SQL = """
INSERT INTO columns (
    site, column_key, outlet_name, column_name, category,
    source_url, fetch_interval_minutes, hide_in_cn
)
VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
ON CONFLICT(column_key) DO UPDATE SET
    site = excluded.site,
    outlet_name = excluded.outlet_name,
    column_name = excluded.column_name,
    category = excluded.category,
    source_url = excluded.source_url,
    fetch_interval_minutes = excluded.fetch_interval_minutes,
    hide_in_cn = excluded.hide_in_cn
"""


def build_statements() -> list[D1Statement]:
    statements = []
    for key, cfg in COLUMNS.items():
        interval = cfg.get("fetch_interval_minutes", DEFAULT_INTERVAL)
        statements.append(D1Statement(
            sql=UPSERT_SQL,
            params=[
                cfg["site"], key, cfg["outlet_name"], cfg.get("column_name"),
                cfg["category"], cfg["source_url"], interval,
                1 if cfg.get("hide_in_cn") else 0,
            ],
        ))
    return statements


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    for key, cfg in COLUMNS.items():
        interval = cfg.get("fetch_interval_minutes", DEFAULT_INTERVAL)
        tier = "fast" if interval <= 30 else "slow"
        print(f"  {tier:4}  {interval:>4} min  {key}")

    if args.dry_run:
        print(f"\nDry run: {len(COLUMNS)} columns, nothing written "
              "(columns removed from the registry would be deactivated).")
        return

    with D1Client() as db:
        db.batch(build_statements())
        rows = db.execute("SELECT column_key, active FROM columns")["results"]
        orphans = sorted(
            r["column_key"] for r in rows
            if r["column_key"] not in COLUMNS and r["active"]
        )
        if orphans:
            db.batch([
                D1Statement(sql="UPDATE columns SET active = 0 WHERE column_key = ?1", params=[k])
                for k in orphans
            ])

    print(f"\nUpserted {len(COLUMNS)} columns.")
    if orphans:
        print("Deactivated (in D1 but no longer in registry):")
        for k in orphans:
            print(f"  - {k}")


if __name__ == "__main__":
    main()
