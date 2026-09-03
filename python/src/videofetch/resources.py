"""Downloads resource: create / retrieve / list / cancel + Job.wait() polling.

Three-layer design (see docs/SDK_RELEASE_GUIDE.md):
  L1  job = client.downloads.create(...)          # POST only, returns immediately
  L2  result = job.wait(timeout=120)              # poll GET with backoff
  L3  result = client.downloads.create_and_wait(...)
"""

from __future__ import annotations

import time
from typing import Optional

from .client import DEFAULT_JOB_TIMEOUT, _poll_delay
from .errors import JobFailedError, VideoFetchError
from .models import Download, DownloadList, TrimSpec, VideoInfo

TERMINAL = ("completed", "failed", "deleted")


# ────────────────────────── Sync resources ───────────────────────
class DownloadsResource:
    def __init__(self, client):
        self._client = client

    def create(self, url: str, format: str = "720p", *,
               trim: Optional[TrimSpec] = None,
               destination: Optional[dict] = None,
               webhook_url: Optional[str] = None,
               **extra: dict) -> DownloadJob:
        """Create a download job. Returns immediately with status 'queued'."""
        body: dict = {"url": url, "format": format, **extra}
        t = trim.to_dict() if trim else None
        if t:
            body["trim"] = t
        if destination:
            body["destination"] = destination
        if webhook_url:
            body["webhook_url"] = webhook_url
        data = self._client.request("POST", "/v1/downloads", json_body=body)
        return DownloadJob(self._client, Download.from_dict(data))

    def retrieve(self, download_id: str) -> Download:
        data = self._client.request("GET", f"/v1/downloads/{download_id}")
        return Download.from_dict(data)

    def list(self, *, status: Optional[str] = None, q: Optional[str] = None,
             limit: int = 20, offset: int = 0) -> DownloadList:
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if q:
            params["q"] = q
        data = self._client.request("GET", "/v1/downloads", params=params)
        return DownloadList.from_dict(data)

    def cancel(self, download_id: str) -> None:
        """Cancel/delete a job (queued/processing). Safe to call on any state."""
        self._client.request("DELETE", f"/v1/downloads/{download_id}")

    def create_and_wait(self, url: str, format: str = "720p", *, timeout: float = DEFAULT_JOB_TIMEOUT,
                        **kwargs) -> Download:
        job = self.create(url, format, **kwargs)
        return job.wait(timeout=timeout)


class DownloadJob:
    """Polling handle around a queued/processing download (sync)."""

    def __init__(self, client, initial: Download):
        self._client = client
        self._download = initial

    @property
    def id(self) -> str:
        return self._download.id

    @property
    def status(self) -> str:
        return self._download.status

    @property
    def download(self) -> Download:
        return self._download

    def refresh(self) -> Download:
        self._download = self._client.downloads.retrieve(self.id)
        return self._download

    def wait(self, *, timeout: float = DEFAULT_JOB_TIMEOUT, poll_interval: float = None) -> Download:
        """Poll until terminal (completed/failed/deleted).

        - Network errors do not abort; we keep polling until timeout.
        - A failed job raises JobFailedError (failed downloads are never charged).
        - timeout=0 / None means wait forever (CLI use). Cancel only stops local
          waiting — the server-side job keeps running unless you call cancel().
        """
        deadline = None if (timeout is None or timeout <= 0) else time.monotonic() + timeout
        attempt = 0
        # If the create response already reached a terminal state, return immediately.
        if self._download.is_terminal:
            return self._raise_if_failed(self._download)
        interval = poll_interval or 2.0
        while True:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VideoFetchError(
                        f"Timed out after {timeout}s waiting for job {self.id}. "
                        "The job is still running server-side — retrieve() it later.",
                        code="job_timeout",
                    )
                time.sleep(min(interval, remaining))
            else:
                time.sleep(interval)
            try:
                self._download = self._client.downloads.retrieve(self.id)
            except VideoFetchError:
                if deadline is not None and time.monotonic() > deadline:
                    raise
                attempt += 1
                interval = _poll_delay(attempt)
                continue
            if self._download.is_terminal:
                return self._raise_if_failed(self._download)
            attempt += 1
            interval = _poll_delay(attempt)

    @staticmethod
    def _raise_if_failed(dl: Download) -> Download:
        if dl.status == "failed":
            raise JobFailedError(
                job_id=dl.id, error_code=dl.error_code, error_message=dl.error_message)
        return dl


