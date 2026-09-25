"""
scrapers/base.py

Shared types used by every site module in scrapers/sites/.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RawArticle:
    title: str
    url: str
    description: Optional[str] = None
    image_url: Optional[str] = None
    published_at: Optional[str] = None   # ISO 8601 string, normalized by the site module
    author: Optional[str] = None         # cleaned display string -- see scrapers/authors.py
    raw_author_string: Optional[str] = None  # original string as scraped, kept for reprocessing
    extra: dict = field(default_factory=dict)  # tags, audio_url, etc -- fields not yet worth a real column
