"""
scrapers/sites/thepaper.py

Extracts articles from The Paper (澎湃新闻 / thepaper.cn) column/list pages.

Extraction method: The Paper's list pages (e.g. thepaper.cn/list_{nodeId})
embed the full article list as JSON inside a <script id="__NEXT_DATA__">
tag (standard Next.js data hydration payload) -- no need to parse rendered
HTML or CSS-select individual cards.

URL pattern -- CONFIRMED against live data, not guessed:
    https://www.thepaper.cn/newsDetail_forward_{id}

Verified 2026-09 by cross-referencing a live fetch of
https://m.thepaper.cn/list_25483 against a __NEXT_DATA__ sample from the
same column: the first item on the live page ("从街头到网络：'羞辱'的历史
与今天｜对谈") links to newsDetail_forward_34080892, matching
"contId":"34080892" in the JSON for the same headline. So `contId` is the
correct id field for this URL pattern.

One caveat that remains UNVERIFIED: items carry both `contId` and
`originalContId`, usually equal, alongside `isOutForward`/`forwardType`
fields that suggest reposted/forwarded content might use a different id
for the canonical URL. I have not found a live example where the two
diverge, so this is a defensive fallback, not a confirmed requirement --
worth revisiting if a scraped URL for a forwarded-looking item 404s.

Per-column notes (record new ones here as they're discovered):
  - 思想市场 (node 25483): `pubTime`/`pubTimeNew` are relative strings
    ("15小时前") not absolute timestamps -- NOT stored as published_at.
    `publishTime` ("2026-09-22 16:28:33") is the absolute timestamp to use.
  - `nodeInfo.summarize` is the COLUMN's description, not the article's --
    never use it as an article-level description.
  - This site has no genuine per-article description field in the list
    JSON at all (confirmed by inspecting the sample) -- trust_description
    should be False for every thepaper column until proven otherwise.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from ..base import RawArticle
from .. import authors

NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

HttpGet = Callable[[str], str]


def fetch_column(node_id: str, list_url: str, http_get: HttpGet) -> list[RawArticle]:
    """
    Fetch and parse one column's list page.

    node_id: the numeric node id, e.g. "25483" for 思想市场. Passed
        separately from list_url (rather than parsed out of it) so the
        registry entry stays readable and the URL format can change
        without touching this function's call sites.
    list_url: full URL of the list page, e.g.
        "https://www.thepaper.cn/list_25483"
    http_get: shared HTTP GET function (see fetch.py's make_http_get) --
        injected rather than imported so this module has no direct network
        dependency and is easy to test with a canned HTML fixture.
    """
    html = http_get(list_url)
    match = NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError(
            f"__NEXT_DATA__ script tag not found for node {node_id} at {list_url} "
            f"-- page structure may have changed"
        )

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"__NEXT_DATA__ for node {node_id} was not valid JSON: {e}") from e

    try:
        items = data["props"]["pageProps"]["data"]["list"]
    except (KeyError, TypeError) as e:
        raise ValueError(
            f"__NEXT_DATA__ for node {node_id} did not match the expected "
            f"props.pageProps.data.list shape -- site structure may have changed"
        ) from e

    out = []
    for item in items:
        out.append(_parse_item(item))
    return out


def _parse_item(item: dict) -> RawArticle:
    # See module docstring: originalContId preferred when present and
    # different from contId, as a defensive guard for forwarded content.
    # Falls back to contId, which is the confirmed-correct field for the
    # common case.
    article_id = item.get("originalContId") or item.get("contId")
    url = f"https://www.thepaper.cn/newsDetail_forward_{article_id}"

    raw_author = item.get("trackAuthor") or None

    return RawArticle(
        title=item["name"],
        url=url,
        description=None,  # see module docstring -- no genuine per-article description on this site
        image_url=item.get("pic") or None,
        published_at=_normalize_published_at(item.get("publishTime")),
        author=authors.clean_author_string(raw_author) if raw_author else None,
        raw_author_string=raw_author,
        extra={
            "tags": [t["tag"] for t in item.get("tagList", [])],
            "audio_url": item.get("voiceInfo", {}).get("voiceSrc"),
            "node_name": item.get("nodeInfo", {}).get("name"),
        },
    )


def _normalize_published_at(publish_time: str | None) -> str | None:
    """
    thepaper's `publishTime` field looks like "2026-09-22 16:28:33" --
    space-separated, no timezone marker. Convert to ISO 8601 with a "T"
    separator for consistency with the rest of the pipeline. Assumed to
    be China Standard Time (UTC+8), matching the site's evident audience
    and every timestamp observed so far, though this has not been
    independently confirmed against a known-timezone reference event.
    """
    if not publish_time:
        return None
    try:
        date_part, time_part = publish_time.split(" ", 1)
        return f"{date_part}T{time_part}+08:00"
    except ValueError:
        # Unexpected format -- don't crash the whole column fetch over one
        # malformed timestamp; just drop it and let fetched_at be the
        # fallback sort key for this article.
        return None
