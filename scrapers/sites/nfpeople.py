"""
scrapers/sites/nfpeople.py

Extracts articles from a 南方人物周刊 (nfpeople.com) category page, e.g. 社会:
    https://www.nfpeople.com/category/21

Extraction method: plain server-rendered HTML (checked against
docs/samples/nfpeople-21.html, 10 articles). Each story is one
    <div class="leftbox lists"> <dl>
        <dt><a href="https://www.nfpeople.com/article/14315"><h2>title</h2></a></dt>
        <dd>summary</dd>
        <dd class="from">发表于：2026年09月28日 &nbsp; 作者：南方人物周刊记者 刘璐明</dd>
    </dl>

Field mapping:
  dt a[href]     -> url
  dt h2          -> title
  dd (not .from) -> description, cleaned (see clean_summary)
  dd.from 发表于 -> published_at (date only -> midnight Beijing time)
  dd.from 作者   -> author, job titles removed and names 、-joined:
                    "南方人物周刊记者 刘璐明 南方人物周刊特约撰稿 刘帆" -> "刘璐明、刘帆"
  (no images on the list page -> image_url None)

Summaries: some are a real standfirst, others are the first lines of the
article body, which can start with a photo caption ("...（图：受访者提供）")
or a short subheading ("房产纠纷"), repeat the headline, and end with
"..." where the site cut them off. clean_summary drops caption lines,
very short lines and headline repeats, and strips the trailing dots.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from bs4 import BeautifulSoup

from ..base import RawArticle

HttpGet = Callable[[str], str]

# Longest first, so "南方人物周刊实习记者" is removed before "记者".
AUTHOR_LABELS = sorted([
    "南方人物周刊记者", "南方人物周刊实习记者", "南方人物周刊特约记者",
    "南方人物周刊特约撰稿人", "南方人物周刊特约撰稿", "南方人物周刊主笔",
    "南方人物周刊实习生", "南方人物周刊编辑",
    "特约撰稿人", "特约撰稿", "特约记者", "实习记者", "实习生", "主笔", "编辑", "记者",
], key=len, reverse=True)

DATE_RE = re.compile(r"发表于[：:]\s*(\d{4})年(\d{1,2})月(\d{1,2})日")
AUTHOR_RE = re.compile(r"作者[：:]\s*(.+)$")
CAPTION_RE = re.compile(r"[（(]\s*图[：:]")
MIN_LINE_CHARS = 12  # shorter lines are subheadings, not summary text


def fetch_category(list_url: str, http_get: HttpGet) -> list[RawArticle]:
    return parse_list(http_get(list_url))


def parse_list(html: str) -> list[RawArticle]:
    soup = BeautifulSoup(html, "html.parser")
    articles = []
    for dl in soup.select(".lists dl"):
        article = _parse_item(dl)
        if article is not None:
            articles.append(article)
    return articles


def _parse_item(dl) -> Optional[RawArticle]:
    link = dl.select_one("dt a[href]")
    if link is None or "/article/" not in link.get("href", ""):
        return None
    title = " ".join(link.get_text(" ", strip=True).split())
    if not title:
        return None

    summary_el = next((dd for dd in dl.find_all("dd") if "from" not in (dd.get("class") or [])), None)
    from_el = dl.select_one("dd.from")
    from_text = " ".join(from_el.get_text(" ", strip=True).split()) if from_el else ""

    raw_author = None
    m = AUTHOR_RE.search(from_text)
    if m:
        raw_author = m.group(1).strip() or None

    return RawArticle(
        title=title,
        url=link["href"].strip(),
        description=clean_summary(summary_el.get_text("\n") if summary_el else None, title),
        published_at=_published_at(from_text),
        author=clean_author(raw_author),
        raw_author_string=raw_author,
    )


def clean_summary(text: Optional[str], title: str = "") -> Optional[str]:
    if not text:
        return None
    lines = [" ".join(l.split()) for l in text.splitlines()]
    kept = [
        l for l in lines
        if l and not CAPTION_RE.search(l) and len(l) >= MIN_LINE_CHARS
        and not (title and l.startswith(title[:8]))  # body repeating the headline
    ]
    s = " ".join(kept).strip()
    s = re.sub(r"(\.{2,}|…+)$", "", s).strip()
    return s or None


def clean_author(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    s = raw
    for label in AUTHOR_LABELS:
        s = s.replace(label, " ")
    names = [n for n in re.split(r"[\s　,，;；、]+", s) if n]
    return "、".join(dict.fromkeys(names)) or None


def _published_at(from_text: str) -> Optional[str]:
    m = DATE_RE.search(from_text)
    if not m:
        return None
    y, mo, d = m.groups()
    return f"{y}-{int(mo):02d}-{int(d):02d}T00:00:00+08:00"
