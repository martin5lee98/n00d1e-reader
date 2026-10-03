"""
scrapers/registry.py

Maps a column_key (matching the `column_key` column in D1's `columns`
table -- see schema.sql) to:
  - "fetch": a zero-argument closure that fetches that column's articles.
    Each closure bakes in whatever site-specific params that column
    needs (a node_id, media_id, tag, programa, etc) plus whichever HTTP
    client shape that site module requires (see scrapers/http_clients.py
    for why three different shapes exist). fetch.py calls this with no
    arguments at all -- it deliberately knows nothing about the
    differences between sites; that knowledge lives here.
  - "trust_description": whether this column's description field is
    genuine per-article content worth storing, vs boilerplate that
    should be left null. Per-column, not per-site, because this can
    vary even within one site (see thepaper.py's module docstring on
    why some columns might differ from others there). Defaults to True
    if omitted; set explicitly to False for columns known not to have a
    real description.
  - "store_images": whether to keep this column's thumbnail URLs.
    Defaults to True; set to False to store every article with
    image_url = NULL (fetch.py enforces this, and because the upsert
    overwrites image_url, re-scraping also clears old thumbnails).

Adding a new column on an ALREADY-SUPPORTED site (one with an existing
scrapers/sites/*.py module) should be a single new dict entry here, not
a new file -- see below for examples on thepaper (multiple columns, one
module) and sspai (two different fetch functions, one module).

Every entry below is built from real, confirmed values used earlier in
this project's development (real node ids, media ids, tag names, list
URLs) -- not placeholders. Where a value is a genuine guess or hasn't
been independently confirmed, it's flagged with a comment rather than
presented as certain.
"""

from __future__ import annotations

import os

from scrapers import http_clients
from scrapers.sites import (
    bbtnews,
    bjnews,
    cbnweek,
    cyol,
    ftchinese,
    initium,
    latepost,
    sspai,
    tencent_news,
    thepaper,
    yicai,
)

