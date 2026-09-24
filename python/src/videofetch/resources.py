"""Downloads resource: create / retrieve / list / cancel + Job.wait() polling.

Three-layer design (see docs/SDK_RELEASE_GUIDE.md):
  L1  job = client.downloads.create(...)          # POST only, returns immediately
  L2  result = job.wait(timeout=120)              # poll GET with backoff
  L3  result = client.downloads.create_and_wait(...)
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional, Union

import httpx

from .client import DEFAULT_JOB_TIMEOUT, _poll_delay
from .errors import (
    DownloadNotCompletedError,
    DownloadURLUnavailableError,
    JobFailedError,
    VideoFetchError,
    map_error,
)
from .models import (
    Download,
    DownloadList,
    ReplayResult,
    TrimSpec,
    Usage,
    UsageAlerts,
    VideoInfo,
    WebhookDeliveriesResult,
    WebhookEndpoint,
    WebhookList,
    WebhookTestResult,
)

TERMINAL = ("completed", "failed", "deleted")

PathLike = Union[str, os.PathLike]
_DOWNLOAD_CHUNK_SIZE = 64 * 1024
_MAX_FILENAME_LEN = 80
# Path separators, control characters and characters no sane filesystem wants.
_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def _safe_filename(value: Optional[str], fallback: str) -> str:
    """Turn arbitrary text into a single, filesystem-safe path component.

    Drops path separators, control characters and unsafe punctuation, trims
    surrounding whitespace and dots, then caps the length. Empty results fall
    back to `fallback` (the job id).
    """
    cleaned = _UNSAFE_FILENAME_CHARS.sub("", value or "").strip().strip(".").strip()
    if not cleaned:
        cleaned = fallback
    return cleaned[:_MAX_FILENAME_LEN] or fallback[:_MAX_FILENAME_LEN]


def _default_filename(download: Download) -> str:
    """`<sanitized title or job id>.<mp3|mp4>` for this job."""
    stem = _safe_filename(download.title, download.id)
    ext = ".mp3" if (download.format or "").lower() == "mp3" else ".mp4"
    return f"{stem}{ext}"


def _resolve_target_path(download: Download, path: Optional[PathLike]) -> str:
    """Resolve the caller's `path` into the file we will write.

    `None` → the default name in the current directory. A path that is an
    existing directory, or ends with a separator, gets the default name appended.
    """
    name = _default_filename(download)
    if path is None:
        return os.path.join(os.getcwd(), name)
    raw = os.fspath(path)
    if raw.endswith((os.sep, "/", "\\")) or (raw and os.path.isdir(raw)):
        return os.path.join(raw, name)
    return raw


def _ensure_downloadable(download: Download) -> str:
    """Validate the job is ready and return its download_url."""
    if download.status == "failed":
        raise JobFailedError(
            job_id=download.id, error_code=download.error_code,
            error_message=download.error_message)
    if download.status != "completed":
        raise DownloadNotCompletedError(job_id=download.id, status=download.status)
    if not download.download_url:
        raise DownloadURLUnavailableError(job_id=download.id)
    return download.download_url


async def _aread_body(resp: httpx.Response) -> object:
    """Read a streaming error response into a JSON/text body for error mapping."""
    await resp.aread()
    try:
        return resp.json()
    except Exception:
        return resp.text


def _read_body(resp: httpx.Response) -> object:
    """Sync twin of :func:`_aread_body`."""
    try:
        return resp.json()
    except Exception:
        return resp.text


def _build_trim(trim: Optional[TrimSpec], trim_start: Optional[float],
                trim_end: Optional[float]) -> Optional[dict]:
    """Normalize `trim{start,end}` and the flat `trim_start`/`trim_end` aliases.

    Both spellings are accepted but must not conflict: passing a TrimSpec plus a
    flat value that disagrees raises ValueError (we never silently pick one).
    """
    if trim is not None and (trim_start is not None or trim_end is not None):
        same = ((trim_start is None or trim_start == trim.start)
                and (trim_end is None or trim_end == trim.end))
        if not same:
            raise ValueError(
                "use either trim{start,end} or trim_start/trim_end, not conflicting values")
        return trim.to_dict()
    if trim_start is not None or trim_end is not None:
        if trim_start is None or trim_end is None:
            raise ValueError("trim_start and trim_end must be provided together")
        return {"start": trim_start, "end": trim_end}
    return trim.to_dict() if trim else None


# ────────────────────────── Sync resources ───────────────────────
class DownloadsResource:
    def __init__(self, client):
        self._client = client

    def create(self, url: str, format: str = "720p", *,
               trim: Optional[TrimSpec] = None,
               trim_start: Optional[float] = None,
               trim_end: Optional[float] = None,
               destination: Optional[dict] = None,
               webhook_url: Optional[str] = None,
               **extra: dict) -> DownloadJob:
        """Create a download job. Returns immediately with status 'queued'.

        Clip window may be given either as ``trim=TrimSpec(start, end)`` or via
        the flat aliases ``trim_start`` / ``trim_end``. The two spellings are
        mutually exclusive in value — a conflict raises ValueError.

        ``destination`` decides where the finished file lands:

        * ``{"id": "..."}`` — a saved storage connection. The provider is read from
          the connection, so you do not need to know it (``type`` is optional here
          and ignored when the id is given).
        * ``{"type": "s3"|"r2"|"gcs"|"s3_compatible", "bucket": ..., "access_key_id":
          ..., "secret_access_key": ...}`` — inline credentials, stored as a
          connection for your account. ``type`` is required in this form.
        * omitted, or ``{"type": "url"}`` — the platform keeps the file and returns a
          presigned ``download_url`` (7 days).
        """
        body: dict = {"url": url, "format": format, **extra}
        t = _build_trim(trim, trim_start, trim_end)
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

    def download_to(self, download_id: str, path: Optional[PathLike] = None) -> str:
        """Stream a completed job's artifact to a local file; return its absolute path.

        When the job was created with no destination configured the platform
        issues a time-limited, self-authorizing ``download_url`` and this method
        saves it locally, in chunks (the file is never held in memory). The API
        key is deliberately NOT sent to that link; if it has expired the server
        re-signs it on the next ``GET /v1/downloads/{id}``, which we do once when
        the link answers 403.

        `path` may be a file path, or an existing/last-component directory
        (a path ending in a separator) in which case the default name is used:
        ``<sanitized title or job id>.<mp3|mp4>`` in the current directory.
        """
        download = self.retrieve(download_id)
        url = _ensure_downloadable(download)
        target = _resolve_target_path(download, path)

        resp = self._client.open_stream(url)
        if resp.status_code == 403:
            # Link expired: re-fetch the job so the server re-signs it, retry once.
            resp.close()
            download = self.retrieve(download_id)
            url = _ensure_downloadable(download)
            resp = self._client.open_stream(url)

        try:
            if resp.status_code >= 400:
                raise map_error(resp.status_code, _read_body(resp))
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(target, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                    fh.write(chunk)
        finally:
            resp.close()
        return os.path.abspath(target)

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
                     trim_start: Optional[float] = None,
                     trim_end: Optional[float] = None,
                     destination: Optional[dict] = None,
                     webhook_url: Optional[str] = None,
                     **extra: dict) -> AsyncDownloadJob:
        body: dict = {"url": url, "format": format, **extra}
        t = _build_trim(trim, trim_start, trim_end)
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

    async def download_to(self, download_id: str, path: Optional[PathLike] = None) -> str:
        """Async twin of :meth:`DownloadsResource.download_to` — streams to disk.

        No API key is sent to the self-authorizing link; a 403 triggers one
        re-fetch of the job (the server re-signs the URL) and a single retry.
        """
        download = await self.retrieve(download_id)
        url = _ensure_downloadable(download)
        target = _resolve_target_path(download, path)

        resp = await self._client.open_stream(url)
        if resp.status_code == 403:
            await resp.aclose()
            download = await self.retrieve(download_id)
            url = _ensure_downloadable(download)
            resp = await self._client.open_stream(url)

        try:
            if resp.status_code >= 400:
                raise map_error(resp.status_code, await _aread_body(resp))
            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            # Local file writes are small and sequential; keep the copy simple.
            with open(target, "wb") as fh:
                async for chunk in resp.aiter_bytes(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                    fh.write(chunk)
        finally:
            await resp.aclose()
        return os.path.abspath(target)

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


# ────────────────────────── Usage resource (v0.2.0) ──────────────────────────
class UsageResource:
    """Account quota, alert state and concurrency snapshot (GET /v1/usage)."""

    def __init__(self, client):
        self._client = client

    def get(self) -> Usage:
        """Current usage/quota snapshot, including alert_level + concurrency_limit."""
        return Usage.from_dict(self._client.request("GET", "/v1/usage"))

    def alerts(self) -> UsageAlerts:
        """Real-time alert state + this month's fired alerts + thresholds/topup amounts."""
        return UsageAlerts.from_dict(self._client.request("GET", "/v1/usage/alerts"))