class InfoResource:
    def __init__(self, client):
        self._client = client

    def lookup(self, url: str) -> VideoInfo:
        data = self._client.request("POST", "/v1/info", json_body={"url": url})
        return VideoInfo.from_dict(data)


# ────────────────────────── Async resources ──────────────────────
class AsyncDownloadsResource:
    def __init__(self, client):
        self._client = client

    async def create(self, url: str, format: str = "720p", *,
                     trim: Optional[TrimSpec] = None,
                     destination: Optional[dict] = None,
                     webhook_url: Optional[str] = None,
                     **extra: dict) -> AsyncDownloadJob:
        body: dict = {"url": url, "format": format, **extra}
        t = trim.to_dict() if trim else None
        if t:
            body["trim"] = t
        if destination:
            body["destination"] = destination
        if webhook_url:
            body["webhook_url"] = webhook_url
        data = await self._client.request("POST", "/v1/downloads", json_body=body)
        return AsyncDownloadJob(self._client, Download.from_dict(data))

    async def retrieve(self, download_id: str) -> Download:
        data = await self._client.request("GET", f"/v1/downloads/{download_id}")
        return Download.from_dict(data)

    async def list(self, *, status: Optional[str] = None, q: Optional[str] = None,
                   limit: int = 20, offset: int = 0) -> DownloadList:
        params = {"limit": limit, "offset": offset}
        if status:
            params["status"] = status
        if q:
            params["q"] = q
        data = await self._client.request("GET", "/v1/downloads", params=params)
        return DownloadList.from_dict(data)

    async def cancel(self, download_id: str) -> None:
        await self._client.request("DELETE", f"/v1/downloads/{download_id}")

    async def create_and_wait(self, url: str, format: str = "720p", *,
                              timeout: float = DEFAULT_JOB_TIMEOUT, **kwargs) -> Download:
        job = await self.create(url, format, **kwargs)
        return await job.wait(timeout=timeout)


class AsyncDownloadJob:
    """Polling handle around a queued/processing download (async)."""

    def __init__(self, client, initial: Download):
        self._client = client
        self._download = initial

    @property
    def id(self) -> str:
        return self._download.id

    @property
    def status(self) -> str:
        return self._download.status

    @property
    def download(self) -> Download:
        return self._download

    async def refresh(self) -> Download:
        self._download = await self._client.downloads.retrieve(self.id)
        return self._download

    async def wait(self, *, timeout: float = DEFAULT_JOB_TIMEOUT,
                   poll_interval: float = None) -> Download:
        import asyncio

        deadline = None if (timeout is None or timeout <= 0) else asyncio.get_event_loop().time() + timeout
        if self._download.is_terminal:
            return self._raise_if_failed(self._download)
        interval = poll_interval or 2.0
        attempt = 0
        while True:
            if deadline is not None:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    raise VideoFetchError(
                        f"Timed out after {timeout}s waiting for job {self.id}. "
                        "The job is still running server-side — retrieve() it later.",
                        code="job_timeout",
                    )
                await asyncio.sleep(min(interval, remaining))
            else:
                await asyncio.sleep(interval)
            try:
                self._download = await self._client.downloads.retrieve(self.id)
            except VideoFetchError:
                if deadline is not None and asyncio.get_event_loop().time() > deadline:
                    raise
                attempt += 1
                interval = _poll_delay(attempt)
                continue
            if self._download.is_terminal:
                return self._raise_if_failed(self._download)
            attempt += 1
            interval = _poll_delay(attempt)

    @staticmethod
    def _raise_if_failed(dl: Download) -> Download:
        if dl.status == "failed":
            raise JobFailedError(
                job_id=dl.id, error_code=dl.error_code, error_message=dl.error_message)
        return dl


class AsyncInfoResource:
    def __init__(self, client):
        self._client = client

    async def lookup(self, url: str) -> VideoInfo:
        data = await self._client.request("POST", "/v1/info", json_body={"url": url})
        return VideoInfo.from_dict(data)
