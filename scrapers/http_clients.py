"""
scrapers/http_clients.py

Shared HTTP client helpers used by scrapers/registry.py to build the
specific callable shape each site module needs. Centralized here (rather
than each site module rolling its own) so User-Agent, timeout, and
politeness settings are consistent everywhere, per the project's
standing decision to send an honest UA and respect robots.txt.

Three shapes exist because the site modules genuinely need different
things -- confirmed by inventorying every scrapers/sites/*.py module's
actual fetch_column/fetch_index/fetch_tag signature rather than assumed:
  - HTML-GET sites (thepaper, yicai, ftchinese, bbtnews, initium's RSS,
    latepost's... no, latepost is POST): need (url) -> str
  - JSON-GET-with-query-params sites (tencent_news, sspai): need
    (url, params: dict) -> dict
  - JSON-POST-with-form-body sites (latepost): need
    (url, data: dict, headers: dict) -> dict

A single client instance is created per process (module-level, built
lazily) so connections/keep-alive are shared across all columns fetched
in one run, rather than opening a new connection per column.
"""

from __future__ import annotations

import ssl
from pathlib import Path
from typing import Optional

import certifi
import httpx

CERTS_DIR = Path(__file__).parent / "certs"


def ssl_context() -> ssl.SSLContext:
    """
    The normal trusted-certificate list, plus any extra *.pem files in
    scrapers/certs/ (see the README there for why they're needed).
    Certificate checking stays fully on -- this only ADDS certificates.
    """
    ctx = ssl.create_default_context(cafile=certifi.where())
    for pem in sorted(CERTS_DIR.glob("*.pem")):
        ctx.load_verify_locations(cafile=str(pem))
    return ctx

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 "
    "(+https://n00dle.pages.dev/about-bot)"
)

_client: Optional[httpx.Client] = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=20.0,
            headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
            verify=ssl_context(),
        )
    return _client


def http_get(url: str) -> str:
    """Plain GET, returns response body as text. For HTML-page site modules."""
    resp = _get_client().get(url)
    resp.raise_for_status()
    return resp.text


def http_get_json(url: str, params: dict) -> dict:
    """GET with query params, returns parsed JSON. For tencent_news.py, sspai.py."""
    resp = _get_client().get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def http_post_json(url: str, data: dict, headers: dict) -> dict:
    """
    POST with form-encoded body and extra headers, returns parsed JSON.
    For latepost.py, which needs a Referer/Origin/X-Requested-With set
    per-request (see that module's docstring for why).
    """
    merged_headers = {**_get_client().headers, **headers}
    resp = _get_client().post(url, data=data, headers=merged_headers)
    resp.raise_for_status()
    return resp.json()
