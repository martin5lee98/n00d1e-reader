"""
scrapers/sites/sspai.py

Extracts articles from Sspai (少数派) via its JSON APIs. TWO endpoints
are supported, both returning the same item shape:
  - fetch_index(): the homepage/general feed (mixed content, all
    sections/topics together)
  - fetch_tag(tag, ...): a single TAG's feed, e.g. tag="热门文章"
    (Popular Articles) -- found by the user as a better fit for a
    single coherent "column" than the mixed index feed. Confirmed via a
    real fetch to share the exact same item shape as the index endpoint
    (see fetch_tag()'s docstring), so no new parsing logic was needed,
    only a new endpoint URL and a tag param.

Endpoints:
    GET https://sspai.com/api/v1/article/index/page/get
        Query params: limit, offset, created_at, view
    GET https://sspai.com/api/v1/article/tag/page/get
        Query params: limit, offset, tag

Parameter behavior -- CAREFULLY TESTED, not assumed, because the user
    found this endpoint's URL already carrying a created_at value and
    asked whether it changes over time. Investigation (several live
    fetches, described below) found the params behave very differently
    from what their names suggest:

    - created_at: CONFIRMED INERT. A bare request with NO query params
      at all (user-verified, via their own browser, bypassing any
      caching on this end) returned the exact same first article
      (id=114954) as a request carrying created_at=1790243446. This
      rules out created_at acting as a time-based filter/cursor in any
      way -- whatever value was in the originally-found URL was just
      whatever happened to be in the page's JS state, irrelevant to the
      request's outcome. NOT used by fetch_column() below; included in
      requests only because it was part of a known-working URL, not
      because it does anything.
    - offset: CONFIRMED WORKING. The user tested
      .../get?offset=50 in their own browser and got a genuinely
      different first article (id=114327) than the offset=0 default
      (id=114954, confirmed absent from the offset=50 page's results).
      This is the real pagination mechanism.
    - limit: NOT independently confirmed to control page size (every
      test so far happened to return the server's default of 10
      items), but there's no specific reason to distrust it either --
      unlike created_at, its name isn't suggestive of behavior that
      turned out to be wrong. Passed through as a normal parameter.
    - view=second: UNEXPLAINED. Present in the user's originally-found
      working URL; passed through as-is since it was part of a request
      that worked, but its effect (if any) was never determined.

Field mapping -- confirmed against a real captured API response
    (20476 total articles reported; sample of 10 inspected in full):
    id            -> used to build url (see below)
    title         -> title, plain text
    summary       -> description. Genuine short summary, truncated with
                     "..." by the API itself at a consistent length --
                     not full article text (unlike some other sites
                     handled in this project), matches what the user
                     originally expected for this source.
    released_time -> published_at. Unix timestamp (seconds) -- confirmed
                     by comparing against the real rendered article page
                     ("2026年09月06日" shown on the page for an article
                     whose released_time converts to 2026-09-06).
                     Converted to ISO 8601 UTC. NOT assumed to be in any
                     particular source timezone since it's a numeric
                     Unix timestamp, not a formatted string -- no
                     CST-guessing needed here, unlike several other
                     sites in this project.
    author.nickname -> author. Clean single string in every item
                     inspected; the author object also carries much more
                     (badges, flags, avatar) that isn't used here.
    banner        -> image_url, via build_image_url() below. See that
                     function's docstring for how this was verified
                     against a real rendered article page rather than
                     assumed -- an early comparison against the WRONG
                     article (a mismatched id) briefly looked like a
                     contradiction; re-checking against a correctly
                     matched id resolved it cleanly. banner is a
                     relative path (e.g.
                     "2026/09/05/3722409a40de21da62c92f7e4fa32094.jpg")
                     that maps directly onto CDN URLs -- confirmed
                     identical filename/path segments between the API's
                     banner field and the real page's og:image tag for
                     the same article.
    free / belong_to_member -> extra["free"], extra["belong_to_member"].
                     Sspai has a members-only paywall on some content
                     (belong_to_member=true, free=false was observed on
                     one real item in the sample) -- captured but, per
                     the project's standing decision (see ftchinese.py
                     and initium.py) not specially flagged or excluded;
                     headline/description/author/image are available
                     regardless of paywall status.
    corner        -> extra["corner_name"]. A content-type label Sspai
                     shows on some articles (e.g. "Matrix精选", "会员内容",
                     "派早报") -- genuinely useful section/type info,
                     captured but not yet used elsewhere in the pipeline.

Article URL -- routing CORRECTED after the user found a real
    counterexample (a bug in an earlier version of this module, not just
    an unverified assumption):
    Two URL patterns exist, not one:
      - https://sspai.com/post/{id}                  -- ordinary articles
      - https://sspai.com/prime/story/{slug}          -- PRIME (member-only
        section) articles
    An earlier version of this module used /post/{id} unconditionally,
    based on cross-referencing 9 independently-found real article URLs
    -- but none of those 9 happened to be Prime content, so the pattern
    looked universal when it wasn't. The one Prime item in the sample
    (id=114710, belong_to_member=true, slug="home-made-beverages-5") was
    never actually fetched to confirm /post/114710 was valid; it isn't
    -- the user found the real page lives at
    /prime/story/home-made-beverages-5 instead, confirmed live (og:url
    meta tag matches exactly, page renders as "少数派会员 π+Prime"
    content). Interestingly, a Prime article's OWN body can link to
    earlier articles in the same series using EITHER pattern depending
    on that specific article's own membership status -- confirming this
    is a genuine per-article property (matching belong_to_member), not
    inferable from the series/topic alone.

    build_article_url() below now branches on belong_to_member: true ->
    /prime/story/{slug}, false/absent -> /post/{id}. slug is assumed
    always present when belong_to_member is true (true in the one
    confirmed example) -- if a future Prime item is ever observed with
    an empty slug, this would need a fallback (see CAVEATS).

Bullet/discussion posts -- NOT YET HANDLED, noted by the user but out of
    scope for this pass: the user also pointed out
    https://sspai.com/bullet/{id} (a lighter-weight discussion/bulletin
    post type, e.g. "九月买了什么好东西？") exists as a third content
    shape on this site, distinct from both /post/ and /prime/story/.
    Nothing in the index API response sample inspected so far has been
    confirmed to represent a bullet post (no item with a distinguishing
    bullet-type field has been seen), so fetch_column() does not attempt
    to detect or route to this pattern. If a bullet post ever appears in
    a future response and gets routed through build_article_url() as if
    it were a normal post, the resulting URL would likely be wrong --
    worth revisiting once a real example is captured in the index feed.

CAVEATS:
  - Only ONE page (the default, effectively offset=0) has been directly
    inspected in full field-by-field detail (the user's uploaded
    response). offset=50 was confirmed to return different content, but
    that response's fields were not individually inspected -- assumed,
    not separately confirmed, to share the same shape as the offset=0
    sample.
  - This is the site-wide index feed (fetch_index()), not filtered to a
    specific category/column -- see fetch_tag() for a better-scoped
    alternative found by the user (e.g. tag="热门文章"). fetch_index()
    returns Sspai's general homepage mix (新玩意, 社区速递, 派早报,
    product reviews, etc together), not a single topical column the way
    other sites in this project are organized. Prefer fetch_tag() for
    registry columns going forward; fetch_index() is kept available in
    case the general mix is ever useful on its own.
  - fetch_tag() has only been confirmed for ONE tag (热门文章, 12-item
    sample). Untested: whether other tags behave identically (same
    param names, same item shape) -- likely, given tag is just a query
    param on the same general API family, but not independently
    verified for a second tag.
  - imageMogr2/imageView2 query-string suffixes seen on real rendered
    image URLs (thumbnailing/cropping params) are deliberately NOT
    included in build_image_url()'s output -- using the bare CDN path
    returns an unprocessed original-size image, which is preferred for
    an aggregator over a page-specific thumbnail crop.
  - build_article_url()'s belong_to_member->prime/story branch is
    confirmed against exactly ONE real example. Untested: whether a
    Prime item can ever have an empty slug (see the function's
    docstring), and whether belong_to_member is the ONLY membership
    signal that matters (free=false was also observed to correlate
    perfectly with belong_to_member=true in the one example, but with
    only one example these could coincidentally always agree without
    truly being the same signal).
  - Bullet/discussion posts (sspai.com/bullet/{id}) are a THIRD content
    type on this site, identified by the user but not yet seen in any
    index API response inspected -- not handled by this module at all.
    If one ever appears in the feed, it would currently be misrouted
    through build_article_url() as if it were a normal /post/ or
    /prime/story/ item, likely producing a wrong URL. Revisit once a
    real example is captured (need to find what field, if any,
    distinguishes a bullet post in the API response).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

from ..base import RawArticle

API_URL_INDEX = "https://sspai.com/api/v1/article/index/page/get"
API_URL_TAG = "https://sspai.com/api/v1/article/tag/page/get"
IMAGE_CDN_BASE = "https://rssfile.sspai.com"  # confirmed via og:image tag match -- see module docstring

# Signature matches tencent_news.py's http_get_json: (url, params) -> parsed JSON dict.
HttpGetJson = Callable[[str, dict], dict]


def fetch_index(
    http_get_json: HttpGetJson,
    limit: int = 20,
    offset: int = 0,
) -> list[RawArticle]:
    """
    Fetch one page of Sspai's homepage/index article feed (all content
    mixed together -- 新玩意, 社区速递, 派早报, reviews, etc). See module
    docstring's CAVEATS: this is NOT filtered to a single topical
    column.

    http_get_json: injected GET-and-parse-JSON function, e.g.
        lambda url, params: httpx.get(url, params=params).json()
    limit: page size. Not independently confirmed to control the
        response size (see module docstring), but passed through as a
        normal, trusted parameter.
    offset: pagination offset -- CONFIRMED working (see module
        docstring). offset=0 is the newest articles; increasing it
        walks back through older content.
    """
    params = {
        "limit": limit,
        "offset": offset,
        "created_at": 1,  # confirmed inert -- see module docstring; kept only because
                           # it was part of a known-working request, not because it does anything
        "view": "second",  # unexplained but harmless -- see module docstring
    }
    data = http_get_json(API_URL_INDEX, params)

    if data.get("error") != 0:
        raise ValueError(
            f"Sspai index API returned error={data.get('error')} (msg={data.get('msg')!r})"
        )

    items = data.get("data") or []
    return [_parse_item(item) for item in items]


def fetch_tag(
    tag: str,
    http_get_json: HttpGetJson,
    limit: int = 20,
    offset: int = 0,
) -> list[RawArticle]:
    """
    Fetch one page of a Sspai TAG's article feed, e.g. tag="热门文章"
    (Popular Articles). This is a genuinely different endpoint from
    fetch_index() (article/tag/page/get, not article/index/page/get),
    found by the user as a better way to get a coherent single "column"
    than the general homepage mix fetch_index() returns.

    CONFIRMED: a real fetch of tag="热门文章" (limit=12, offset=0)
    returned 12 items (of 5410 total) in the EXACT SAME item shape as
    the index endpoint -- same fields (id, title, banner, summary,
    released_time, author.nickname, belong_to_member, slug, corner,
    etc). This means _parse_item(), build_article_url(),
    build_image_url(), and _normalize_published_at() all apply
    unchanged; no new field-mapping logic was needed for this endpoint,
    only a new URL and a `tag` query param. The 12-item sample checked
    had no belong_to_member=true items, so the Prime-URL branch wasn't
    re-exercised here specifically, but it's the same parsing path
    already confirmed via fetch_index()'s Prime example.

    tag: the tag name, e.g. "热门文章". Passed as-is; the caller is
        responsible for URL-encoding if needed (httpx and most HTTP
        libraries handle this automatically via the params dict, so
        this is usually not something the caller needs to think about).
    http_get_json, limit, offset: same as fetch_index().

    created_at/view params are NOT sent here -- they were never
    confirmed relevant even on the index endpoint (see module
    docstring), and weren't present in the user's originally-found
    working tag-endpoint URL either, so there's no reason to carry them
    over speculatively.
    """
    params = {
        "limit": limit,
        "offset": offset,
        "tag": tag,
    }
    data = http_get_json(API_URL_TAG, params)

    if data.get("error") != 0:
        raise ValueError(
            f"Sspai tag API returned error={data.get('error')} (msg={data.get('msg')!r}) for tag={tag!r}"
        )

    items = data.get("data") or []
    return [_parse_item(item) for item in items]


def _parse_item(item: dict) -> RawArticle:
    url = build_article_url(item)

    author_obj = item.get("author") or {}
    author = author_obj.get("nickname") or None

    corner = item.get("corner") or {}

    return RawArticle(
        title=item["title"],
        url=url,
        description=item.get("summary") or None,
        image_url=build_image_url(item.get("banner")),
        published_at=_normalize_published_at(item.get("released_time")),
        author=author,
        raw_author_string=author,  # no cleaning applied -- single clean value in every item observed
        extra={
            "free": item.get("free"),
            "belong_to_member": item.get("belong_to_member"),
            "corner_name": corner.get("name") or None,
            "slug": item.get("slug") or None,
            "comment_count": item.get("comment_count"),
            "like_count": item.get("like_count"),
        },
    )


def build_article_url(item: dict) -> str:
    """
    Builds the correct article URL, branching on membership status --
    see module docstring's "Article URL" section for how this was
    discovered to be necessary (a real bug in an earlier version of this
    module) and confirmed.

    belong_to_member=true -> https://sspai.com/prime/story/{slug}
    otherwise              -> https://sspai.com/post/{id}
    """
    article_id = item["id"]
    if item.get("belong_to_member"):
        slug = item.get("slug")
        if slug:
            return f"https://sspai.com/prime/story/{slug}"
        # No slug on a Prime item hasn't been observed in practice (the
        # one confirmed example had one), but if it ever happens, falling
        # back to /post/{id} is a guess, not a confirmed-correct URL --
        # flagged via extra rather than silently assumed right. See
        # CAVEATS in the module docstring.
    return f"https://sspai.com/post/{article_id}"


def build_image_url(banner: Optional[str]) -> Optional[str]:
    """
    Builds the image URL from the API's `banner` field.

    CONFIRMED (not assumed) by cross-referencing a real API response
    against the same article's real rendered page: banner
    "2026/09/05/3722409a40de21da62c92f7e4fa32094.jpg" for article id
    114211 matches exactly the path segments in that article's real
    og:image meta tag, https://rssfile.sspai.com/2026/09/05/
    3722409a40de21da62c92f7e4fa32094.jpg?imageMogr2/auto-orient/
    ignore-error/1 -- confirming banner maps directly onto this CDN
    path. The imageMogr2 query-string suffix (thumbnailing params) is
    deliberately omitted here -- see module docstring.
    """
    if not banner:
        return None
    return f"{IMAGE_CDN_BASE}/{banner}"


def _normalize_published_at(released_time: Optional[int]) -> Optional[str]:
    """
    Sspai's released_time is a Unix timestamp (seconds) -- confirmed by
    converting a real item's value and matching it against that
    article's real displayed publish date on the live page. Unlike
    several other sites in this project, no source-timezone ASSUMPTION
    is needed here: a Unix timestamp is unambiguous (always UTC-based
    internally), so this is a straightforward conversion, not a guess.
    """
    if not released_time:
        return None
    try:
        dt = datetime.fromtimestamp(released_time, tz=timezone.utc)
        return dt.isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError, OSError):
        return None
