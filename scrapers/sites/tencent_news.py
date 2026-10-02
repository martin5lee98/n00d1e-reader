"""
scrapers/sites/tencent_news.py

Extracts articles from a Tencent News (腾讯新闻/QQ News) author/outlet
homepage, e.g. https://news.qq.com/omn/author/5049062 (财经杂志).

Extraction method: this is the one site so far that's a genuine JSON API,
not an embedded-JSON-in-HTML page. The author homepage makes three XHR
calls in sequence (getUserHomepageInfo, getQualification,
getSubNewsMixedList) -- only the third, getSubNewsMixedList, carries the
article list; the first two are profile/verification metadata not needed
for scraping headlines. Confirmed directly from a real captured response
(552KB, 20 items) provided by the user -- not guessed from API naming.

Endpoint:
    GET https://i.news.qq.com/getSubNewsMixedList
    Query params:
        offset_info  -- pagination cursor, see below. Empty string for
                         the first page.
        guestSuid    -- RESOLVED (was previously misunderstood as a
                         session/auth token -- it is not). QQ News gives
                         every author TWO interchangeable ids after a
                         2023 企鹅号 redesign: an old numeric id (e.g.
                         "5049062", used in the author URL
                         news.qq.com/omn/author/5049062) and a new opaque
                         id (e.g. "8QMc33tc7IYfvT/Q", used in
                         news.qq.com/omn/author/8QMc33tc7IYfvT%2FQ for
                         the SAME author -- confirmed by the user, who
                         found both URLs render the identical author page
                         for 财经杂志). guestSuid is that new-format id.
                         No cookie or session state is involved (checked
                         directly: the real browser request carried no
                         Cookie header at all). getUserHomepageInfo's
                         `suid` field is this same new-format id -- i.e.
                         that endpoint's real function here is old-id ->
                         new-id lookup, not auth/session issuance. See
                         resolve_guest_suid() below.
        tabId        -- "om_index" for the main article tab (confirmed
                         from the captured request).
        caller       -- "1" (unverified what this controls; passed through
                         as-is since it was present in the working request).
        from_scene   -- "103" (same -- passed through unverified).

    Note there is NO media_id/mediaid param on this endpoint at all --
    author identity is carried entirely through guestSuid.

Pagination cursor -- CONFIRMED from real data:
    The response's top-level `offsetInfo` field is a URL-encoded JSON
    string: {"lastPubTime": "<time of last item in this page>",
             "lastID": "<id of last item in this page>"}.
    Verified directly: in the captured response, offsetInfo decoded to
    {"lastPubTime": "2026-09-20 21:10:29", "lastID": "20260920A0CKZX00"},
    which matches the `time` and `id` fields of the actual last item in
    that page's newslist. To fetch the next page, take the last item's
    own time/id, build that same JSON shape, and URL-encode it as the
    offset_info param for the following request.

    hasNext (0 or 1) and total (total article count) are also present at
    the top level and can be used to know when to stop paginating.

Field mapping -- based on inspecting 4 real items from the captured
response (each item has 250+ fields; only the following were found
populated/relevant):
    id                       -> used to build url (see URL note below)
    title / longtitle        -> headline (identical in every item checked
                                 so far; `title` used, `longtitle` as
                                 fallback)
    url / surl / short_url / shareUrl
                              -> all identical in every item checked, but
                                 CONFIRMED (by the user, checking a real
                                 article) to point at the MOBILE renderer
                                 (view.inews.qq.com/a/{id}), not the
                                 canonical PC-facing URL a browser
                                 actually lands on (news.qq.com/rain/a/{id}
                                 for the same id). The API's url field is
                                 NOT used for this reason -- see
                                 build_article_url() below, which
                                 constructs the PC URL from `id` instead.
    time                     -> "2026-09-23 20:54:29", space-separated,
                                 no timezone -- same unverified CST
                                 assumption as thepaper.cn/yicai.com
    abstract                 -> re-examined across all 20 sampled items,
                                 not just a couple: for short/quote-style
                                 posts (single-sentence "观点分享" items)
                                 abstract is just the title + hashtags,
                                 basically harmless but redundant. For
                                 long-form articles, abstract is body text
                                 truncated at what looks like a fixed
                                 ~303-character ceiling, frequently
                                 cutting off mid-sentence or mid-word
                                 (e.g. "该院神经外...", "...同比增长
                                 33.9%。2027财年一季度（2026年二季度）阿里的
                                 AI云与算力服务..."). So: not "full text"
                                 exactly, but a truncated lede, which is
                                 exactly the kind of ugly mid-sentence cut
                                 a reader-facing description field
                                 shouldn't show. NOT used as description
                                 for this reason.
    nlpAbstract              -> re-examined across all 20 items: every
                                 populated value is a complete-sentence
                                 summary, not a truncation of `abstract`
                                 -- e.g. one item's nlpAbstract pulls a
                                 pointed quote that doesn't even appear
                                 near the start of that item's abstract,
                                 confirming it's a genuinely separate
                                 (likely model-generated) summary, not
                                 just a shorter cut of the same text.
                                 Empty for short/quote-style items (7/20
                                 in the sample -- exactly the items whose
                                 abstract was just title+hashtags). Used
                                 as description when present; left null
                                 otherwise -- deliberately NOT falling
                                 back to abstract, since that would
                                 reintroduce the mid-sentence-truncation
                                 problem described above.
    thumbnails_big / bigImage -> identical when both present; None for
                                 short items. thumbnails (smaller size)
                                 used as fallback when thumbnails_big is
                                 None, so short items still get an image.
    source / chlname / uinnick
                              -> all identical (outlet/column display
                                 name, e.g. "财经杂志") in every item
                                 checked -- this is NOT a byline. No
                                 author field was found anywhere in the
                                 250+ keys per item for this feed. This
                                 CONTRADICTS an earlier general assumption
                                 that Tencent Tech has author data --
                                 that may hold for a different Tencent
                                 News endpoint/section, but not for this
                                 author-homepage feed. author is always
                                 None here.

CAVEATS -- genuinely unverified, flagged rather than assumed:
  - Only tested against ONE author/media_id (5049062, 财经杂志). Field
    presence (e.g. whether author ever appears, whether abstract is
    always truncated the same way) is confirmed only for this feed, not
    for QQ News generally -- a different author or a topical
    (non-author) channel could have a different item shape.
  - articletype values (0, 4, 118) were observed but their meaning was
    not investigated -- not currently used to filter or branch, but may
    matter later (e.g. distinguishing video posts from articles).
  - build_article_url()'s news.qq.com/rain/a/{id} pattern is confirmed
    against exactly one article -- worth a spot-check across a few more
    before fully trusting it for every column.

CONFIRMED LIVE (2026-09-23, by the user):
  - getUserHomepageInfo?apptype=web&from_scene=103&isInGuest=1&chlid={id}
    works from a bare, unauthenticated request -- no Referer header, no
    Cookie, navigated directly in a browser address bar rather than
    fetched from within the page. Returned ret=0 and userinfo.suid
    exactly matching "8QMc33tc7IYfvT/Q", the same new-format id
    independently found by clicking through the site. This means the
    two-step fetch (resolve_guest_suid then fetch_column) should work
    unauthenticated from a GitHub Actions runner -- no session/cookie
    setup needed, no referer spoofing required (though setting one
    matching the working request is still cheap, honest insurance).
  - resolve_guest_suid()'s parsing (data["userinfo"]["suid"]) was
    re-verified against this exact real response, not just a
    hand-written fixture matching the field names -- confirmed correct.
"""

