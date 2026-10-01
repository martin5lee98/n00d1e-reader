"""
scrapers/sites/cbnweek.py

Extracts articles from 第一财经杂志 (cbnweek.com) topic lists via its
JSON API.

Endpoints (found by the user) -- same response format for both:
    GET https://api.cbnweek.com/v5/topics/<id>/articles?page=1&per=20
        topic 14 = 新闻
    GET https://api.cbnweek.com/v5/columns/<id>/articles?page=1&per=20
        column 1044 = 有腔调 (published in monthly batches, all on one day)

Response shape (checked against a live response, 2026-10-02):
    {"code": 0, "msg": null,
     "meta": {"total_count", "current_page", "total_pages", "next_page"},
     "data": [ {"id", "title", "cover_url", "visit_times", "display_time"} ]}
  - display_time is a full ISO-8601 UTC timestamp ("2026-09-29T06:52:50.953Z").
  - cover_url is on imgcdn.cbnweek.com.
  - NO summary and NO author in the list.
  - Article page: https://www.cbnweek.com/article_detail/<id> (per the user).

`per` accepts any number, but the topic publishes roughly one article
every two days, so 20 per 6-hourly run is plenty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from ..base import RawArticle

API_URL = "https://api.cbnweek.com/v5/{kind}/{list_id}/articles"
ARTICLE_URL = "https://www.cbnweek.com/article_detail/{id}"

HttpGetJson = Callable[[str, dict], dict]


def fetch_topic(topic_id: int, http_get_json: HttpGetJson, per: int = 20) -> list[RawArticle]:
    return fetch_list("topics", topic_id, http_get_json, per)


def fetch_column(column_id: int, http_get_json: HttpGetJson, per: int = 20) -> list[RawArticle]:
    return fetch_list("columns", column_id, http_get_json, per)


def fetch_list(kind: str, list_id: int, http_get_json: HttpGetJson, per: int = 20) -> list[RawArticle]:
    data = http_get_json(API_URL.format(kind=kind, list_id=list_id), {"page": 1, "per": per})
    if data.get("code") not in (0, "0", None):
        raise ValueError(
            f"cbnweek API returned code={data.get('code')!r} msg={data.get('msg')!r} "
            f"for {kind}/{list_id}"
        )

    articles = []
    for item in data.get("data") or []:
        title = (item.get("title") or "").strip()
        article_id = item.get("id")
        if not title or article_id is None:
            continue
        articles.append(RawArticle(
            title=title,
            url=ARTICLE_URL.format(id=article_id),
            description=None,  # not provided by the list API
            image_url=item.get("cover_url") or None,
            published_at=_normalize_published_at(item.get("display_time")),
            extra={"visit_times": item.get("visit_times")},
        ))
    return articles


def _normalize_published_at(value: Optional[str]) -> Optional[str]:
    """'2026-09-29T06:52:50.953Z' -> '2026-09-29T06:52:50Z' (UTC, seconds)."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except ValueError:
        return None
