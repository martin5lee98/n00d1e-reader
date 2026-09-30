"""
reclean_authors.py

Re-runs author cleaning on articles already in D1, using each article's
stored raw_author (the original byline, never modified). Useful after
improving a site's author cleaner.

    python3 reclean_authors.py cyol-bingdian            # show before -> after only
    python3 reclean_authors.py cyol-bingdian --apply    # also save the changes

Needs the same env vars as fetch.py.
"""

from __future__ import annotations

import argparse

from d1_client import D1Client, D1Statement
from scrapers import authors
from scrapers.sites import cyol

# site -> cleaner; anything not listed uses the shared prefix cleaner.
CLEANERS = {
    "cyol": cyol.clean_reporter,
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("column_key")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    with D1Client() as db:
        col = db.execute(
            "SELECT id, site FROM columns WHERE column_key = ?1", [args.column_key]
        )["results"]
        if not col:
            print(f"No column {args.column_key!r}")
            return
        column_id, site = col[0]["id"], col[0]["site"]
        clean = CLEANERS.get(site, lambda r: authors.clean_author_string(r) or None)

        rows = db.execute(
            "SELECT id, title, author, raw_author FROM articles WHERE column_id = ?1 ORDER BY id",
            [column_id],
        )["results"]

        updates = []
        for r in rows:
            new = clean(r["raw_author"]) if r["raw_author"] else None
            mark = "  " if new == r["author"] else "* "
            print(f"{mark}{r['raw_author']!s:40}  ->  {new}")
            if new != r["author"]:
                updates.append(D1Statement(
                    sql="UPDATE articles SET author = ?1 WHERE id = ?2",
                    params=[new, r["id"]],
                ))

        print(f"\n{len(rows)} articles, {len(updates)} would change (marked *).")
        if args.apply and updates:
            db.batch_chunked(updates)
            print("Saved.")
        elif updates:
            print("Nothing saved -- re-run with --apply to save.")


if __name__ == "__main__":
    main()
