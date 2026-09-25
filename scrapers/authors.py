"""
scrapers/authors.py

Shared author-string handling across all site scrapers.

Deliberately does NOT attempt to split a raw author string into a list of
individual names. Real examples seen from thepaper.cn alone:

    "邹碧航、朱嘉祺、赵晓梅"           -- 、-separated
    "澎湃新闻记者 龚思量、杨小舟"       -- role prefix + 、-separated
    "陆晔 端木异"                      -- space-separated, NO delimiter
    "季寺，贾敏"                       -- full-width comma
    "对谈/傅元峰 蓝江 吴天楚"          -- label + / + space-separated

The space-separated case (no delimiter at all) can't be split reliably --
Chinese given names are usually 2-4 characters, so naive space-splitting
*often* works, but "记者 龚思量" shows a role label can also be separated
only by a space, which would misparse as a name. Given that, we keep
`author` as a single cleaned display string rather than guessing at a
list. If a future feature (e.g. an author archive page) genuinely needs
structured multi-author data, that's a deliberate, separate task -- not
something to bolt on here speculatively.
"""

from __future__ import annotations

# Known role/label prefixes to strip from the front of a raw author string,
# per-site as they're discovered. Add to this list rather than writing
# per-site stripping logic -- keeps the behavior centralized and visible.
ROLE_PREFIXES = [
    "澎湃新闻记者",
    "记者",
    "对谈",
    "编译",
    "整理",
    "文",
    "撰文",
]


def clean_author_string(raw: str) -> str:
    """
    Strip known role/label prefixes from a raw author string. Does not
    split into multiple names -- see module docstring for why.
    """
    if not raw:
        return ""
    s = raw.strip()
    for prefix in ROLE_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):].lstrip("：: /").strip()
            break  # only strip one prefix -- avoid over-stripping on an
                    # unlucky match against a genuine name
    return s