COLUMNS = {

    # ---------------------------------------------------------------
    # thepaper.cn (澎湃新闻) -- __NEXT_DATA__ JSON blob, see thepaper.py
    # ---------------------------------------------------------------
    "thepaper-sixiang-shichang": {
        "site": "thepaper",
        "outlet_name": "澎湃新闻",
        "column_name": "思想市场",
        "category": "culture",
        "source_url": "https://www.thepaper.cn/list_25483",
        "fetch_interval_minutes": 360,
        "fetch": lambda: thepaper.fetch_column(
            node_id="25483",
            list_url="https://www.thepaper.cn/list_25483",
            http_get=http_clients.http_get,
        ),
        # thepaper.py's module docstring: this site has no genuine
        # per-article description in the list JSON at all -- confirmed
        # by inspecting the sample, not assumed.
        "trust_description": False,
    },

    "thepaper-waijiao-xueren": {
        "site": "thepaper",
        "outlet_name": "澎湃新闻",
        "column_name": "外交学人",
        "category": "international",
        "source_url": "https://www.thepaper.cn/list_25481",
        "fetch_interval_minutes": 360,
        # Same page structure as 思想市场 (thepaper.py); no per-article
        # summary, so descriptions are always stored as NULL.
        "fetch": lambda: thepaper.fetch_column(
            node_id="25481",
            list_url="https://www.thepaper.cn/list_25481",
            http_get=http_clients.http_get,
        ),
        "trust_description": False,
    },

    # ---------------------------------------------------------------
    # yicai.com (第一财经) -- `var firstlist = [...]` JS blob, see yicai.py
    # ---------------------------------------------------------------
    "yicai-books": {
        "site": "yicai",
        "outlet_name": "第一财经",
        "column_name": "阅读周刊",
        "category": "culture",
        "source_url": "https://www.yicai.com/news/books/",
        "fetch_interval_minutes": 360,
        "fetch": lambda: yicai.fetch_column(
            list_url="https://www.yicai.com/news/books/",
            http_get=http_clients.http_get,
        ),
        # yicai.py's module docstring: NewsNotes confirmed to be a
        # genuine per-article summary (unlike thepaper.cn).
        "trust_description": True,
    },

    # ---------------------------------------------------------------
    # QQ News / Tencent News (腾讯新闻) -- author homepage JSON API,
    # see tencent_news.py. Only ONE author (财经杂志, media_id 5049062)
    # has actually been tested end-to-end.
    # ---------------------------------------------------------------
    "tencent-news-tech": {
        "site": "tencent_news",
        "outlet_name": "腾讯科技",
        "column_name": None,  # author homepage, not a named column within the outlet
        "category": "tech",
        "source_url": "https://news.qq.com/omn/author/5540552",
        "fetch_interval_minutes": 360,
        "fetch": lambda: tencent_news.fetch_column(
            media_id="5540552",
            http_get_json=http_clients.http_get_json,
            max_pages=1,
        ),
        # tencent_news.py's module docstring: nlpAbstract confirmed to
        # be a genuine summary (not the truncated-mid-sentence abstract
        # field) for substantive articles; empty for short ones, which
        # correctly becomes a null description rather than junk.
        "trust_description": True,
    },

    # ---------------------------------------------------------------
    # FT Chinese (FT中文网) -- HTML scraping via cn.ft.com, storing
    # www.ftchinese.com URLs per the user's explicit choice. See
    # ftchinese.py.
    # ---------------------------------------------------------------
    "ftchinese-yuanguan-jinsi": {
        "site": "ftchinese",
        "outlet_name": "FT中文网",
        "column_name": "远观近思",
        "category": "society",
        "source_url": "https://cn.ft.com/column/007000074",
        "fetch_interval_minutes": 360,
        "fetch": lambda: ftchinese.fetch_column(
            list_url="https://cn.ft.com/column/007000074",
            http_get=http_clients.http_get,
        ),
        "trust_description": True,
    },

    # ---------------------------------------------------------------
    # Initium Media (端傳媒) -- plain RSS, see initium.py. Only the
    # "opinion" tag has actually been fetched/confirmed; other tags are
    # assumed (not verified) to follow the same /tag/{slug}/rss/ pattern.
    # ---------------------------------------------------------------
    "initium-opinion": {
        "site": "initium",
        "outlet_name": "端傳媒",
        "column_name": "評論",
        "category": "society",
        # Left out of the ?r=cn version of the site (see astro-src/src/middleware.ts).
        "hide_in_cn": True,
        "source_url": "https://theinitium.com/tag/opinion/",
        "fetch_interval_minutes": 360,
        "fetch": lambda: initium.fetch_column(
            tag_slug="opinion",
            http_get=http_clients.http_get,
        ),
        "trust_description": True,
    },

    "bjnews-shendu": {
        "site": "bjnews",
        "outlet_name": "新京报",
        "column_name": "深度",
        "category": "society",
        "source_url": "https://www.bjnews.com.cn/depth",
        "fetch_interval_minutes": 360,
        # JSON API, channel 97 = 深度 (see bjnews.py). No author in the
        # list API, so articles show without a byline.
        "fetch": lambda: bjnews.fetch_channel(
            channel_id=97,
            http_get_json=http_clients.http_get_json,
        ),
        "trust_description": True,
    },

    "cyol-bingdian": {
        "site": "cyol",
        "outlet_name": "中国青年报",
        "column_name": "冰点周刊",
        "category": "society",
        "source_url": "https://zqb.cyol.com/",
        "fetch_interval_minutes": 360,
        # Weekly (Wednesday) printed section, read from the e-paper
        # (see cyol.py). Looks at the last 2 issues; for a one-off
        # backfill run:  CYOL_WEEKS=8 python3 fetch.py --column cyol-bingdian
        "fetch": lambda: cyol.fetch_section(
            section_name="冰点周刊",
            weekday=2,  # Wednesday
            http_get=http_clients.http_get,
            weeks=int(os.environ.get("CYOL_WEEKS", "2")),
        ),
        "trust_description": True,
    },

    "initium-report": {
        "site": "initium",
        "outlet_name": "端傳媒",
        "column_name": "專題",
        "category": "society",
        # Left out of the ?r=cn version of the site (see astro-src/src/middleware.ts).
        "hide_in_cn": True,
        "source_url": "https://theinitium.com/tag/report/",
        "fetch_interval_minutes": 360,
        # Same RSS-per-tag structure as initium-opinion (initium.py).
        "fetch": lambda: initium.fetch_column(
            tag_slug="report",
            http_get=http_clients.http_get,
        ),
        "trust_description": True,
    },

    # ---------------------------------------------------------------
    # Sspai (少数派) -- TWO fetch functions exist (see sspai.py):
    # fetch_tag() is preferred for a coherent single column (per the
    # user's later addition); fetch_index() is the earlier, mixed-
    # content general feed, kept available but not used as a registry
    # column below since fetch_tag is the better fit.
    # ---------------------------------------------------------------
    "sspai-hot-articles": {
        "site": "sspai",
        "outlet_name": "少数派",
        "column_name": "热门文章",
        "category": "tech",
        "source_url": "https://sspai.com/tag/热门文章",
        "fetch_interval_minutes": 360,
        "fetch": lambda: sspai.fetch_tag(
            tag="热门文章",
            http_get_json=http_clients.http_get_json,
            limit=20,
            offset=0,
        ),
        "trust_description": True,
    },

    # ---------------------------------------------------------------
    # bbtnews.com.cn (北京商报) -- HTML scraping, see bbtnews.py. Note
    # the module's caching-trap lesson: if a manual re-check of this
    # site ever looks stale, verify with a real browser before trusting
    # an automated fetch.
    # ---------------------------------------------------------------
    "bbtnews-recommend": {
        "site": "bbtnews",
        "outlet_name": "北京商报",
        "column_name": "推荐",
        "category": "finance",
        "source_url": "https://www.bbtnews.com.cn/news/Recommend/",
        "fetch_interval_minutes": 360,
        "fetch": lambda: bbtnews.fetch_column(
            list_url="https://www.bbtnews.com.cn/news/Recommend/",
            http_get=http_clients.http_get,
        ),
        "trust_description": True,
        # List-page thumbnails here are mostly licensed stock photos
        # (e.g. Visual China Group) that don't even appear as the
        # article's og:image -- don't store or show them.
        "store_images": False,
    },

    # ---------------------------------------------------------------
    # LatePost (晚点LatePost) -- JSON API via POST, see latepost.py.
    # robots.txt blocks direct verification of this site by this
    # project's own tools -- see that module's docstring for the lower
    # confidence level that implies. Four columns exist (programa 1-4);
    # only programa=1 has actually been tested against real captured
    # data so far. Columns 2-4 are included below on the assumption
    # (unverified) that they share the same response shape -- worth
    # confirming with a real capture before fully trusting them.
    # ---------------------------------------------------------------
    "cbnweek-news": {
        "site": "cbnweek",
        "outlet_name": "第一财经杂志",
        "column_name": "新闻",
        "category": "finance",
        "source_url": "https://www.cbnweek.com/",
        "fetch_interval_minutes": 360,
        # JSON API, topic 14 = 新闻 (see cbnweek.py). No summary or
        # author in the list, so headline + time only (like 澎湃).
        "fetch": lambda: cbnweek.fetch_topic(
            topic_id=14,
            http_get_json=http_clients.http_get_json,
        ),
        "trust_description": False,
    },

    "cbnweek-youyisi": {
        "site": "cbnweek",
        "outlet_name": "第一财经杂志",
        "column_name": "有意思",
        "category": "finance",
        "source_url": "https://www.cbnweek.com/",
        "fetch_interval_minutes": 360,
        # Same API format as the other cbnweek columns.
        "fetch": lambda: cbnweek.fetch_column(
            column_id=1040,
            http_get_json=http_clients.http_get_json,
        ),
        "trust_description": False,
    },

    "cbnweek-youqiangdiao": {
        "site": "cbnweek",
        "outlet_name": "第一财经杂志",
        "column_name": "有腔调",
        "category": "life",
        "source_url": "https://www.cbnweek.com/",
        "fetch_interval_minutes": 360,
        # Same API format as cbnweek-news, but a "columns" list.
        "fetch": lambda: cbnweek.fetch_column(
            column_id=1044,
            http_get_json=http_clients.http_get_json,
        ),
        "trust_description": False,
    },

    "latepost-exclusive": {
        "site": "latepost",
        "outlet_name": "晚点LatePost",
        "column_name": "晚点独家",
        "category": "finance",
        "source_url": "https://www.latepost.com/news/index?proma=1",
        "fetch_interval_minutes": 360,
        "fetch": lambda: latepost.fetch_column(
            programa=1,
            http_post_json=http_clients.http_post_json,
            page=1,
            limit=10,
        ),
        "trust_description": True,
    },
    "latepost-long-form": {
        "site": "latepost",
        "outlet_name": "晚点LatePost",
        "column_name": "长报道",
        "category": "finance",
        "source_url": "https://www.latepost.com/news/index?proma=4",
        "fetch_interval_minutes": 360,
        # UNCONFIRMED -- see programa=2's note above.
        "fetch": lambda: latepost.fetch_column(
            programa=4,
            http_post_json=http_clients.http_post_json,
            page=1,
            limit=10,
        ),
        "trust_description": True,
    },

}