from __future__ import annotations

import json
import urllib.parse
from typing import Callable, Optional

from ..base import RawArticle

API_URL = "https://i.news.qq.com/getSubNewsMixedList"
USERINFO_URL = "https://i.news.qq.com/i/getUserHomepageInfo"

# Signature matches make_http_get in fetch.py, but this site needs query
# params and JSON parsing rather than a bare HTML GET, so it takes a
# slightly richer callable: (url, params) -> parsed JSON dict.
HttpGetJson = Callable[[str, dict], dict]


def resolve_guest_suid(media_id: str, http_get_json: HttpGetJson) -> str:
    """
    Resolves the old-format numeric media_id (e.g. "5049062") to the
    new-format opaque id (e.g. "8QMc33tc7IYfvT/Q") that getSubNewsMixedList
    actually requires as guestSuid. See module docstring for how this was
    figured out -- it's an id-format translation, not session/auth setup.

    CONFIRMED LIVE by the user (2026-09-23): a direct, unauthenticated
    browser request to this exact endpoint shape (chlid=5049062) returned
    ret=0 and userinfo.suid="8QMc33tc7IYfvT/Q" -- matching the new-format
    id independently found elsewhere on the site. The parsing below
    (data["userinfo"]["suid"]) was re-checked against that real response
    and is correct. Still raises loudly on a shape mismatch (KeyError-safe
    via .get() chains, then an explicit ValueError) in case a different
    author's response ever omits userinfo or suid.
    """
    params = {
        "apptype": "web",
        "from_scene": "103",
        "isInGuest": "1",
        "chlid": media_id,
    }
    data = http_get_json(USERINFO_URL, params)

    if data.get("ret") != 0:
        raise ValueError(
            f"getUserHomepageInfo returned ret={data.get('ret')} "
            f"(info={data.get('info')!r}) for media_id={media_id}"
        )

    suid = data.get("userinfo", {}).get("suid")
    if not suid:
        raise ValueError(
            f"getUserHomepageInfo response for media_id={media_id} had no "
            f"userinfo.suid -- response shape may have changed"
        )
    return suid


