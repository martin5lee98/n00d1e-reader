"""
scrapers/sites/latepost.py

Extracts articles from LatePost (晚点LatePost) via its news-list JSON
API. Four columns exist on this site, selected by a `programa` (sic --
site's own param name, not "program" or "programa" corrected) value:
    1 = 晚点独家 (Exclusive)
    2 = 人物访谈 (Interviews)
    3 = 晚点早知道 (Morning Briefing)
    4 = 长报道 (Long-form Reporting)

IMPORTANT ACCESS NOTE: latepost.com's robots.txt disallows automated
    fetching -- confirmed directly (this project's own web-fetch tool
    was refused with a ROBOTS_DISALLOWED error when attempting to open
    an article page). This means nothing about this site could be
    independently verified by fetching it directly; everything below is
    based on what the user captured themselves (a real curl request/
    response) plus corroborating evidence found via web search of
    syndicated copies of one article on OTHER sites (Toutiao, Xueqiu,
    Sina, etc -- LatePost content is widely republished). Treat this
    module's confidence level as correspondingly lower than sites this
    project was able to fetch and verify directly.

Endpoint (from the user's captured curl request):
    POST https://www.latepost.com/news/get-news-data
    Content-Type: application/x-www-form-urlencoded
    Body params: page, limit, programa
    Referer header was present in the captured request
    (https://www.latepost.com/news/index?proma={N}) -- UNTESTED whether
    the API requires a matching Referer to respond correctly, since
    robots.txt blocks this project from testing that independently.
    Safest to send one matching the programa being requested.

Field mapping -- ORIGINALLY based on the user's first captured response
    (5 items, programa=1 / 晚点独家) but SIGNIFICANTLY REVISED after the
    user tested programa=2 (人物访谈/Interviews) and found real
    differences this module didn't originally handle -- two genuine bugs
    were caught this way (an AttributeError crash on a differently-
    shaped label field, and a silent None date for year-included
    timestamps). Both are fixed below; see build_description(),
    _parse_labels(), and infer_published_at() for the corrected logic
    and what each was tested against.

    id           -> used to build url
    title        -> title. Often carries a "晚点独家丨", "独家丨", or
                    "晚点专访"/"独家对话"/"晚点对话" prefix baked directly
                    into the title text itself -- NOT stripped by this
                    module; kept as the site's own editorial framing.
    [abstract | intro | problem+answer] -> description, via
                    build_description() -- see that function's docstring
                    for the priority order. CORRECTED: an earlier version
                    only used `abstract`, which is empty for EVERY
                    programa=2 (interview) item in the real sample,
                    meaning interview-column articles would have had no
                    description at all under the original logic.
    cover        -> image_url, via urljoin against the site root.
    release_time -> published_at, via infer_published_at() below.
                    CORRECTED: the source field has been confirmed to
                    use TWO DIFFERENT FORMATS depending on article age
                    (see that function's docstring) -- an earlier
                    version only handled one of them.
    detail_url   -> NOT used for url construction -- see
                    build_article_url()'s docstring for why id is
                    preferred instead, even though detail_url is present
                    and usable.
    label        -> extra["labels"], via _parse_labels() -- see that
                    function's docstring for the shape correction
                    (a bare [""] list, not always a list of dicts).
    profile      -> extra["profile"]. Populated on programa=2 (interview)
                    items with the interviewee's title/role (e.g. "与爱
                    为舞创始人、CEO", "数学家", "美团核心本地商业CEO") --
                    genuinely useful context for an interview column,
                    captured but not yet surfaced elsewhere in the
                    pipeline. Empty on programa=1 items observed so far.
    is_dj        -> extra["is_dj"]. "1" on every programa=1 item, "0" on
                    every programa=2 item in the samples seen -- this
                    now looks more likely to mean "is 独家/exclusive"
                    specifically (matching that programa=1's 晚点独家
                    column is exclusives, while programa=2's interviews
                    are not framed as such) rather than some other flag,
                    though still not directly confirmed, just a stronger
                    correlation than before (2 programa values now
                    agreeing, not 1).
    programa     -> extra["programa"]. Echoes the request's own
                    programa param back on each item -- useful as a
                    sanity check that the response matches the requested
                    column, not otherwise used.

Author -- NOT present in this API's response at all (confirmed: no
    field resembling an author/byline exists anywhere in the sampled
    items). However, web-search of syndicated copies of one sampled
    article (id=3741, "2 亿日活之后，豆包开始收缩对话团队") on OTHER
    sites consistently show a byline "文丨董慧 陈佳惠 编辑丨高洪浩"
    ("Written by Dong Hui, Chen Jiahui; Edited by Gao Honghao") -- so
    author information likely DOES exist on the real LatePost article
    page, just not in this list-API response. This module does not
    attempt to fetch or scrape the detail page for author data (that
    would mean fetching N article pages per column poll, a much heavier
    operation, and would also hit the same robots.txt block that
    prevented this project from verifying anything else about this
    site) -- author is always None from this module. Revisit only if
    per-article author data becomes important enough to justify a
    second, heavier fetch per article.

CAVEATS:
  - Tested against TWO captured responses now: programa=1 (5 items) and
    programa=2 (4+ items shown, real response longer). programa=3 and 4
    remain untested -- assumed, not confirmed, to share one of these two
    shapes (most likely programa=1's headline/abstract shape for 晚点
    早知道, and possibly programa=2's shape or a third shape entirely
    for 长报道 -- genuinely unknown until tested).
  - infer_published_at()'s year-inference heuristic (for the no-year
    format only -- see that function's docstring for why older items
    don't need inference at all) is still UNVERIFIED at the one case
    that actually matters: a date very close to a year boundary in the
    no-year format specifically. The window where this matters is
    narrower than originally thought now that we know older dates
    include the year explicitly, but the no-year window's exact size
    (how many months of recency before LatePost includes the year) is
    itself not confirmed -- worth a manual spot-check once this scraper
    has run for a while.
  - The Referer header's necessity is unverified (see endpoint note
    above) -- included defensively since it was part of both known-
    working captured requests (programa=1 and programa=2).
  - is_dj's meaning is a stronger-but-still-unconfirmed guess now: "1"
    on every programa=1 (exclusives) item, "0" on every programa=2
    (interviews) item across both samples -- consistent with "is
    exclusive" but not directly confirmed by any labeled field.
  - build_description()'s priority order (abstract > intro >
    problem+answer) is confirmed to correctly handle both samples seen
    so far, but the interview Q&A combination (problem+answer) has only
    been checked for readability/reasonableness by inspection, not
    validated against how it will actually look in the homepage/column
    block UI -- worth a visual check once real interview-column data is
    flowing into the site.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Callable, Optional
from urllib.parse import urljoin

from ..base import RawArticle

SITE_ROOT = "https://www.latepost.com"
API_URL = f"{SITE_ROOT}/news/get-news-data"

COLUMN_NAMES = {
    1: "晚点独家",
    2: "人物访谈",
    3: "晚点早知道",
    4: "长报道",
}

# Signature: (url, form_data, headers) -> parsed JSON dict. Distinct from
# the simpler HttpGetJson used elsewhere in this project (GET + query
# params) since this endpoint is a POST with form-encoded body and
# (possibly) a required Referer header -- see module docstring.
HttpPostJson = Callable[[str, dict, dict], dict]


def fetch_column(
    programa: int,
    http_post_json: HttpPostJson,
    page: int = 1,
    limit: int = 10,
    today: Optional[date] = None,
) -> list[RawArticle]:
    """
    Fetch one page of one LatePost column.

    programa: 1-4, see module docstring for what each number means.
    http_post_json: injected POST-form-and-parse-JSON function, e.g.
        lambda url, data, headers: httpx.post(url, data=data, headers=headers).json()
    page, limit: pagination params, passed through as-is -- their
        behavior was not independently tested beyond the one captured
        request (page=1, limit=10), but they're conventional enough
        names that there's no specific reason to distrust them (unlike
        sspai.com's created_at, whose name was actively misleading).
    today: the date to use as "now" for infer_published_at()'s
        year-inference heuristic. Defaults to the real current date;
        exposed as a parameter mainly for testing.
    """
    if programa not in COLUMN_NAMES:
        raise ValueError(f"programa must be 1-4, got {programa!r}")

    form_data = {
        "page": page,
        "limit": limit,
        "programa": programa,
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "X-Requested-With": "XMLHttpRequest",
        # Included defensively -- untested whether required, see module
        # docstring's endpoint note.
        "Referer": f"{SITE_ROOT}/news/index?proma={programa}",
        "Origin": SITE_ROOT,
    }
    data = http_post_json(API_URL, form_data, headers)

    if data.get("code") != 1:
        raise ValueError(f"LatePost API returned code={data.get('code')} for programa={programa}")

    items = data.get("data") or []
    resolved_today = today or datetime.now(timezone.utc).date()
    return [_parse_item(item, resolved_today) for item in items]


def _parse_item(item: dict, today: date) -> RawArticle:
    article_id = item["id"]

    labels = _parse_labels(item.get("label"))

    return RawArticle(
        title=item["title"],
        url=build_article_url(article_id),
        description=build_description(item),
        image_url=build_image_url(item.get("cover")),
        published_at=infer_published_at(item.get("release_time"), today),
        author=None,  # not present in this API -- see module docstring
        raw_author_string=None,
        extra={
            "labels": labels,
            "is_dj": item.get("is_dj"),
            "programa": item.get("programa"),
            "profile": item.get("profile") or None,
        },
    )


def _parse_labels(raw_labels) -> list[dict]:
    """
    Parses the `label` field, which has been observed in TWO shapes:
      - a list of {label, label_url} dicts (programa=1 sample)
      - a list containing a single empty string, [""] (programa=2
        sample -- CORRECTED after the user's test: an earlier version
        of this function assumed every element was a dict and called
        .get() on it unconditionally, which would raise AttributeError
        on this exact shape -- a real crash, not just a wrong value,
        caught by re-testing against the user's new data.)
    Non-dict entries (including the empty-string case) are skipped
    rather than causing an error.
    """
    if not raw_labels:
        return []
    result = []
    for entry in raw_labels:
        if isinstance(entry, dict) and entry.get("label"):
            result.append({"label": entry.get("label"), "label_url": entry.get("label_url")})
    return result


def build_description(item: dict) -> Optional[str]:
    """
    Builds a description, since NOT ALL LatePost content types populate
    `abstract` -- CORRECTED after the user's programa=2 (人物访谈/
    Interviews) test showed every item with an EMPTY abstract, while
    carrying real content in other fields instead: `problem` (an
    interview question) and `answer` (a quoted response), and sometimes
    a short `intro` pull-quote.

    Priority order, first non-empty wins:
      1. abstract -- the headline/report-style summary (programa=1's
         shape, confirmed genuine and not boilerplate)
      2. intro -- a short pull-quote, seen populated on one programa=2
         item ("创业者从来不会失败") though empty on most others in that
         sample
      3. problem + answer, combined as "{problem} {answer}" -- the
         interview Q&A shape. Used as a last resort since it's the
         LONGEST of the three options (an `answer` in the sample ran to
         several sentences) -- fine as a description, but worth noting
         this could be longer than what a typical "headline + short
         description" card expects; no truncation is applied here,
         left to the display layer if it matters there.
    Returns None only if all of the above are empty -- meaning no
    content is available at all, not that content was actively
    discarded.
    """
    abstract = (item.get("abstract") or "").strip()
    if abstract:
        return abstract

    intro = (item.get("intro") or "").strip()
    if intro:
        return intro

    problem = (item.get("problem") or "").strip()
    answer = (item.get("answer") or "").strip()
    if problem and answer:
        return f"{problem} {answer}"
    if answer:
        return answer
    if problem:
        return problem

    return None


def build_article_url(article_id: str) -> str:
    """
    Builds the article URL from id: {SITE_ROOT}/news/dj_detail?id={id}

    The API response also includes a ready-made detail_url field
    ("/news/dj_detail?id={id}") that could be used directly -- id-based
    construction is used instead only for consistency with how most
    other site modules in this project build URLs (from an id field
    they already need for other purposes), not because detail_url is
    untrustworthy. Confirmed matching the user's independently-given
    example: id=3741 -> https://www.latepost.com/news/dj_detail?id=3741,
    exactly matching what the user reported opening in their browser.
    """
    return f"{SITE_ROOT}/news/dj_detail?id={article_id}"


def build_image_url(cover: Optional[str]) -> Optional[str]:
    """
    Resolves a relative cover path against the site root. Confirmed
    matching the user's independently-given example thumbnail exactly:
    cover "/uploads/cover/bc4ed0fb60b3c81697754bc40ddcbeb3.png" ->
    https://www.latepost.com/uploads/cover/bc4ed0fb60b3c81697754bc40ddcbeb3.png
    """
    if not cover:
        return None
    return urljoin(SITE_ROOT, cover)


RELEASE_TIME_WITH_YEAR_RE = re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日$")
RELEASE_TIME_NO_YEAR_RE = re.compile(r"^(\d{1,2})月(\d{1,2})日$")
RELEASE_TIME_RELATIVE = {"今天": 0, "昨天": 1}  # value = days before `today`


def infer_published_at(release_time: Optional[str], today: date) -> Optional[str]:
    """
    Converts LatePost's release_time field into an ISO 8601 timestamp.

    FOUR formats are now confirmed to coexist, not two -- this function
    has been corrected twice as real data revealed each new shape:
      - "今天" (today)        -- CONFIRMED in real programa=4 data (the
                                 user's most recent test). Resolves to
                                 `today` directly.
      - "昨天" (yesterday)    -- NOT directly shown to this project by
                                 the user, but added proactively based
                                 on strong external evidence: two
                                 independent real GitHub issues filed
                                 against RSSHub's own LatePost route
                                 (DIYgod/RSSHub#20877, #20878) report
                                 exactly this format appearing in real
                                 LatePost data ("昨天 23:01"), and a
                                 live fetch of latepost.com's own
                                 homepage (found via web search) shows
                                 "昨天" appearing as a real value
                                 alongside "09月21日" for the same
                                 article referenced in the user's own
                                 programa=4 paste. Resolves to
                                 `today - 1 day`.
      - "MM月DD日" (no year)   -- confirmed in programa=1 and programa=2
                                 data for recent-but-not-today/yesterday
                                 items. Year is INFERRED (see below).
      - "YYYY年MM月DD日" (year included) -- confirmed in programa=2 data
                                 for older items; LatePost's own data
                                 self-disambiguates once an article is
                                 old enough, so no inference is needed
                                 for this shape.

    Given today/yesterday are handled as their own explicit cases, the
    year-inference heuristic (see below) now only has to cover the
    narrower window between "the day before yesterday" and "whenever
    LatePost starts writing out the year" -- smaller than originally
    scoped, though the exact size of that window is still not confirmed.

    Year-inference heuristic (for the bare "MM月DD日" case only): if
    MM/DD interpreted in the CURRENT year would fall after `today`,
    assume it's from LAST year instead (a "recent items" feed shouldn't
    show a future date) -- otherwise assume the current year. Verified
    against one real case ("09月22日" fetched 2 days later, confirmed
    correct against independent syndicated copies of that article).
    Still NOT verified against a real year-boundary case.

    Regex/dict-based shape detection is used throughout rather than
    fixed-length string slicing -- an earlier version of this function
    used fixed-length slicing and had a real, silent bug from a
    miscounted character length (caught by the test suite). Explicit
    shape matching is deliberately more defensive against exactly that
    class of mistake.

    Time-of-day is unavailable in any of these formats (date-only), so
    this always returns midnight UTC for the resolved date -- same
    limitation as bbtnews.com.cn's date field; fetched_at remains the
    practical tiebreaker for same-day items.
    """
    if not release_time:
        return None
    release_time = release_time.strip()

    if release_time in RELEASE_TIME_RELATIVE:
        days_before = RELEASE_TIME_RELATIVE[release_time]
        resolved = date.fromordinal(today.toordinal() - days_before)
        return f"{resolved.isoformat()}T00:00:00Z"

    with_year_match = RELEASE_TIME_WITH_YEAR_RE.match(release_time)
    if with_year_match:
        year, month, day = (int(g) for g in with_year_match.groups())
        try:
            return f"{date(year, month, day).isoformat()}T00:00:00Z"
        except ValueError:
            return None

    no_year_match = RELEASE_TIME_NO_YEAR_RE.match(release_time)
    if no_year_match:
        month, day = (int(g) for g in no_year_match.groups())
        try:
            candidate = date(today.year, month, day)
        except ValueError:
            return None
        year = today.year - 1 if candidate > today else today.year
        try:
            final_date = date(year, month, day)
        except ValueError:
            return None
        return f"{final_date.isoformat()}T00:00:00Z"

    # No known shape matched -- unknown format, don't guess.
    return None
