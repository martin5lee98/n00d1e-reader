"""
scrapers/summaries.py

One summary-length rule for every source, applied in fetch.py just
before saving (so no site module has to remember it).

Rule: at most SUMMARY_MAX_CHARS characters. A longer summary is cut at
the last sentence end (。！？…) within the limit, as long as that keeps
at least half of it; otherwise it is cut at the limit and ends in "…".

Chosen from real data (2026-10): nearly every source's summaries are
under 120 characters already; only occasional 少数派 ones go slightly over.
"""

from __future__ import annotations

import re
from typing import Optional

SUMMARY_MAX_CHARS = 120
SENTENCE_ENDS = "。！？…"


def trim_summary(text: Optional[str], limit: int = SUMMARY_MAX_CHARS) -> Optional[str]:
    if not text:
        return None
    text = re.sub(r"[\s　\xa0]+", " ", text).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_end = max(cut.rfind(ch) for ch in SENTENCE_ENDS)
    if last_end >= limit // 2:
        return cut[: last_end + 1]
    return cut[: limit - 1].rstrip("，、；：,;: .…") + "…"