def fetch_column(
    media_id: str,
    http_get_json: HttpGetJson,
    max_pages: int = 1,
    guest_suid: Optional[str] = None,
    include_videos: bool = False,
) -> list[RawArticle]:
    """
    Fetch one author/outlet's article list from QQ News.

    media_id: the numeric author/outlet id, e.g. "5049062" for 财经杂志
        (found in the author homepage URL: news.qq.com/omn/author/{media_id}).
    http_get_json: injected GET-and-parse-JSON function, e.g.
        lambda url, params: httpx.get(url, params=params, headers=...).json()
        Kept separate from the plain http_get used by other site modules
        since this endpoint needs query params, not just a URL.
    max_pages: how many pages of getSubNewsMixedList to walk before
        stopping, following the offsetInfo cursor. Defaults to 1 (most
        recent ~20 items) since for a fast-polling column that's normally
        enough to catch new articles between runs; raise this for a
        first backfill of a newly-added column.
    include_videos: videos are skipped by default (see _is_video); pass
        True for a column that should keep them.
    guest_suid: the new-format id to use directly, skipping the
        resolve_guest_suid() lookup call. Pass this once you know a
        column's suid (e.g. after resolving it once and hardcoding it in
        the registry) to save an HTTP call on every fetch; if omitted,
        it's resolved from media_id automatically on each call.
    """
    if guest_suid is None:
        guest_suid = resolve_guest_suid(media_id, http_get_json)

    articles: list[RawArticle] = []
    offset_info = ""  # empty string = first page, confirmed from the captured request

    for _ in range(max_pages):
        params = {
            "offset_info": offset_info,
            "guestSuid": guest_suid,
            "tabId": "om_index",
            "caller": "1",
            "from_scene": "103",
        }
        data = http_get_json(API_URL, params)

        if data.get("ret") != 0:
            raise ValueError(
                f"getSubNewsMixedList returned ret={data.get('ret')} "
                f"(errmsg={data.get('errmsg')!r}) for media_id={media_id}"
            )

        newslist = data.get("newslist") or []
        for item in newslist:
            if not include_videos and _is_video(item):
                continue
            parsed = _parse_item(item)
            if parsed is not None:
                articles.append(parsed)

        if not data.get("hasNext"):
            break

        next_offset = data.get("offsetInfo")
        if not next_offset or not newslist:
            # No cursor to advance with, or an empty page -- stop rather
            # than loop forever.
            break
        offset_info = next_offset

    return articles


