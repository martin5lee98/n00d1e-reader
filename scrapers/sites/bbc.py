"""
scrapers/sites/bbc.py

Extracts articles from a BBC RSS feed, e.g. BBC 中文 (Traditional):
    https://feeds.bbci.co.uk/zhongwen/trad/rss.xml

Written against the standard BBC RSS layout (title, description, link,
guid, pubDate, media:thumbnail). The feed itself could not be fetched from
the development environment, so check it once against a real copy
(docs/samples/bbc-zhongwen-trad.xml) -- see the CAVEATS below.

Field mapping:
  title            -> title
  description      -> description (BBC's own one-line summary)
  link             -> url, with tracking parameters removed
                      (BBC adds ?at_medium=RSS&at_campaign=rss...), so the
                      same story always gets the same URL / database row
  pubDate          -> published_at (RFC 822 with timezone -> UTC)
  media:thumbnail  -> image_url (largest one offered)
  (no author in BBC feeds)

Skipped: video and live pages (URL path contains /av/, /live/ or
/videos/), which are not readable articles.

CAVEATS (until checked against a real copy of the feed):
  - Exact thumbnail element / sizes.
  - Whether video items use the paths above.
"""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

import feedparser

from ..base import RawArticle

HttpGet = Callable[[str], str]

SKIP_PATH_PARTS = ("/av/", "/live/", "/videos/")


def fetch_feed(feed_url: str, http_get: HttpGet) -> list[RawArticle]:
    parsed = feedparser.parse(http_get(feed_url))
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Could not parse BBC feed {feed_url}: {parsed.bozo_exception}")

    articles = []
    for entry in parsed.entries:
        article = _parse_entry(entry)
        if article is not None:
            articles.append(article)
    return articles


def _parse_entry(entry) -> Optional[RawArticle]:
    title = (entry.get("title") or "").strip()
    link = entry.get("link") or entry.get("id") or ""
    if not title or not link.startswith("http"):
        return None

    url = clean_url(link)
    if any(part in urlsplit(url).path for part in SKIP_PATH_PARTS):
        return None

    return RawArticle(
        title=title,
        url=url,
        description=(entry.get("summary") or "").strip() or None,
        image_url=_thumbnail(entry),
        published_at=_published_at(entry),
        extra={"guid": entry.get("id")},
    )


def clean_url(link: str) -> str:
    """Drops the query string and fragment (BBC's at_* tracking tags)."""
    parts = urlsplit(link.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _thumbnail(entry) -> Optional[str]:
    candidates = list(entry.get("media_thumbnail") or [])
    candidates += [m for m in (entry.get("media_content") or []) if m.get("medium") in (None, "image")]
    candidates += [e for e in (entry.get("enclosures") or []) if (e.get("type") or "").startswith("image/")]
    urls = [(int(c.get("width") or 0), c.get("url") or c.get("href")) for c in candidates]
    urls = [(w, u) for w, u in urls if u]
    if not urls:
        return None
    return max(urls)[1]


def _published_at(entry) -> Optional[str]:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    dt = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")
