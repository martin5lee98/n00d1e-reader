"""
scrapers/sites/leiphone.py

Extracts articles from 雷峰网's site-wide RSS feed:
    https://www.leiphone.com/feed

The feed is the whole site (about 20 items, roughly a day's worth), mostly
short 业界 news briefs and press releases. Only these are kept (checked
against docs/samples/leiphone-feed.xml):
  - exclusives: title starts with "独家", or
  - longer pieces: at least MIN_TEXT_CHARS characters of text in the item
and never the daily 雷峰早报 digest (/category/zaobao/). Items whose
title was already seen in the same feed are skipped too (the feed
sometimes carries the same news twice under different URLs).

Field mapping (the feed has no author or summary fields of its own; each
item's <description> is the start of the article as HTML):
  title             -> title
  link              -> url
  pubDate           -> published_at (with timezone -> UTC)
  description text  -> description: the opening text, with the
                       "作者丨… 编辑丨…" byline removed
  "作者丨name"       -> author, when the byline is there
  first real <img>  -> image_url (data-src or src). Thin banner images
                       (data-ratio < 0.3, height/width) and GIFs are
                       skipped; the URL is asked for at 740px wide.
"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from typing import Callable, Optional
from urllib.parse import urlsplit, urlunsplit

import feedparser
from bs4 import BeautifulSoup

from ..base import RawArticle

HttpGet = Callable[[str], str]

MIN_TEXT_CHARS = 1500
SKIP_PATHS = ("/category/zaobao/",)
BYLINE_RE = re.compile(r"(作者|编辑|撰文|审核|责编)\s*[丨|｜:：]\s*\S{1,12}")
AUTHOR_RE = re.compile(r"作者\s*[丨|｜:：]\s*([^\s丨|｜]{1,12})")
MIN_IMAGE_RATIO = 0.3


def fetch_feed(feed_url: str, http_get: HttpGet) -> list[RawArticle]:
    return parse_feed(http_get(feed_url))


def parse_feed(text: str) -> list[RawArticle]:
    # sanitize_html=False: feedparser's cleaning drops data-src/data-ratio,
    # which _first_image needs. The HTML is only read here, never shown.
    parsed = feedparser.parse(text, sanitize_html=False)
    if parsed.bozo and not parsed.entries:
        raise ValueError(f"Could not parse 雷峰网 feed: {parsed.bozo_exception}")
    articles, seen_titles = [], set()
    for entry in parsed.entries:
        article = _parse_entry(entry)
        if article is None or article.title in seen_titles:
            continue
        seen_titles.add(article.title)
        articles.append(article)
    return articles


def _parse_entry(entry) -> Optional[RawArticle]:
    title = " ".join((entry.get("title") or "").split())
    link = (entry.get("link") or "").strip()
    if not title or not link.startswith("http"):
        return None
    if any(p in link for p in SKIP_PATHS):
        return None

    soup = BeautifulSoup(entry.get("summary") or "", "html.parser")
    text = " ".join(soup.get_text(" ", strip=True).split())
    if not (title.startswith("独家") or len(text) >= MIN_TEXT_CHARS):
        return None

    m = AUTHOR_RE.search(text)
    author = m.group(1) if m else None
    description = " ".join(BYLINE_RE.sub(" ", text).split()) or None

    tags = [t.get("term") for t in entry.get("tags") or [] if t.get("term")]
    return RawArticle(
        title=title,
        url=_clean_url(link),
        description=description,
        image_url=_first_image(soup),
        published_at=_published_at(entry),
        author=author,
        raw_author_string=author,
        extra={"tags": tags},
    )


def _first_image(soup) -> Optional[str]:
    for img in soup.find_all("img"):
        src = (img.get("data-src") or img.get("src") or "").strip()
        if not src.startswith("http"):
            continue
        try:
            if float(img.get("data-ratio") or 1) < MIN_IMAGE_RATIO:
                continue  # thin header/footer banner
        except ValueError:
            pass
        bare = _clean_url(src)
        if bare.lower().endswith(".gif"):
            continue
        return bare + "?imageView2/2/w/740"
    return None


def _clean_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.replace("//", "/"), "", ""))


def _published_at(entry) -> Optional[str]:
    t = entry.get("published_parsed")
    if not t:
        return None
    dt = datetime.fromtimestamp(calendar.timegm(t), tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
