"""
scrapers/sites/bbtnews.py

Extracts articles from bbtnews.com.cn (北京商报 / Beijing Business Today)
column/list pages, e.g. https://www.bbtnews.com.cn/news/Recommend/.

Extraction method: plain CSS-selector scraping of server-rendered HTML.
Items live in <ul> inside a <div class="news-feed">, one <li> per
article.

IMPORTANT CACHING NOTE, kept here for anyone debugging this module
    later: an early attempt to inspect this page via this project's
    automated web-fetch tool returned content dated February 2021 --
    years stale -- even though the site was live and current in 2026.
    The user caught this by checking view-source in their own browser
    and pasting the real, current HTML directly. The lesson: for this
    site specifically (and possibly others), an automated fetch tool's
    result should not be trusted at face value if the dates look wrong
    -- cross-check against a real browser when in doubt, rather than
    building a scraper against stale cached content.

Field mapping -- from HTML the user pasted directly from their browser's
    view-source (i.e. real, current markup, not a stale fetch):
    li > .info > h4 > a[href]       -> url. Format:
                                        http://www.bbtnews.com.cn/{YYYY}/{MMDD}/{id}.shtml
                                        Note: source URLs use http://, not
                                        https://. NOT verified whether an
                                        https:// version of the same URL
                                        also works -- build_article_url()
                                        upgrades to https:// by default
                                        (see that function's docstring)
                                        since serving readers a plain-http
                                        link is best avoided if the site
                                        supports https, but this upgrade
                                        itself is unverified.
    li > .info > h4 > a (text)      -> title
    li > .info > p.words            -> description. The read-more link
                                        ("查看详情>>") is NESTED INSIDE
                                        this same <p> tag, appended right
                                        after the real description text --
                                        a naive .get_text() would include
                                        "查看详情>>" as trailing junk.
                                        extract_description() below
                                        removes the <a class="more"> node
                                        before extracting text, rather
                                        than trying to string-strip a
                                        trailing substring (more robust
                                        if the exact trailing text ever
                                        changes).
    li > .info > p.others > span[0] -> extra["outlet_name"] ("出处：...").
                                        Observed constant ("北京商报")
                                        across every item in the pasted
                                        sample -- captured but not used
                                        as a per-item field since it's
                                        site-level, not article-level,
                                        information.
    li > .info > p.others > span[1] -> author, via clean_author_string()
                                        below (see that function's
                                        docstring for the role-label
                                        stripping logic and why it's
                                        token-based rather than
                                        positional).
    li > .info > p.others > span[2] -> extra["web_editor"] ("网编：...").
                                        This is NOT a byline -- it's the
                                        person who published/formatted
                                        the piece for the web, a distinct
                                        role from the article's actual
                                        author(s). Deliberately kept
                                        separate from `author`, never
                                        merged into it.
    li > .info > p.others > span[3] -> published_at. Plain "YYYY-MM-DD",
                                        no time component and no
                                        timezone marker -- unlike several
                                        other sites in this project, this
                                        is COARSER than just "no
                                        timezone", it's date-only with no
                                        time-of-day at all. Stored as
                                        that date at midnight UTC (see
                                        _normalize_published_at) -- this
                                        means articles published on the
                                        same day will sort arbitrarily
                                        against each other by this field
                                        alone; fetched_at remains the
                                        more precise fallback/tiebreak
                                        sort key for same-day items, per
                                        the schema's original design.
    li > span.img.fL > a > img[src] -> image_url. Already a complete,
                                        direct CDN URL
                                        (upload.bbtnews.com.cn/...) --
                                        no CDN-prefix construction needed,
                                        unlike ftchinese.com or
                                        sspai.com. Only present on some
                                        items (image-less items simply
                                        lack this element entirely) --
                                        image_url is None when absent,
                                        not a placeholder.

CAVEATS:
  - Only tested against the ONE HTML fragment the user pasted (6 <li>
    items from a single page load of /news/Recommend/). Not yet run
    against a live fetch of a full page, and pagination (if any) has not
    been investigated at all.
  - clean_author_string()'s role-label stripping (实习记者, 记者) is
    based on exactly 2 real examples, both containing 实习记者 in a
    name-label-name shape. Untested against any other role-label word,
    and untested against a label appearing at the very start or very end
    of the string (only the middle position has been observed) -- the
    token-based approach should handle those positions correctly in
    principle, since it doesn't rely on position, but this hasn't been
    confirmed against a real example.
  - build_article_url()'s http-to-https upgrade is unverified -- see
    that function's docstring.
"""

from __future__ import annotations

from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..base import RawArticle

# Role/label words known to appear inline within an author string,
# stripped out token-by-token regardless of position -- see
# clean_author_string()'s docstring for why this is token-based rather
# than a positional regex.
ROLE_LABELS = {"实习记者", "记者"}

HttpGet = Callable[[str], str]


def fetch_column(list_url: str, http_get: HttpGet) -> list[RawArticle]:
    """
    Fetch and parse one bbtnews.com.cn column/list page.

    list_url: full URL of the list page, e.g.
        "https://www.bbtnews.com.cn/news/Recommend/"
    http_get: shared HTTP GET function, injected for testability. See
        the module docstring's caching note -- if results ever look
        suspiciously stale (old dates), that's a signal to check with a
        real browser rather than trust the fetch.
    """
    html = http_get(list_url)
    soup = BeautifulSoup(html, "html.parser")

    feed = soup.select_one(".news-feed")
    if feed is None:
        raise ValueError(f"'.news-feed' container not found at {list_url} -- page structure may have changed")

    articles = []
    for li in feed.select("ul > li"):
        parsed = _parse_item(li, list_url)
        if parsed is not None:
            articles.append(parsed)
    return articles


