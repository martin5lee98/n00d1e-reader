"""
scrapers/sites/ftchinese.py

Extracts articles from FT Chinese (FT中文网) column pages.

Extraction method: plain CSS-selector scraping of server-rendered HTML --
no embedded JSON blob like thepaper.cn/yicai.com, no JSON API like QQ
News. Column pages list items as repeated `.item-container` blocks.

Domain split -- CONFIRMED by the user:
    - Fetch FROM d3a1cuk57dib8p.cloudfront.net: the user confirmed ftchinese.com has required
      login to view article LIST pages for the past few months, while
      d3a1cuk57dib8p.cloudfront.net (also an official FT Chinese domain) does not. This
      module fetches column/list pages from d3a1cuk57dib8p.cloudfront.net.
    - Store URLs pointing AT www.ftchinese.com: per the user's explicit
      choice (ftchinese.com is the more commonly recognized/used domain
      for this outlet), stored article URLs are built against
      www.ftchinese.com, not d3a1cuk57dib8p.cloudfront.net, even though we fetched the list
      from d3a1cuk57dib8p.cloudfront.net. NOTE: whether an anonymous reader can actually open
      an individual www.ftchinese.com/story/{id} page without hitting a
      login wall has NOT been verified -- the user's login-required
      observation was specifically about LIST pages. If individual
      article pages also turn out to be gated, this choice may need
      revisiting.

CONFIRMED duplicate-entry pattern (resolved by the user, not guessed):
    Column pages list each editorial piece as TWO separate
    .item-container blocks with near-identical timestamps (observed ~7.5
    minutes apart) and identical item-lead text:
      - /story/{id}   -- the real article. Has an image, and its link
                          carries a "locked" CSS class (paywall).
      - /interactive/{id} -- NOT an alternate or free version of the
                          article. Confirmed by the user: this is a
                          text-to-speech (TTS) audio-narration companion
                          page for the SAME story -- same text content,
                          plus an audio player bar at the top. It should
                          never be used as the article URL.
    This module filters out /interactive/ links entirely and only emits
    articles from /story/ links, rather than attempting to deduplicate a
    pair after the fact -- simpler and avoids ever accidentally keeping
    the wrong one of a pair if the timestamps or lead text ever diverge
    slightly.

Field mapping (from the HTML structure the user pasted):
    item-headline-link[href]  -> url (only kept if path starts with
                                  /story/; /interactive/ links skipped --
                                  see above)
    item-headline-link (text) -> title
    item-lead                 -> description AND author (see below).
                                  Per the user's original instruction,
                                  this was initially left un-parsed
                                  (author always null, full text kept in
                                  description). The user later reversed
                                  this after observing that column
                                  articles consistently prefix the
                                  byline directly into item-lead,
                                  terminated by a full-width colon "：",
                                  e.g. "刘远举：..." (single author) or
                                  "黄小雨、金涛：..." (two authors,
                                  、-joined -- same convention already
                                  used for thepaper.cn multi-author
                                  strings, see scrapers/authors.py).
                                  extract_author_prefix() below now
                                  splits this out: author gets the
                                  cleaned name(s), description gets the
                                  remaining text with the prefix
                                  stripped. See that function's
                                  docstring for the false-positive risk
                                  this introduces and how it's mitigated.
    item-time[data-pubdate]   -> published_at. This is the ONE site so
                                  far with an explicit, unambiguous
                                  timezone in its timestamp
                                  ("2026-09-20T12:19:20.000Z", ISO 8601
                                  with a Z suffix) -- no CST-assumption
                                  needed here, unlike thepaper.cn /
                                  yicai.com / tencent_news.
    figure[data-url]          -> image_url, built via
                                  build_image_url() below. Only present
                                  on has-image items; no-image items
                                  (which, per the pattern above, are
                                  always the /interactive/ TTS entries we
                                  filter out anyway) have none.

Image URL construction -- CONFIRMED by the user reading main.js's actual
    (minified) source directly, which corrects a few imprecisions in an
    earlier secondhand summary (via Claude Cowork) of the same file:
    Each figure's data-url ("/picture/9/000301499_piclink.jpg") is NOT a
    complete image path in the server-rendered HTML -- the visible image
    is injected by client-side JS (buildImageRequest() in main.js),
    which only runs in a real browser. Traced directly from the real
    minified source:
      1. Base: "https://dq4atoxl7csa1.cloudfront.net/unsafe/"
      2. Reads the figure's on-screen width/height (offsetWidth/Height
         or getBoundingClientRect).
      3. If devicePixelRatio > 1 (retina): doubles both width and
         height, and marks a "is-retina" CSS class.
      4. THEN, separately (not combined with step 3): if the width is
         not already an exact multiple of 100, rounds it up to the next
         multiple of 100 and recomputes height to preserve the aspect
         ratio. (This step also sets the "is-retina" class regardless of
         actual retina status -- a real quirk in the minified code, but
         it only affects a CSS class name, not anything the scraper
         needs.)
      5. Determines fit type: "contain" if the image's parent element's
         className matches /brand/, else "cover" (we always use "cover"
         -- see below).
      6. For "cover": builds a normal "{width}x{height}" size string.
         For "contain": builds a Thumbor auto-dimension string instead
         -- "{width}x0" or "0x{height}" (whichever preserves aspect
         ratio), NOT a normal WxH. Not implemented here since we always
         use "cover" and have no notion of a "brand" element to trigger
         "contain" in the first place.
      7. Also strips a few pre-existing Thumbor-style prefixes from
         data-url if present (fit-in/, an existing WxH/ segment,
         filters:.../) before rebuilding -- purely defensive code for a
         case that doesn't affect us: every data-url we've observed is a
         clean bare "/picture/..." path with none of these prefixes, so
         this stripping is always a no-op for our data. Documented here
         so it's clear this was checked, not overlooked.
      8. Primary URL: base + "{width}x{height}" (or the contain-style
         string) + "/" + the (possibly-stripped) data-url.
      9. Fallback URL: built from the SAME final width/height values as
         the primary URL (not independently computed) -- see "Fallback
         image URL" below.

    Since this scraper has no browser/layout context to compute a
    responsive size from, IMAGE_FIXED_SIZE below is a deliberately
    chosen fixed dimension (not a discovered constant) used for every
    image, for both the primary and fallback URLs alike -- matching the
    real code's behavior of using one consistent size across both.
    "700x395" (the original example) is used as a reasonable default --
    an aggregator thumbnail doesn't need retina-scaled or
    viewport-responsive sizing, so a fixed size is an intentional
    simplification of steps 2-4 above, not an attempt to replicate them.
    fit is always "cover" -- the "contain"/brand-detection logic (steps
    5-6) is not implemented, since it depends on page layout context
    (a parent element's class name) this scraper doesn't have.

Fallback image URL -- CONFIRMED, both by the user directly reading
    main.js's real source (see above -- the fallback is built from the
    same final width/height as the primary URL, not independently) and
    by the user separately testing the exact worked-example URL live,
    which loaded a real image (527x296 when 1200x676 was requested --
    same aspect ratio, just smaller; images.ft.com appears to cap output
    at the source image's real size rather than upscaling, so
    width/height are best read as a "no larger than" request, not a
    guaranteed output size).

    Earlier history, kept for context: this was originally reconstructed
    secondhand via Claude Cowork reading the same file, which flagged
    that it couldn't see the exact `?`/`=`/`&` separator characters (its
    tool blanked them out) and hadn't seen this URL actually fire on a
    live page. Both concerns are now resolved: the user's own direct
    reading of the source confirms the exact string-building logic
    (encodeURIComponent + "?source=ftchinese&width=...&height=...&fit=..."),
    and the user's live test confirms the resulting URL actually works.

CAVEATS:
  - Only tested against the HTML fragment the user pasted (one column
    page, 2 story/interactive pairs = effectively 1 real article's worth
    of markup). Not yet run against a live fetch of a full column page.
  - data-keywords attribute (comma-separated topic tags, e.g.
    "中国经济,消费,就业,GDP,经济学") is captured in extra but not yet
    used anywhere.
  - "contain" fit (vs our always-"cover") is not implemented -- see
    Image URL construction steps 5-6 above. Only matters for images
    whose parent element is classed "brand", which none of our observed
    examples are -- if a future column's images look stretched/distorted,
    this is the first thing to check.
  - extract_author_prefix()'s false-positive blocklist
    (KNOWN_NON_AUTHOR_LEAD_PREFIXES) is a manually curated starting list,
    not exhaustive -- see that function's docstring. A not-yet-seen
    2-4-character editorial phrase ending in "：" could still be
    misparsed as an author until added to the list.
  - The defensive data-url-prefix-stripping in the real main.js source
    (Image URL construction step 7) is a no-op for every data-url we've
    observed -- our code doesn't replicate that stripping since it's
    never needed to. If a future site's data-url is ever observed
    containing a "fit-in/", "filters:/", or pre-existing "WxH/" segment,
    build_image_url() and build_fallback_image_url() would need that
    stripping added.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import RawArticle

STORY_DOMAIN = "https://www.ftchinese.com"  # per the user's explicit choice -- see module docstring
IMAGE_CDN_BASE = "https://dq4atoxl7csa1.cloudfront.net/unsafe"
IMAGE_FIXED_SIZE = "700x395"  # deliberately chosen fixed size, not a discovered constant -- see module docstring

HttpGet = Callable[[str], str]


def fetch_column(list_url: str, http_get: HttpGet) -> list[RawArticle]:
    """
    Fetch and parse one FT Chinese column's list page.

    list_url: full URL of the column page on d3a1cuk57dib8p.cloudfront.net, e.g.
        "https://d3a1cuk57dib8p.cloudfront.net/column/007000074"
        (fetch from d3a1cuk57dib8p.cloudfront.net, not ftchinese.com -- see module docstring)
    http_get: shared HTTP GET function, injected for testability.
    """
    html = http_get(list_url)
    soup = BeautifulSoup(html, "html.parser")

    articles = []
    for container in soup.select(".item-container"):
        parsed = _parse_item(container)
        if parsed is not None:
            articles.append(parsed)
    return articles


def _parse_item(container) -> Optional[RawArticle]:
    link_el = container.select_one(".item-headline-link")
    if link_el is None:
        return None

    href = link_el.get("href", "")
    if not href.startswith("/story/"):
        # Filters out /interactive/{id} TTS-companion entries (and
        # anything else that isn't a /story/ link) -- see module
        # docstring for why this is a deliberate skip, not a bug.
        return None

    title = link_el.get_text(strip=True)
    if not title:
        return None

    url = urljoin(STORY_DOMAIN, href)

    lead_el = container.select_one(".item-lead")
    lead_text = lead_el.get_text(strip=True) if lead_el else None
    author, description = extract_author_prefix(lead_text)

    time_el = container.select_one(".item-time")
    published_at = time_el.get("data-pubdate") if time_el else None

    figure_el = container.select_one("figure[data-url]")
    image_url = build_image_url(figure_el.get("data-url")) if figure_el else None

    keywords_raw = container.get("data-keywords", "")
    keywords = [k for k in keywords_raw.split(",") if k] if keywords_raw else []

    return RawArticle(
        title=title,
        url=url,
        description=description,
        image_url=image_url,
        published_at=published_at,  # already ISO 8601 with explicit Z -- no normalization needed
        author=author,
        raw_author_string=lead_text,  # full original lead text, before author-prefix stripping
        extra={
            "keywords": keywords,
        },
    )


# Editorial/notice phrases that could false-positive match the
# name+colon extraction pattern below (2-4 CJK characters immediately
# followed by "："). Not exhaustive -- a starting list of the most
# likely offenders, extended as more are found in practice. A
# false-negative here (a real byline that happens to also be a common
# phrase) is far less likely than a false-positive (a phrase that
# happens to be 2-4 characters), so this list only needs to grow, not
# be perfectly complete, to be useful.
KNOWN_NON_AUTHOR_LEAD_PREFIXES = {
    "重要提示", "编者按", "编者注", "小编", "编辑注",
    "注意事项", "免责声明", "温馨提示", "特别提示", "读者须知",
}

AUTHOR_PREFIX_RE = re.compile(r"^([\u4e00-\u9fff]{2,4}(?:、[\u4e00-\u9fff]{2,4})*)：")


def extract_author_prefix(lead_text: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Splits a FT Chinese item-lead string into (author, description),
    based on the confirmed convention that column articles prefix the
    byline directly into the lead text, terminated by a full-width
    colon "：" -- e.g. "刘远举：..." or "黄小雨、金涛：..." (multiple
    authors, 、-joined). Returns (None, lead_text) unchanged if no such
    prefix is found.

    FALSE-POSITIVE RISK, mitigated but not eliminated: the underlying
    pattern (2-4 CJK characters + "：") cannot distinguish a real name
    from a short editorial phrase that happens to have the same shape
    (e.g. "重要提示：..." -- "Important notice:", 4 characters). This is
    handled with a manual blocklist (KNOWN_NON_AUTHOR_LEAD_PREFIXES)
    rather than a smarter pattern, since there's no clean regex-only way
    to distinguish "刘远举" (a name) from "重要提示" (a phrase) --
    they're the same shape. The blocklist is NOT exhaustive; it only
    catches phrases already identified as false positives. If a
    not-yet-listed phrase produces a wrong "author", add it to the set
    above rather than trying to make the regex itself smarter.
    """
    if not lead_text:
        return None, lead_text

    match = AUTHOR_PREFIX_RE.match(lead_text)
    if not match:
        return None, lead_text

    candidate = match.group(1)
    if candidate in KNOWN_NON_AUTHOR_LEAD_PREFIXES:
        return None, lead_text

    description = lead_text[match.end():].strip() or None
    return candidate, description


