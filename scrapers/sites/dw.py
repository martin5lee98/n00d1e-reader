"""
scrapers/sites/dw.py

Extracts articles from a DW (德国之声) Chinese section page, e.g. 政治:
    https://www.dw.com/zh/政治/s-1681

Extraction method: the page is server-rendered with its data embedded as
    <script> window.__APP_STATE__={...}; </script>
(an Apollo/GraphQL cache). The entry keyed "/graph-api/zh/content/navigation/{id}"
holds the section's contentComposition -> informationSpaces -> components
(top_story_thematic_focus, news_thematic_focus, stories_thematic_focus, ...),
each with a `contents` list of teasers. Every teaser in those lists is
collected, de-duplicated by id.

Kept: __typename "Article" only, and not isLiveVideo. Videos, audio,
live blogs and anything else are skipped. The "panorama_thematic_focus"
box is skipped too: it holds older evergreen features (weeks or months
old), not current news. Checked against docs/samples/dw-zh-politics.html
(51 articles + 2 videos across 7 boxes -> 45 unique articles kept).

Field mapping:
  namedUrl           -> url ("https://www.dw.com" + path, percent-encoded)
  title              -> title
  teaser/shortTeaser -> description (teaser is the full one; the "news"
                        lists carry no teaser at all -> None)
  contentDate        -> published_at (already UTC with Z)
  mainContentImage.staticUrl -> image_url, with ${formatId} filled in by
                        IMAGE_FORMAT_ID (the "news" lists have no image)
  firstAuthorArray[].fullName -> author (、-joined)
  roadTeaserKicker   -> extra.kicker (e.g. "中国", "美国")

The same story can appear in several components (one with an image and
teaser, one without), so duplicates are merged, keeping whichever copy
has each field filled.

CAVEATS:
  - IMAGE_FORMAT_ID 605 confirmed by the user: 79623621_605.jpg loads as a
    1199x674 (16:9) image.
  - URLs use DW's slug path (/zh/{title-slug}/a-{id}). If DW edits a
    headline the slug can change, which would store the story twice.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional
from urllib.parse import quote

from ..base import RawArticle

BASE = "https://www.dw.com"
IMAGE_FORMAT_ID = "605"
SKIP_COMPONENTS = {"panorama_thematic_focus", "opinion_thematic_focus"}
OPINION_GENRES = {"COMMENT", "OPINION", "COMMENTARY"}
STATE_RE = re.compile(r"window\.__APP_STATE__\s*=\s*")

HttpGet = Callable[[str], str]


def fetch_section(section_url: str, http_get: HttpGet) -> list[RawArticle]:
    return parse_page(http_get(section_url))


def parse_page(html: str) -> list[RawArticle]:
    state = _app_state(html)
    merged: dict[int, dict] = {}
    order: list[int] = []
    for key, entry in state.items():
        if "/content/navigation/" not in key:
            continue
        content = ((entry or {}).get("data") or {}).get("content") or {}
        for item in _teasers(content.get("contentComposition") or {}):
            item_id = item.get("id")
            if item_id is None:
                continue
            if item_id not in merged:
                merged[item_id] = {}
                order.append(item_id)
            for k, v in item.items():
                if v not in (None, "", [], {}) and merged[item_id].get(k) in (None, "", [], {}):
                    merged[item_id][k] = v

    articles = []
    for item_id in order:
        article = _parse_item(merged[item_id])
        if article is not None:
            articles.append(article)
    return articles


def _app_state(html: str) -> dict:
    match = STATE_RE.search(html)
    if not match:
        raise ValueError("DW page has no window.__APP_STATE__")
    state, _ = json.JSONDecoder().raw_decode(html, match.end())
    return state


def _teasers(node):
    """Yields every dict found inside a `contents` list, anywhere below node."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in SKIP_COMPONENTS:
                continue
            if k == "contents" and isinstance(v, list):
                for item in v:
                    if isinstance(item, dict):
                        yield item
            else:
                yield from _teasers(v)
    elif isinstance(node, list):
        for v in node:
            yield from _teasers(v)


def _parse_item(item: dict) -> Optional[RawArticle]:
    if item.get("__typename") != "Article" or item.get("isLiveVideo"):
        return None
    if item.get("isOpinion") or (item.get("genre") or "").upper() in OPINION_GENRES:
        return None
    title = " ".join((item.get("title") or "").split())
    path = item.get("namedUrl") or ""
    if not title or not path.startswith("/"):
        return None

    names = [
        (p.get("fullName") or "").strip()
        for p in item.get("firstAuthorArray") or []
        if (p.get("personType") or "AUTHOR") == "AUTHOR"
    ]
    names = [n for n in names if n]
    author = "、".join(names) or None

    description = (item.get("teaser") or item.get("shortTeaser") or "").strip() or None

    return RawArticle(
        title=title,
        url=BASE + quote(path, safe="/-"),
        description=description,
        image_url=_image_url(item.get("mainContentImage")),
        published_at=item.get("contentDate"),
        author=author,
        raw_author_string=author,
        extra={
            "dw_id": item.get("id"),
            "kicker": item.get("roadTeaserKicker"),
            "genre": item.get("genre"),
        },
    )


def _image_url(image: Optional[dict]) -> Optional[str]:
    url = (image or {}).get("staticUrl")
    if not url:
        return None
    return url.replace("${formatId}", IMAGE_FORMAT_ID)
