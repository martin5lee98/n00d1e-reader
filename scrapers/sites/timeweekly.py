"""
scrapers/sites/timeweekly.py

Extracts articles from a 时代周刊 (time-weekly.com) category via its JSON
list endpoint, e.g. 要闻 (category 6):
    https://www.time-weekly.com/category/6/posts?page=1&limit=40

Response (docs/samples/time-weekly-posts.json, first 3 items of a real one):
    {"status":200, "msg":"ok", "data":{"items":[{
        "id":333467,
        "href":"https://www.time-weekly.com/post/333467",
        "title":"...", "digest":"...", "author":"马欢",
        "photo_title":"https://marmot-obs.timesmedia.com.cn/...jpg?x-oss-process=image/resize,m_fixed,w_300",
        "publish_at":"2026-10-13 21:20:57"}, ...], "page":"1", "limit":"40"}}

Field mapping:
  href (or /post/{id})  -> url
  title                 -> title
  digest                -> description
  author                -> author
  photo_title           -> image_url, resized to IMAGE_WIDTH instead of the
                           list's 300px thumbnail (Aliyun OSS resize param)
  publish_at            -> published_at (Beijing time -> +08:00)
"""

from __future__ import annotations

import json
import re
from typing import Callable, Optional

from ..base import RawArticle

BASE = "https://www.time-weekly.com"
IMAGE_WIDTH = 600

HttpGet = Callable[[str], str]


def fetch_category(category_id: int, http_get: HttpGet, limit: int = 20) -> list[RawArticle]:
    url = f"{BASE}/category/{category_id}/posts?page=1&limit={limit}"
    return parse_list(http_get(url))


def parse_list(text: str) -> list[RawArticle]:
    payload = json.loads(text)
    if payload.get("status") != 200:
        raise ValueError(f"时代周刊 API error: {payload.get('status')} {payload.get('msg')}")
    articles = []
    for item in (payload.get("data") or {}).get("items") or []:
        article = _parse_item(item)
        if article is not None:
            articles.append(article)
    return articles


def _parse_item(item: dict) -> Optional[RawArticle]:
    title = " ".join((item.get("title") or "").split())
    url = (item.get("href") or "").strip()
    if not url and item.get("id"):
        url = f"{BASE}/post/{item['id']}"
    if not title or not url.startswith("http"):
        return None
    author = (item.get("author") or "").strip() or None
    return RawArticle(
        title=title,
        url=url,
        description=(item.get("digest") or "").strip() or None,
        image_url=_image_url(item.get("photo_title")),
        published_at=_published_at(item.get("publish_at")),
        author=author,
        raw_author_string=author,
        extra={"post_id": item.get("id")},
    )


def _image_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return re.sub(r"(resize,[^&]*?w_)\d+", rf"\g<1>{IMAGE_WIDTH}", url.strip())


def _published_at(value: Optional[str]) -> Optional[str]:
    """'2026-10-13 21:20:57' (Beijing time) -> '2026-10-13T21:20:57+08:00'"""
    if not value or not re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?$", value.strip()):
        return None
    return value.strip().replace(" ", "T") + "+08:00"