def build_article_url(article_id: str) -> str:
    """
    Builds the canonical PC-facing article URL from an id, rather than
    trusting the API's url/surl/short_url/shareUrl fields -- confirmed by
    the user that those all point at the MOBILE renderer
    (view.inews.qq.com/a/{id}), not the URL a desktop browser actually
    lands on for the same article (news.qq.com/rain/a/{id}). See module
    docstring's URL field note.

    UNVERIFIED so far: whether news.qq.com/rain/a/{id} holds for every
    article on this site, or just the one the user checked -- worth a
    spot-check across a few more articles (especially non-"rain"-channel
    content, if that varies) before fully trusting this for every column.
    """
    return f"https://news.qq.com/rain/a/{article_id}"


def _is_video(item: dict) -> bool:
    """
    The feed mixes text articles and videos. Confirmed from a real
    response (20 items, 5 videos) -- three signals that always agreed:
      - video_channel: an object for videos, null for articles
      - articletype:   "4" for videos, "0" for articles
      - id:            "…V…" for videos, "…A…" for articles
                       (e.g. 20261001V0BR0200 vs 20261002A07YDO00)
    Any one of the first two is enough to call it a video.
    """
    return bool(item.get("video_channel")) or str(item.get("articletype")) == "4"


def _parse_item(item: dict) -> Optional[RawArticle]:
    article_id = item.get("id")
    title = item.get("title") or item.get("longtitle")
    url = build_article_url(article_id) if article_id else None

    if not article_id or not url or not title:
        # Some items in a mixed feed can be non-article cards (live
        # streams, topic modules, etc) -- id/url/title being empty is
        # the cheapest signal to skip those rather than store junk.
        # UNVERIFIED how often this actually occurs in practice, since
        # all 20 sampled items had these fields populated.
        return None

    description = item.get("nlpAbstract") or None  # deliberately NOT falling back to abstract (full text)

    image_url = _first_url(item.get("thumbnails_big")) \
        or _first_url(item.get("bigImage")) \
        or _first_url(item.get("thumbnails"))

    return RawArticle(
        title=title,
        url=url,
        description=description,
        image_url=image_url,
        published_at=_normalize_published_at(item.get("time")),
        author=None,       # no author field found in this feed -- see module docstring
        raw_author_string=None,
        extra={
            "outlet_name": item.get("source") or item.get("chlname"),
            "media_id": item.get("media_id"),
            "articletype": item.get("articletype"),
            "read_count": item.get("readCount"),
            "comment_count": item.get("commentNum"),
        },
    )


def _first_url(value) -> Optional[str]:
    """Several image fields are lists-of-one (e.g. thumbnails: [...]) or None."""
    if isinstance(value, list) and value:
        return value[0]
    return None


def _normalize_published_at(time_str: Optional[str]) -> Optional[str]:
    """
    QQ News' `time` field looks like "2026-09-23 20:54:29" -- space
    separated, no timezone. Same unverified CST assumption as the other
    site modules; see thepaper.py's docstring for the caveat.
    """
    if not time_str:
        return None
    try:
        date_part, time_part = time_str.split(" ", 1)
        return f"{date_part}T{time_part}+08:00"
    except ValueError:
        return None


def build_next_offset_info(last_item: RawArticle) -> str:
    """
    Not currently called internally (fetch_column reads offsetInfo
    straight from the API response, which is simpler and doesn't require
    reconstructing the cursor by hand). Provided as a standalone helper
    in case a caller ever needs to resume pagination from a stored
    article rather than a live response -- e.g. "fetch everything newer
    than the last article we saved for this column" across separate runs.

    UNTESTED against the live API -- built by mirroring the exact shape
    confirmed in the captured response's offsetInfo, not independently
    verified to be accepted as a request param.
    """
    raise NotImplementedError(
        "Not yet needed -- fetch_column paginates using the API's own "
        "offsetInfo directly. Implement if cross-run resumption is required."
    )
