"""
scrapers/sites/myformosa.py

Extracts the opinion columns (專欄) from the 美麗島電子報 homepage.

Encoding: the site is Big5, not UTF-8 (<meta charset=big5>), so pages are
fetched as bytes and decoded as cp950 (Microsoft's Big5, a superset that
also covers the extra characters Taiwanese sites use).

Which items: only the opinion pieces, i.e. the <section> blocks inside the
FIRST div.span4 under div.content (15 on docs/samples/my-formosa.com.tw.html).
Each one:
    <figure><a href="/DOC_229902.htm"><img src="/News/upload/....jpg"></a></figure>
    <article>
      <h3><a href="/DOC_229902.htm" title="...">title</a></h3>
      <p>summary, cut off with ".."</p>
      <div class="news-item"> ... <h4><a href="/Brand/YuTzungChang">張佑宗</a></h4>
        <small>國立台灣大學社會科學院院長</small> ... </div>
    </article>

Field mapping:
  h3 a[href]          -> url (BASE + /DOC_{id}.htm)
  h3 a                -> title
  article > p         -> description (trailing ".." removed)
  .news-item h4 a     -> author
  .news-item small    -> extra.author_bio
  first figure img    -> image_url (BASE + /News/upload/...)
  (the author's portrait in .news-item is not used)

Dates: the homepage has none; each article page has exactly one, as
    <small class="date"><i class="icon-calendar"></i> 2026-10-12</small>
(day only, no time anywhere on the page -- checked against
docs/samples/my-formosa-article.html), stored as midnight Taipei time.
fill_dates() fetches the article page only for articles not yet stored
with a date (fetch.py passes in the set of those URLs), so after the
first run it is usually 0-2 page fetches per run. A failed page is just
left undated and retried next run.
"""

from __future__ import annotations

import re
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import RawArticle

BASE = "https://www.my-formosa.com.tw"  # the old .com domain is no longer used
ENCODING = "cp950"

HttpGetBytes = Callable[[str], bytes]


def decode(body: bytes) -> str:
    return body.decode(ENCODING, errors="replace")


def fetch_opinion(home_url: str, http_get_bytes: HttpGetBytes) -> list[RawArticle]:
    return parse_home(decode(http_get_bytes(home_url)))


def parse_home(html: str) -> list[RawArticle]:
    soup = BeautifulSoup(html, "html.parser")
    column = soup.select_one("div.content div.span4")
    if column is None:
        raise ValueError("美麗島電子報: no div.content div.span4 on the homepage")
    articles, seen = [], set()
    for section in column.select("section"):
        article = _parse_section(section)
        if article is not None and article.url not in seen:
            seen.add(article.url)
            articles.append(article)
    return articles


def _parse_section(section) -> Optional[RawArticle]:
    link = section.select_one("h3 a[href]")
    if link is None:
        return None
    href = link["href"].strip()
    if not re.search(r"/DOC_\d+\.htm$", href):
        return None
    title = " ".join((link.get("title") or link.get_text(" ", strip=True)).split())
    if not title:
        return None

    summary_el = section.select_one("article > p")
    summary = summary_el.get_text(" ", strip=True) if summary_el else ""
    summary = re.sub(r"(\.{2,}|…+)$", "", summary).strip() or None

    author_el = section.select_one(".news-item h4 a")
    author = author_el.get_text(strip=True) if author_el else None
    bio_el = section.select_one(".news-item small")

    img = section.select_one("figure img[src]")
    if img is not None and img.find_parent(class_="news-item") is not None:
        img = None  # that's the author's portrait, not the article image

    return RawArticle(
        title=title,
        url=urljoin(BASE, href),
        description=summary,
        image_url=urljoin(BASE, img["src"].strip()) if img is not None else None,
        author=author or None,
        raw_author_string=author or None,
        extra={"author_bio": bio_el.get_text(strip=True)} if bio_el else {},
    )


DATE_RE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")


def parse_article_date(html: str) -> Optional[str]:
    """'<small class="date">... 2026-10-12</small>' -> '2026-10-12T00:00:00+08:00'"""
    el = BeautifulSoup(html, "html.parser").select_one("small.date")
    m = DATE_RE.search(el.get_text(" ", strip=True)) if el else None
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}T00:00:00+08:00"


def fill_dates(articles: list[RawArticle], dated_urls: set[str], http_get_bytes: HttpGetBytes) -> None:
    """Sets published_at on articles not already stored with a date."""
    for a in articles:
        if a.published_at or a.url in dated_urls:
            continue
        try:
            a.published_at = parse_article_date(decode(http_get_bytes(a.url)))
        except Exception as e:
            print(f"    myformosa: no date for {a.url}: {type(e).__name__}: {e}")
