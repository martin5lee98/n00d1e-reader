"""
scrapers/sites/infzm.py

Extracts articles from 南方周末 (infzm.com) via the mobile site's JSON API,
e.g. the homepage 推荐 feed:

    GET https://api.infzm.com/mobile/contents?platform=wap&version=1.177.0
        &machine_id=<any 32-hex string>&user_id=&token=&member_type=
        &limit=20&page=1&term_id=998

machine_id: any random 32-character hex value works (checked 2026-10-12),
so a fixed made-up one is used -- never a real device's id.

Response (checked against docs/samples/infzm-998.json):
    {"code": 200, "data": {"banners": [], "news": [], "tops": [], "list": [...]}}
  list items:
    id, subject (title), author, publish_time ("2026-10-12 22:00:00",
    Beijing time), introtext (summary; list_desc is the same text),
    covers[0].file_path (relative, on images.infzm.com), column.title,
    type_tag ("", "投票", "专题"...), link_url, pay_property:
      content_type  "article" for normal stories, "subject" for 专题
                    (a container whose submods are articles that usually
                    also appear in the list on their own)
      mode          "meterage" = behind the metered paywall, "free" = open
  Article page: https://www.infzm.com/contents/<id>

Filtering: ONLY items with content_type == "article" and no link_url are
kept. That drops 专题 and -- whatever they turn out to be labelled --
videos, promotions and other non-article cards. (The homepage's 会员
promotion is not part of this API at all.)

Truncation: the response is cut off at ~32 KB (seen consistently in
downloads; limit/page appear to be ignored), so it is often not valid JSON.
parse_list() keeps every complete item before the cut instead of failing.
That's typically 5-10 stories per fetch.

Cover images are often stock photos (e.g. "VCG111617906050.jpg" from Visual
China Group) -- the registry entry sets store_images: False.
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from ..base import RawArticle

API_URL = "https://api.infzm.com/mobile/contents"
ARTICLE_URL = "https://www.infzm.com/contents/{id}"
IMAGE_BASE = "https://images.infzm.com/"
MACHINE_ID = "0123456789abcdef0123456789abcdef"  # made up on purpose

HttpGet = Callable[[str], str]

AUTHOR_LABELS = [
    "南方周末特约撰稿人", "南方周末特约撰稿", "南方周末记者", "南方周末实习生",
    "特约撰稿人", "特约撰稿", "实习生", "记者",
]


def fetch_term(term_id: int, http_get: HttpGet, limit: int = 20) -> list[RawArticle]:
    url = (
        f"{API_URL}?platform=wap&version=1.177.0&machine_id={MACHINE_ID}"
        f"&user_id=&token=&member_type=&limit={limit}&page=1&term_id={term_id}"
    )
    items = parse_list(http_get(url))
    if items is None:
        raise ValueError(f"infzm: no article list found in response for term {term_id}")
    articles = []
    for item in items:
        article = _parse_item(item)
        if article is not None:
            articles.append(article)
    return articles


def parse_list(text: str) -> Optional[list[dict]]:
    """data.list from the response, tolerating a cut-off response."""
    try:
        data = json.loads(text)
        return (data.get("data") or {}).get("list") or []
    except json.JSONDecodeError:
        pass
    start = text.find('"list":[')
    if start == -1:
        return None
    i = start + len('"list":[')
    decoder = json.JSONDecoder()
    items = []
    while i < len(text):
        while i < len(text) and text[i] in " ,\r\n\t":
            i += 1
        if i >= len(text) or text[i] == "]":
            break
        try:
            obj, i = decoder.raw_decode(text, i)
        except json.JSONDecodeError:
            break  # the item that was cut off
        items.append(obj)
    return items


def _parse_item(item: dict) -> Optional[RawArticle]:
    pay = item.get("pay_property") or {}
    if pay.get("content_type") != "article" or item.get("link_url"):
        return None
    article_id = item.get("id")
    title = (item.get("subject") or "").strip()
    if not article_id or not title:
        return None

    raw_author = (item.get("author") or "").strip() or None
    covers = item.get("covers") or []
    cover_path = (covers[0].get("file_path") if covers and isinstance(covers[0], dict) else None) or None

    return RawArticle(
        title=title,
        url=ARTICLE_URL.format(id=article_id),
        description=(item.get("introtext") or item.get("list_desc") or "").strip() or None,
        image_url=(IMAGE_BASE + cover_path.lstrip("/")) if cover_path else None,
        published_at=_published_at(item.get("publish_time")),
        author=clean_author(raw_author),
        raw_author_string=raw_author,
        extra={
            "column": (item.get("column") or {}).get("title"),
            "paywall": pay.get("mode"),
            "type_tag": item.get("type_tag") or None,
        },
    )


def clean_author(raw: Optional[str]) -> Optional[str]:
    """'南方周末记者 柴会群 南方周末实习生 王新瑞 周甜甜' -> '柴会群、王新瑞、周甜甜'"""
    if not raw:
        return None
    s = raw
    for label in AUTHOR_LABELS:
        s = s.replace(label, " ")
    names = [n for n in re.split(r"[\s　,，;；、]+", s) if n]
    return "、".join(names) or None


def _published_at(value: Optional[str]) -> Optional[str]:
    """'2026-10-12 22:00:00' (Beijing time) -> '2026-10-12T22:00:00+08:00'"""
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$", value.strip()):
        return None
    return value.strip().replace(" ", "T") + "+08:00"