def _parse_item(li, base_url: str) -> Optional[RawArticle]:
    link_el = li.select_one(".info h4 a")
    if link_el is None:
        return None

    href = link_el.get("href", "")
    title = link_el.get_text(strip=True)
    if not href or not title:
        return None

    url = build_article_url(href, base_url)

    description = extract_description(li)

    others_spans = li.select(".info p.others span")
    # Fixed positional order confirmed across every item in the pasted
    # sample: [0]=出处 (outlet), [1]=作者 (author), [2]=网编 (web editor),
    # [3]=date. Indexed rather than matched by label text since the
    # labels are baked into each span's text content, not separate
    # attributes -- if the site ever reorders these, this would need
    # label-text matching instead of fixed indices.
    outlet_name = _span_text_after_label(others_spans, 0, "出处：")
    raw_author = _span_text_after_label(others_spans, 1, "作者：")
    web_editor = _span_text_after_label(others_spans, 2, "网编：")
    date_str = others_spans[3].get_text(strip=True) if len(others_spans) > 3 else None

    image_url = None
    img_el = li.select_one("span.img img[src]")
    if img_el:
        image_url = img_el.get("src") or None

    author = clean_author_string(raw_author) if raw_author else None

    return RawArticle(
        title=title,
        url=url,
        description=description,
        image_url=image_url,
        published_at=_normalize_published_at(date_str),
        author=author,
        raw_author_string=raw_author,
        extra={
            "outlet_name": outlet_name,
            "web_editor": web_editor,
        },
    )


def _span_text_after_label(spans, index: int, label: str) -> Optional[str]:
    """
    Extracts a span's text with a known leading label (e.g. "出处：")
    stripped off, e.g. span text "出处：北京商报" with label "出处："
    returns "北京商报". Returns None if the span doesn't exist at that
    index or doesn't start with the expected label (the latter case
    logs nothing but returns the raw text unstripped, on the theory
    that a changed label format is better surfaced as odd-looking data
    than silently dropped).
    """
    if index >= len(spans):
        return None
    text = spans[index].get_text(strip=True)
    if text.startswith(label):
        return text[len(label):].strip() or None
    return text or None


def extract_description(li) -> Optional[str]:
    """
    Extracts the article description from .info p.words, with the
    trailing "查看详情>>" read-more link removed. Removes the <a
    class="more"> element from the DOM before calling get_text(), rather
    than string-stripping a trailing substring afterward -- more robust
    if the exact link text or icon ever changes, since this approach
    doesn't depend on matching that text at all.
    """
    words_el = li.select_one(".info p.words")
    if words_el is None:
        return None

    more_link = words_el.select_one("a.more")
    if more_link:
        more_link.decompose()

    text = words_el.get_text(strip=True)
    return text or None


def clean_author_string(raw: str) -> str:
    """
    Strips known role/label words (see ROLE_LABELS) out of an author
    string, wherever they appear -- token-based rather than positional,
    because the one confirmed example ("王天逸 实习记者 鲁芹") has the
    label sitting BETWEEN two names, not at the start (unlike
    thepaper.cn's role-prefix pattern, which is always leading). This
    approach naturally also handles a label at the start or end,
    though only the middle position has actually been observed.

    Splits on whitespace, drops any token that's an exact match for a
    known role label, rejoins the rest. If every token happens to be a
    role label (shouldn't happen in practice), falls back to returning
    the original trimmed string rather than an empty one.
    """
    if not raw:
        return raw
    tokens = raw.strip().split()
    kept = [t for t in tokens if t not in ROLE_LABELS]
    return " ".join(kept) if kept else raw.strip()


def build_article_url(href: str, base_url: str) -> str:
    """
    Resolves a possibly-relative href against base_url, then upgrades
    http:// to https:// if present.

    CONFIRMED by the user: opening the plain http:// URL
    (http://www.bbtnews.com.cn/2026/0924/606792.shtml) in a real browser
    redirects to the https:// version, so upgrading eagerly here saves a
    redirect hop rather than risking a broken link.
    """
    absolute = urljoin(base_url, href)
    if absolute.startswith("http://"):
        absolute = "https://" + absolute[len("http://"):]
    return absolute


def _normalize_published_at(date_str: Optional[str]) -> Optional[str]:
    """
    bbtnews' date field is a bare "YYYY-MM-DD" with no time component at
    all -- coarser than most other sites in this project (which at
    least have a time, even if the timezone needed assuming). Stored as
    midnight UTC for that date. This means articles published the same
    day cannot be ordered relative to each other by published_at alone
    -- fetched_at (first-seen time) remains the practical tiebreaker for
    same-day items, consistent with the schema's original fallback-sort
    design.
    """
    if not date_str:
        return None
    try:
        # Validate shape without pulling in a full date-parsing library
        # for a format this simple.
        year, month, day = date_str.split("-")
        if not (len(year) == 4 and len(month) == 2 and len(day) == 2):
            return None
        return f"{date_str}T00:00:00Z"
    except ValueError:
        return None
