"""
scrapers/sites/yicai.py

Extracts articles from Yicai (第一财经 / yicai.com) column/list pages.

Extraction method: Yicai's list pages (e.g. yicai.com/news/books/) embed
the article list as a plain JS variable assignment:

    <script type="text/javascript">var firstlist = [{...}, {...}, ...];</script>

-- not a Next.js hydration blob like thepaper.cn, just a bare JSON array
literal assigned to a var. Simpler to extract: regex out the array,
json.loads it directly (no nested props.pageProps.* traversal needed).

URL pattern -- CONFIRMED against live data:
    https://www.yicai.com/news/{NewsID}.html

Verified 2026-09 by fetching the live column page (yicai.com/news/books/)
and cross-referencing against the __NEXT_DATA__-style sample the user
pasted: NewsID 103368867 ("现代医学必然走向人道主义吗｜荐书") appears at
the top of both the live page and the sample, linking to exactly
https://www.yicai.com/news/103368867.html. Two more of the user's
originally-pasted example headlines ("匈牙利小说家纳道什·彼得..." and
"复旦大学沈奕斐...") were also found live, confirming the column and
extraction are current, not stale.

Field notes:
  - NewsNotes is a genuine per-article description (unlike thepaper.cn) --
    trust_description = True is reasonable for yicai columns by default,
    though verify per-column since this has only been checked for the
    books column so far.
  - originPic is already an absolute CDN URL -- use directly.
  - Two author fields exist: NewsAuthor (string) and NewsAuthor1 (array).
    In every observed sample, NewsAuthor1 == [NewsAuthor] -- i.e. the
    array is just the same single string wrapped, not an independently
    populated multi-author list. NOT confirmed whether NewsAuthor1 ever
    contains more than one element for genuinely co-authored pieces --
    treat multi-element NewsAuthor1 as a signal worth spot-checking if
    it's ever observed, rather than assumed impossible.
  - CreateDate / EntityPublishDate: identical in every sample seen so far.
    Using CreateDate as the canonical published_at; format is
    "2026-09-17T21:38:51" (ISO-shaped, no explicit timezone -- assumed
    China Standard Time like thepaper.cn, same caveat applies: unverified
    against a known ground-truth event).
  - pubDate / showDate ("09-17 21:38") are truncated display strings with
    no year -- not used as published_at, kept in `extra` only if needed.
  - Pagination: the page shows a "加载更多内容" (load more) control below
    the initial list. Not yet investigated what endpoint it calls --
    fetch_column currently only returns the items present in the initial
    `firstlist` payload (in practice ~20 items per the samples seen).
    Revisit if a column needs deeper history per fetch than that.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from ..base import RawArticle

FIRSTLIST_RE = re.compile(
    r'var\s+firstlist\s*=\s*(\[.*?\]);',
    re.DOTALL,
)

HttpGet = Callable[[str], str]


def fetch_column(list_url: str, http_get: HttpGet) -> list[RawArticle]:
    """
    Fetch and parse one Yicai column's list page.

    list_url: full URL of the list page, e.g.
        "https://www.yicai.com/news/books/"
    http_get: shared HTTP GET function, injected for testability
        (see fetch.py's make_http_get).
    """
    html = http_get(list_url)
    match = FIRSTLIST_RE.search(html)
    if not match:
        raise ValueError(
            f"`var firstlist = [...]` not found at {list_url} -- "
            f"page structure may have changed"
        )

    try:
        items = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        raise ValueError(f"firstlist at {list_url} was not valid JSON: {e}") from e

    return [_parse_item(item) for item in items]


def _parse_item(item: dict) -> RawArticle:
    news_id = item["NewsID"]
    url = f"https://www.yicai.com/news/{news_id}.html"

    # NewsAuthor1 is array-shaped and, in every sample seen, equals
    # [NewsAuthor] -- prefer it since it's already in the right shape if
    # multi-author ever populates it, falling back to NewsAuthor for
    # robustness if NewsAuthor1 is ever missing/empty.
    author_list = item.get("NewsAuthor1") or []
    if author_list:
        # Join defensively in case NewsAuthor1 ever does hold >1 name --
        # matches the "single cleaned display string" convention used
        # across all site modules (see scrapers/authors.py).
        author = "、".join(a for a in author_list if a)
    else:
        author = item.get("NewsAuthor") or None

    raw_author = item.get("NewsAuthor") or None

    return RawArticle(
        title=item["NewsTitle"],
        url=url,
        description=item.get("NewsNotes") or None,
        image_url=item.get("originPic") or None,
        published_at=_normalize_published_at(item.get("CreateDate")),
        author=author or None,
        raw_author_string=raw_author,
        extra={
            "news_source": item.get("NewsSource"),
            "channel_name": item.get("ChannelName"),
            "topics": [t.get("topicName") for t in item.get("topics", []) if t.get("topicName")],
            "comment_count": item.get("CommentCount"),
            "news_hot": item.get("NewsHot"),
        },
    )


def _normalize_published_at(create_date: str | None) -> str | None:
    """
    Yicai's CreateDate looks like "2026-09-17T21:38:51" -- already ISO
    8601-shaped but with no timezone marker. Assumed China Standard Time
    (UTC+8), same unverified assumption as thepaper.cn -- see that
    module's docstring for the caveat.
    """
    if not create_date:
        return None
    if "+" in create_date or create_date.endswith("Z"):
        # Already has a timezone marker -- don't double-append one.
        return create_date
    return f"{create_date}+08:00"
