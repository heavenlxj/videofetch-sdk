"""Sync + Async HTTP clients with retry, error mapping and typed resources.

Design mirrors the OpenAI/Stripe SDKs:
  VideoFetch(api_key)        → sync   client:  client.downloads.create(...)
  AsyncVideoFetch(api_key)   → async  client:  await client.downloads.create(...)
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Optional

import httpx

from .errors import VideoFetchError, map_error
from .models import Download, DownloadList, TrimSpec, VideoInfo

DEFAULT_BASE_URL = os.getenv("VIDEOFETCH_BASE_URL", "https://api.vidfetch.dev")
DEFAULT_MAX_RETRIES = 2
DEFAULT_TIMEOUT = 30.0
DEFAULT_JOB_TIMEOUT = 120.0
DEFAULT_POLL_INTERVAL = 2.0

_TERMINAL = ("completed", "failed", "deleted")


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}


def _retry_delay(attempt: int) -> float:
    """2s → 3s → 5s → 8s → 13s (Fibonacci) + 20% jitter."""
    a, b = 2.0, 3.0
    for _ in range(attempt):
        a, b = b, a + b
    return min(a, 30.0) * random.uniform(0.8, 1.2)


def _poll_delay(attempt: int) -> float:
    """Poll backoff for job.wait: 2s → 3s → 5s → 8s → 13s → cap 30s."""
    return min(_retry_delay(attempt), 30.0)


# ────────────────────────── Sync client ──────────────────────────
class VideoFetch:
    """Sync client. Usage:
        client = VideoFetch(api_key="vf_live_sk_...")
        job = client.downloads.create(url=..., format="1080p")
        result = job.wait(timeout=120)
    """

    downloads: "DownloadsResource"
    info: "InfoResource"

    def __init__(self, api_key: Optional[str] = None, *, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT, max_retries: int = DEFAULT_MAX_RETRIES,
                 http_client: Optional[httpx.Client] = None):
        self.api_key = api_key or os.getenv("VIDEOFETCH_API_KEY") or ""
        if not self.api_key:
            raise ValueError(
                "No API key provided. Pass api_key=... or set VIDEOFETCH_API_KEY."
            )
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._client = http_client or httpx.Client(
            base_url=self.base_url, headers=_headers(self.api_key),
            timeout=timeout, follow_redirects=True,
            # do not inherit system proxy env (can hijack localhost/dev traffic);
            # advanced users can pass their own http_client to override
            trust_env=False,
        )
        # lazy import avoids circular dependency (resources imports client)
        from .resources import DownloadsResource, InfoResource
        self.downloads = DownloadsResource(self)
        self.info = InfoResource(self)

    def request(self, method: str, path: str, *, json_body: Optional[dict] = None,
                params: Optional[dict] = None) -> Any:
        """Send request with automatic retry on 429/5xx. Returns parsed JSON."""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.request(method, path, json=json_body, params=params)
            except httpx.HTTPError as e:
                if attempt < self.max_retries:
                    time.sleep(_retry_delay(attempt))
                    continue
                raise VideoFetchError(f"Network error calling {path}: {e}", status_code=None) from e
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else _retry_delay(attempt)
                    time.sleep(min(delay, 30.0))
                    continue
            if resp.status_code >= 400:
                body = _parse_body(resp)
                raise map_error(resp.status_code, body)
            if resp.status_code == 204:
                return None
            return _parse_body(resp)
        raise VideoFetchError("request failed")  # pragma: no cover

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "VideoFetch":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ────────────────────────── Async client ─────────────────────────
class AsyncVideoFetch:
    """Async client for asyncio/Next.js backends. Same shape as VideoFetch, but
    every resource method is a coroutine (await client.downloads.create(...)).
    """

    downloads: "AsyncDownloadsResource"
    info: "AsyncInfoResource"

    def __init__(self, api_key: Optional[str] = None, *, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = DEFAULT_TIMEOUT, max_retries: int = DEFAULT_MAX_RETRIES,
                 http_client: Optional[httpx.AsyncClient] = None):
        self.api_key = api_key or os.getenv("VIDEOFETCH_API_KEY") or ""
        if not self.api_key:
            raise ValueError("No API key provided. Pass api_key=... or set VIDEOFETCH_API_KEY.")
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self._client = http_client or httpx.AsyncClient(
            base_url=self.base_url, headers=_headers(self.api_key),
            timeout=timeout, follow_redirects=True,
            trust_env=False,
        )
        from .resources import AsyncDownloadsResource, AsyncInfoResource
        self.downloads = AsyncDownloadsResource(self)
        self.info = AsyncInfoResource(self)

    async def request(self, method: str, path: str, *, json_body: Optional[dict] = None,
                      params: Optional[dict] = None) -> Any:
        import asyncio

        for attempt in range(self.max_retries + 1):
            try:
                resp = await self._client.request(method, path, json=json_body, params=params)
            except httpx.HTTPError as e:
                if attempt < self.max_retries:
                    await asyncio.sleep(_retry_delay(attempt))
                    continue
                raise VideoFetchError(f"Network error calling {path}: {e}", status_code=None) from e
            if resp.status_code in (429,) or resp.status_code >= 500:
                if attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else _retry_delay(attempt)
                    await asyncio.sleep(min(delay, 30.0))
                    continue
            if resp.status_code >= 400:
                body = _parse_body(resp)
                raise map_error(resp.status_code, body)
            if resp.status_code == 204:
                return None
            return _parse_body(resp)
        raise VideoFetchError("request failed")  # pragma: no cover

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncVideoFetch":
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


def _parse_body(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text
