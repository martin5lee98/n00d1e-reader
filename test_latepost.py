"""
test_latepost.py

Diagnoses the 晚点LatePost scraper step by step, without touching the
database. Run from the repo root:

    python3 test_latepost.py            # tests both columns in use (1 and 4)
    python3 test_latepost.py 1          # one column (1=晚点独家 2=人物访谈 3=晚点早知道 4=长报道)
    python3 test_latepost.py 1 --raw    # also print the full raw response

It makes exactly the request scrapers/sites/latepost.py makes, then shows
where things go wrong:
    step 1  the HTTP request      (blocked? wrong address? timeout?)
    step 2  the reply is JSON     (or an HTML error / login / captcha page?)
    step 3  the API says success  (code == 1)
    step 4  items have the fields the scraper expects
    step 5  the scraper's own parsing of each item
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import httpx

from scrapers import http_clients
from scrapers.sites import latepost

EXPECTED_FIELDS = ["id", "title", "release_time", "cover", "abstract"]


def show(label: str, value) -> None:
    print(f"    {label:<14} {value}")


def test_programa(programa: int, raw: bool) -> bool:
    name = latepost.COLUMN_NAMES.get(programa, "?")
    print(f"\n===== programa={programa} ({name}) =====")

    form_data = {"page": 1, "limit": 10, "programa": programa}
    headers = {
        "User-Agent": http_clients.USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{latepost.SITE_ROOT}/news/index?proma={programa}",
        "Origin": latepost.SITE_ROOT,
    }

    # ---- step 1: the request itself
    print("[1] POST", latepost.API_URL, form_data)
    try:
        resp = httpx.post(latepost.API_URL, data=form_data, headers=headers,
                          timeout=20.0, follow_redirects=True,
                          verify=http_clients.ssl_context())
    except Exception as e:
        print(f"    FAILED: could not connect -- {type(e).__name__}: {e}")
        return False
    show("status", resp.status_code)
    show("content-type", resp.headers.get("content-type"))
    show("final URL", resp.url)
    if resp.history:
        show("redirected via", " -> ".join(str(r.status_code) for r in resp.history))
    show("body length", f"{len(resp.text)} characters")
    if raw:
        print("    ---- raw body ----")
        print(resp.text)
        print("    ------------------")
    if resp.status_code != 200:
        print("    FAILED: the server did not return 200. Start of the reply:")
        print("   ", resp.text[:400].replace("\n", " "))
        return False
    print("    ok")

    # ---- step 2: is it JSON?
    print("[2] reply is JSON")
    try:
        data = resp.json()
    except Exception as e:
        print(f"    FAILED: not JSON ({type(e).__name__}). Start of the reply:")
        print("   ", resp.text[:400].replace("\n", " "))
        return False
    if not isinstance(data, dict):
        print(f"    FAILED: expected a JSON object, got {type(data).__name__}: {str(data)[:200]}")
        return False
    show("top-level keys", list(data.keys()))
    print("    ok")

    # ---- step 3: API success code
    print("[3] API reports success (code == 1)")
    show("code", repr(data.get("code")))
    for key in ("msg", "message", "info"):
        if key in data:
            show(key, repr(data.get(key)))
    if data.get("code") != 1:
        print("    FAILED: the scraper requires code == 1 (the number, not the text \"1\").")
        print("    whole reply:", json.dumps(data, ensure_ascii=False)[:600])
        return False
    print("    ok")

    # ---- step 4: items and their fields
    print("[4] items")
    items = data.get("data")
    if not isinstance(items, list):
        print(f"    FAILED: 'data' is {type(items).__name__}, expected a list: {str(items)[:300]}")
        return False
    show("count", len(items))
    if not items:
        print("    FAILED: the list is empty.")
        return False
    first = items[0]
    show("fields", sorted(first.keys()) if isinstance(first, dict) else type(first).__name__)
    missing = [f for f in EXPECTED_FIELDS if not isinstance(first, dict) or f not in first]
    if missing:
        print(f"    WARNING: first item has no field(s): {missing}")
    else:
        print("    ok")

    # ---- step 5: the scraper's own parsing, item by item
    print("[5] scraper parsing")
    today = datetime.now(timezone.utc).date()
    ok = True
    for i, item in enumerate(items, 1):
        try:
            a = latepost._parse_item(item, today)
        except Exception as e:
            ok = False
            print(f"    item {i}: FAILED -- {type(e).__name__}: {e}")
            print("      raw:", json.dumps(item, ensure_ascii=False)[:400])
            continue
        flags = []
        if a.published_at is None:
            flags.append(f"date not understood: {item.get('release_time')!r}")
        if not a.description:
            flags.append("no summary")
        if not a.image_url:
            flags.append("no image")
        note = ("   <-- " + "; ".join(flags)) if flags else ""
        print(f"    item {i}: {a.published_at}  {a.title[:36]}{note}")
        print(f"            {a.url}")

    # ---- finally: the real entry point fetch.py uses
    print("[6] latepost.fetch_column() as fetch.py calls it")
    try:
        result = latepost.fetch_column(programa=programa,
                                       http_post_json=http_clients.http_post_json,
                                       page=1, limit=10)
        print(f"    ok -- {len(result)} articles")
    except Exception as e:
        ok = False
        print(f"    FAILED -- {type(e).__name__}: {e}")
    return ok


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv
    programas = [int(a) for a in args] or [1, 4]
    results = {p: test_programa(p, raw) for p in programas}
    print("\n===== summary =====")
    for p, ok in results.items():
        print(f"  programa={p} ({latepost.COLUMN_NAMES.get(p, '?')}): {'OK' if ok else 'FAILED'}")
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
