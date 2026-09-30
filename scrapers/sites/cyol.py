"""
scrapers/sites/cyol.py

Extracts one weekly section (e.g. 冰点周刊) from 中国青年报's electronic
newspaper at zqb.cyol.com. The section has no list page or feed of its
own -- it only exists as printed pages (版面) in each issue.

Structure (checked against saved pages in docs/samples/, issue 2026-09-16):

  Layout page  https://zqb.cyol.com/pc/layout/YYYYMM/DD/node_NN.html
    - Every layout page lists ALL of that day's pages with their names:
        <a id="pageLink" href="node_05.html">05版：冰点周刊</a>
      so fetching node_01 tells us which pages carry the section.
    - Article links for that page:
        <ul class="news-list"><li><a href="../../../content/…/content_N.html">
    - No author, summary or image.

  Article page https://zqb.cyol.com/pc/content/YYYYMM/DD/content_N.html
    - <meta name="reporter" content="中青报·中青网记者 杜佳冰">
    - <h3> 引题 (e.g. "冰点特稿第1354期"), <h1> title, <h2> subtitle
    - body paragraphs inside <founder-content> as <p> elements
      (first ones may be images only).

Behaviour:
  - Looks at the section's weekday (Wednesday for 冰点周刊) over the last
    `weeks` weeks. A missing issue (404) or an issue without the section
    (e.g. a holiday) is skipped quietly.
  - Pages are identified by NAME, not number, so a move to other pages
    doesn't break anything.
  - A long story continued onto the next page appears on both pages with
    different content ids (e.g. 谁的房子谁的家 = content_430781 on 05版
    and content_430784 on 06版). De-duplicated by title within an issue,
    keeping the first (earlier page) link.
  - Summary = the article's first text paragraph (length rule in
    scrapers/summaries.py).
  - No thumbnails (by choice).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .. import authors
from ..summaries import trim_summary
from ..base import RawArticle

BASE = "https://zqb.cyol.com/pc/layout"
BEIJING = timezone(timedelta(hours=8))

HttpGet = Callable[[str], str]


def fetch_section(
    section_name: str,
    weekday: int,
    http_get: HttpGet,
    weeks: int = 2,
    today: Optional[datetime] = None,
) -> list[RawArticle]:
    """
    section_name: 版面 name to look for, e.g. "冰点周刊".
    weekday: Python weekday the section appears on (Monday=0 … Wednesday=2).
    weeks: how many recent issues to look at (2 normally; more to backfill).
    """
    now = today or datetime.now(BEIJING)
    articles: list[RawArticle] = []
    for d in _recent_weekdays(now.date(), weekday, weeks):
        articles.extend(_fetch_issue(d, section_name, http_get))
    return articles


def _recent_weekdays(today, weekday: int, count: int):
    days_back = (today.weekday() - weekday) % 7
    latest = today - timedelta(days=days_back)
    return [latest - timedelta(weeks=i) for i in range(count)]


def _get_or_none(http_get: HttpGet, url: str) -> Optional[str]:
    try:
        return http_get(url)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            return None  # issue not published (yet), or no such page
        raise


def _fetch_issue(day, section_name: str, http_get: HttpGet) -> list[RawArticle]:
    base = f"{BASE}/{day:%Y%m}/{day:%d}/"
    first_html = _get_or_none(http_get, base + "node_01.html")
    if first_html is None:
        return []

    # Which pages of this issue carry the section?
    soup = BeautifulSoup(first_html, "html.parser")
    pages = []
    for a in soup.select("a#pageLink, #pageList a"):
        if section_name in a.get_text() and a.get("href"):
            href = a["href"]
            if href not in pages:
                pages.append(href)
    if not pages:
        return []

    published_at = f"{day:%Y-%m-%d}T00:00:00+08:00"
    seen_titles: set[str] = set()
    results: list[RawArticle] = []

    for href in pages:
        page_url = urljoin(base, href)
        html = first_html if href == "node_01.html" else _get_or_none(http_get, page_url)
        if html is None:
            continue
        page = BeautifulSoup(html, "html.parser")
        for link in page.select("ul.news-list li a[href]"):
            title = _clean(link.get_text())
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            article_url = urljoin(page_url, link["href"])
            results.append(_fetch_article(article_url, title, published_at, http_get))
    return results


def _fetch_article(url: str, list_title: str, published_at: str, http_get: HttpGet) -> RawArticle:
    raw_author = None
    summary = None
    extra: dict = {}
    title = list_title

    html = _get_or_none(http_get, url)
    if html is not None:
        soup = BeautifulSoup(html, "html.parser")
        reporter = soup.find("meta", attrs={"name": "reporter"})
        if reporter and reporter.get("content", "").strip():
            raw_author = reporter["content"].strip()
        h1 = soup.select_one("#ozoom h1") or soup.find("h1")
        if h1 and _clean(h1.get_text()):
            title = _clean(h1.get_text())
        for tag, key in (("h3", "kicker"), ("h2", "subtitle")):
            el = soup.select_one(f"#ozoom {tag}")
            if el and _clean(el.get_text()):
                extra[key] = _clean(el.get_text())
        summary = _first_paragraph(soup)

    return RawArticle(
        title=title,
        url=url,
        description=summary,
        image_url=None,
        published_at=published_at,
        author=authors.clean_author_string(raw_author) if raw_author else None,
        raw_author_string=raw_author,
        extra=extra,
    )


def _first_paragraph(soup) -> Optional[str]:
    body = soup.find("founder-content") or soup.select_one("#ozoom")
    if body is None:
        return None
    for p in body.find_all("p"):
        if p.find("strong") and _clean(p.get_text()) == _clean(p.find("strong").get_text()):
            continue  # a bold sub-heading, not a paragraph
        text = _clean(p.get_text())
        if text:
            return trim_summary(text)
    return None


def _clean(s: str) -> str:
    return re.sub(r"[\s　\xa0]+", " ", s or "").strip()
