"""
d1_client.py

Minimal client for Cloudflare D1's HTTP/REST API, used by the GitHub Actions
fetcher (which runs outside the Workers runtime, so it can't use the
env.DB.prepare(...) binding API that the Astro site itself uses).

Auth: a Cloudflare API token with D1 edit permission, passed via the
CLOUDFLARE_API_TOKEN env var (set as a GitHub Actions secret).

Endpoint shape (Cloudflare D1 REST API):
  POST /accounts/{account_id}/d1/database/{database_id}/query
  Body: either
    {"sql": "...", "params": [...]}                 -- single statement
  or
    {"batch": [{"sql": "...", "params": [...]}, ...]} -- atomic batch,
       executed sequentially, all-or-nothing (rolls back on any failure)

Response:
  {"success": true, "result": [ { "results": [...], "meta": {...} }, ... ]}
  One entry in "result" per statement (batch) or a single entry (single query).
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx


class D1Error(Exception):
    """Raised when D1's REST API returns success=false or a non-2xx response."""
    def __init__(self, message: str, errors: Optional[list] = None, status_code: Optional[int] = None):
        super().__init__(message)
        self.errors = errors or []
        self.status_code = status_code


@dataclass
class D1Statement:
    sql: str
    params: list[Any]


class D1Client:
    """
    Thin wrapper around the D1 REST API. Not a general SQLite client —
    just enough to run our upsert / status-update queries from a
    GitHub Actions runner.
    """

    def __init__(
        self,
        account_id: Optional[str] = None,
        database_id: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.account_id = account_id or _require_env("CLOUDFLARE_ACCOUNT_ID")
        self.database_id = database_id or _require_env("D1_DATABASE_ID")
        self.api_token = api_token or _require_env("CLOUDFLARE_API_TOKEN")
        self.base_url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{self.account_id}/d1/database/{self.database_id}/query"
        )
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
        )

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def execute(self, sql: str, params: Optional[list[Any]] = None) -> dict:
        """Run a single statement. Returns the first result entry."""
        body = {"sql": sql, "params": params or []}
        return self._post(body)["result"][0]

    def batch(self, statements: list[D1Statement]) -> list[dict]:
        """
        Run multiple statements atomically (all succeed or all roll back).
        D1's REST batch endpoint recommends keeping batches to roughly
        100-500 statements for good performance; we chunk automatically
        (see batch_chunked) so callers don't have to think about this.
        """
        if not statements:
            return []
        body = {
            "batch": [
                {"sql": s.sql, "params": s.params} for s in statements
            ]
        }
        return self._post(body)["result"]

    def batch_chunked(
        self, statements: list[D1Statement], chunk_size: int = 200
    ) -> list[dict]:
        """
        Same as batch(), but splits into chunks so a single fetch run with
        (say) a few thousand upserts doesn't send one enormous request.
        Each chunk is its own atomic batch -- NOT atomic across chunks.
        For our use case (independent article upserts) that's fine: a
        failure in one chunk doesn't need to roll back unrelated articles.
        """
        results = []
        for i in range(0, len(statements), chunk_size):
            chunk = statements[i : i + chunk_size]
            results.extend(self.batch(chunk))
        return results

    def _post(self, body: dict) -> dict:
        resp = self._client.post(self.base_url, content=json.dumps(body))
        try:
            data = resp.json()
        except Exception as e:
            raise D1Error(
                f"D1 API returned non-JSON response (status {resp.status_code}): {resp.text[:500]}",
                status_code=resp.status_code,
            ) from e

        if resp.status_code >= 400 or not data.get("success", False):
            raise D1Error(
                f"D1 API error (status {resp.status_code}): {data.get('errors')}",
                errors=data.get("errors"),
                status_code=resp.status_code,
            )
        return data


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Set it as a GitHub Actions secret and pass it via `env:` in the workflow."
        )
    return val