class AsyncUsageResource:
    def __init__(self, client):
        self._client = client

    async def get(self) -> Usage:
        return Usage.from_dict(await self._client.request("GET", "/v1/usage"))

    async def alerts(self) -> UsageAlerts:
        return UsageAlerts.from_dict(await self._client.request("GET", "/v1/usage/alerts"))


# ────────────────────────── Webhooks resource (v0.2.0) ───────────────────────
class WebhooksResource:
    """Account-level webhook endpoints (API key or JWT); requires httpx only.

    create() is the only call that returns the FULL plaintext signing secret.
    """

    def __init__(self, client):
        self._client = client

    def create(self, url: str, events: Optional[list] = None) -> WebhookEndpoint:
        """Register an endpoint. Omit `events` to subscribe to all events.

        The returned `secret` is the full plaintext signing secret and is shown
        only once — persist it to verify deliveries.
        """
        body: dict = {"url": url}
        if events is not None:
            body["events"] = list(events)
        data = self._client.request("POST", "/v1/webhooks", json_body=body)
        return WebhookEndpoint.from_dict(data)

    def list(self) -> WebhookList:
        """List endpoints (secrets are masked)."""
        return WebhookList.from_dict(self._client.request("GET", "/v1/webhooks"))

    def delete(self, webhook_id: str) -> None:
        """Delete an endpoint (204 No Content)."""
        self._client.request("DELETE", f"/v1/webhooks/{webhook_id}")

    def test(self, webhook_id: str) -> WebhookTestResult:
        """Send a one-shot `webhook.test` ping to the endpoint and report the result."""
        data = self._client.request("POST", f"/v1/webhooks/{webhook_id}/test")
        return WebhookTestResult.from_dict(data)

    def deliveries(self, endpoint_id: str, limit: int = 50) -> WebhookDeliveriesResult:
        """Recent deliveries for an endpoint plus aggregate health.

        Deliveries are at-least-once and not ordered — dedupe by `event_id`
        (the `X-VideoFetch-Delivery` header) and sort by `seq`.
        """
        data = self._client.request(
            "GET", f"/v1/webhooks/{endpoint_id}/deliveries", params={"limit": limit})
        return WebhookDeliveriesResult.from_dict(data)

    def replay(self, event_id: str) -> ReplayResult:
        """Queue a fresh delivery of a past event (identified by its event_id).

        Raises NotFoundError when the delivery is not visible to this account.
        """
        data = self._client.request(
            "POST", f"/v1/webhooks/deliveries/{event_id}/replay")
        return ReplayResult.from_dict(data)