def build_image_url(data_url: Optional[str], size: str = IMAGE_FIXED_SIZE) -> Optional[str]:
    """
    Builds the CloudFront/Thumbor-proxied image URL from a figure's
    data-url attribute. The real site computes `size` dynamically from
    on-screen layout (see module docstring) -- this scraper has no
    layout context, so it uses a fixed size instead, overridable via the
    `size` param if a different fixed thumbnail size is ever wanted.
    """
    if not data_url:
        return None
    return f"{IMAGE_CDN_BASE}/{size}{data_url}"


def build_fallback_image_url(data_url: Optional[str], size: str = IMAGE_FIXED_SIZE) -> Optional[str]:
    """
    Builds the images.ft.com fallback URL for a figure's data-url.

    CONFIRMED LIVE by the user: the exact worked example this
    construction is based on was opened directly and returned a real
    image (527x296, same aspect ratio as the requested 1200x676 -- see
    module docstring's "Fallback image URL" section for what that
    implies about width/height being a ceiling, not a guarantee).

    Still not called automatically anywhere in this module -- the
    primary CloudFront path (build_image_url()) works fine on its own,
    so this remains a caller-invoked fallback for if/when a primary URL
    is found broken, rather than a first choice.
    """
    if not data_url:
        return None

    width, height = _parse_size(size)
    unresized_cloudfront_url = f"{IMAGE_CDN_BASE}{data_url}"  # no size segment, per Cowork's reading
    encoded = urllib.parse.quote(unresized_cloudfront_url, safe="")

    return (
        f"https://images.ft.com/v3/image/raw/{encoded}"
        f"?source=ftchinese&width={width}&height={height}&fit=cover"
        # fit=contain for "brand"-classed containers per Cowork's read of
        # main.js -- not handled here; this module has no notion of the
        # element class an image would render inside, so "cover" is used
        # unconditionally.
    )


def _parse_size(size: str) -> tuple[str, str]:
    """Splits a "WxH" string like "700x395" into ("700", "395")."""
    match = re.match(r"^(\d+)x(\d+)$", size)
    if not match:
        raise ValueError(f"Expected a WxH size string like '700x395', got {size!r}")
    return match.group(1), match.group(2)
