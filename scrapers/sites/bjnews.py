"""
scrapers/sites/bjnews.py

Extracts articles from 新京报 (bjnews.com.cn) channel lists via the
mobile site's JSON API.

Endpoint (found by the user in the mobile site's network requests):
    GET https://m.bjnews.com.cn/bwnew/index-tj
        ?page=1&size=20&channel_id=<channel>&wz_id=1

Response shape (checked against a live response, 2026-09-30):
    {"status": 1, "info": "ok", "data": [ {...article...}, ... ]}
    `data` is a plain list. Fields used per item:
      uuid               -- unique article id
      title              -- headline
      desc               -- genuine per-article summary; sometimes ""
      publish_timestamp  -- Unix seconds (unambiguous; preferred over the
                            timezone-less "publish_time" string)
      pc_url             -- desktop article URL (m_url is the mobile one)
      cover              -- thumbnail on media.bjnews.com.cn
    There is NO author/byline field in the list, so author stays empty.

Caveats:
  - Only channel_id=97 (the 深度 stream) has been looked at.
  - No pagination: page 1 (20 items) every 6 hours is far more than the
    channel publishes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from ..base import RawArticle

API_URL = "https://m.bjnews.com.cn/bwnew/index-tj"

HttpGetJson = Callable[[str, dict], dict]


def fetch_channel(
    channel_id: int,
    http_get_json: HttpGetJson,
    size: int = 20,
) -> list[RawArticle]:
    data = http_get_json(
        API_URL,
        {"page": 1, "size": size, "channel_id": channel_id, "wz_id": 1},
    )
    if str(data.get("status")) != "1":
        raise ValueError(
            f"bjnews API returned status={data.get('status')!r} "
            f"info={data.get('info')!r} for channel_id={channel_id}"
        )

    articles = []
    for item in data.get("data") or []:
        parsed = _parse_item(item)
        if parsed is not None:
            articles.append(parsed)
    return articles


def _parse_item(item: dict) -> Optional[RawArticle]:
    title = (item.get("title") or "").strip()
    uuid = item.get("uuid")
    url = item.get("pc_url") or (
        f"https://www.bjnews.com.cn/detail-{uuid}.html" if uuid else None
    )
    if not title or not url:
        return None

    return RawArticle(
        title=title,
        url=url,
        description=(item.get("desc") or "").strip() or None,
        image_url=item.get("cover") or None,
        published_at=_normalize_published_at(item.get("publish_timestamp")),
        extra={"uuid": str(uuid) if uuid else None},
    )


def _normalize_published_at(ts) -> Optional[str]:
    if not ts:
        return None
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None