class AsyncWebhooksResource:
    def __init__(self, client):
        self._client = client

    async def create(self, url: str, events: Optional[list] = None) -> WebhookEndpoint:
        body: dict = {"url": url}
        if events is not None:
            body["events"] = list(events)
        data = await self._client.request("POST", "/v1/webhooks", json_body=body)
        return WebhookEndpoint.from_dict(data)

    async def list(self) -> WebhookList:
        return WebhookList.from_dict(await self._client.request("GET", "/v1/webhooks"))

    async def delete(self, webhook_id: str) -> None:
        await self._client.request("DELETE", f"/v1/webhooks/{webhook_id}")

    async def test(self, webhook_id: str) -> WebhookTestResult:
        data = await self._client.request("POST", f"/v1/webhooks/{webhook_id}/test")
        return WebhookTestResult.from_dict(data)

    async def deliveries(self, endpoint_id: str, limit: int = 50) -> WebhookDeliveriesResult:
        data = await self._client.request(
            "GET", f"/v1/webhooks/{endpoint_id}/deliveries", params={"limit": limit})
        return WebhookDeliveriesResult.from_dict(data)

    async def replay(self, event_id: str) -> ReplayResult:
        data = await self._client.request(
            "POST", f"/v1/webhooks/deliveries/{event_id}/replay")
        return ReplayResult.from_dict(data)
