"""Type hierarchy for VideoFetch SDK errors.

Mirrors the server error contract:
  HTTP 4xx/5xx → {"detail": {"code": ..., "message": ..., "param": ...}}
Terminal job failure → DownloadOut {status: "failed", error_code, error_message}

v0.2.0 error semantics:
  429  RateLimitError        — code ∈ {concurrency_limit_exceeded, queue_limit_exceeded,
                               platform_at_capacity}; carries limit/active/scope and
                               retry_after (parsed from the Retry-After response header).
  403  PermissionDeniedError — code=account_suspended when the account was disabled.
  402  QuotaExceededError    — carries remaining_gb.
  400  ValidationError       — code ∈ {invalid_format, invalid_trim, invalid_url, invalid_webhook};
                               carries param.

v0.3.0 error semantics:
  download_to() local-save preconditions:
    DownloadNotCompletedError — status is not "completed" yet (code=job_not_completed).
    DownloadURLUnavailableError — completed but no download_url (code=download_url_unavailable).
"""

from __future__ import annotations

from typing import Optional


class VideoFetchError(Exception):
    """Base class for all SDK errors."""

    def __init__(self, message: str, *, code: Optional[str] = None,
                 status_code: Optional[int] = None, param: Optional[str] = None,
                 response_body: object = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.param = param
        self.response_body = response_body


class AuthenticationError(VideoFetchError):
    """Invalid/expired API key or JWT (401)."""


class PermissionDeniedError(VideoFetchError):
    """Authenticated but not allowed (403).

    The most common cause is `code == "account_suspended"` — the account was
    disabled by an administrator. Check ``exc.code`` for the precise reason.
    """


class QuotaExceededError(VideoFetchError):
    """Monthly quota exhausted (402).

    `remaining_gb` is the account's remaining quota (usually 0.0) when the
    server provides it.
    """

    def __init__(self, message: str, *, code: Optional[str] = None,
                 status_code: Optional[int] = None, param: Optional[str] = None,
                 response_body: object = None, remaining_gb: Optional[float] = None):
        super().__init__(message, code=code, status_code=status_code, param=param,
                         response_body=response_body)
        self.remaining_gb = remaining_gb


class ValidationError(VideoFetchError):
    """Request rejected (400/422): bad url/format/trim/destination/webhook.

    `param` names the offending request field when the server provides it.
    """


class NotFoundError(VideoFetchError):
    """Resource does not exist or does not belong to this key (404)."""


class RateLimitError(VideoFetchError):
    """Request throttled (429).

    Attributes:
        code:        concurrency_limit_exceeded | queue_limit_exceeded | platform_at_capacity
        limit:       the configured limit that was hit
        active:      how many jobs were in-flight at rejection time
        scope:       "account" (default) or "platform"
        retry_after: seconds to wait, parsed from the Retry-After response header
                     (None when the header is absent / non-numeric)
    """

    def __init__(self, message: str, *, code: Optional[str] = None,
                 status_code: Optional[int] = None, param: Optional[str] = None,
                 response_body: object = None, limit: Optional[int] = None,
                 active: Optional[int] = None, scope: Optional[str] = None,
                 retry_after: Optional[float] = None):
        super().__init__(message, code=code, status_code=status_code, param=param,
                         response_body=response_body)
        self.limit = limit
        self.active = active
        self.scope = scope
        self.retry_after = retry_after


class ApiError(VideoFetchError):
    """Server-side failure (5xx) or unknown non-2xx."""


class JobFailedError(VideoFetchError):
    """The download job reached a terminal failed state.

    A failed download is never charged — see job.failed_not_charged.
    """

    def __init__(self, *, job_id: str, error_code: Optional[str], error_message: Optional[str]):
        super().__init__(
            f"Download job {job_id} failed"
            + (f" [{error_code}]: {error_message}" if error_code or error_message else ""),
            code=error_code or "job_failed",
        )
        self.job_id = job_id
        self.error_code = error_code
        self.error_message = error_message
        self.failed_not_charged = True


class DownloadNotCompletedError(VideoFetchError):
    """The job has not reached `completed`, so there is no artifact to save yet.

    Wait for the terminal state first (``job.wait()`` or the ``download.completed``
    webhook) and call ``download_to()`` afterwards.
    """

    def __init__(self, *, job_id: str, status: str):
        super().__init__(
            f"Download job {job_id} is not ready to save: status is {status!r} "
            "(expected 'completed'). Wait for the job to finish before downloading it.",
            code="job_not_completed",
        )
        self.job_id = job_id
        self.status = status


class DownloadURLUnavailableError(VideoFetchError):
    """The completed job exposes no downloadable link.

    This happens when the file was delivered straight to your own bucket
    (``destination_type`` other than ``url``) — read it from your storage instead.
    """

    def __init__(self, *, job_id: str):
        super().__init__(
            f"Download job {job_id} completed but has no download_url "
            "(it was delivered to your own storage destination).",
            code="download_url_unavailable",
        )
        self.job_id = job_id


def _parse_retry_after(headers) -> Optional[float]:
    """Retry-After is either delta-seconds or an HTTP date; SDK handles seconds."""
    if not headers:
        return None
    raw = None
    try:
        raw = headers.get("Retry-After")
    except Exception:
        raw = None
    if raw is None:
        return None
    raw = str(raw).strip()
    try:
        return float(raw)
    except ValueError:
        return None


def map_error(status_code: int, body: object, *, message: Optional[str] = None,
              headers=None) -> VideoFetchError:
    """Translate an HTTP response into the right SDK error."""
    detail = None
    if isinstance(body, dict):
        detail = body.get("detail")
    extra: dict = {}
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("type")
        msg = detail.get("message") or detail.get("msg") or message or "Request failed"
        param = detail.get("param")
        extra = detail
    elif isinstance(detail, str):
        code = None
        msg = detail
        param = None
    else:
        code = None
        msg = message or "Request failed"
        param = None

    if status_code == 401:
        return AuthenticationError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code == 403:
        return PermissionDeniedError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code == 402:
        return QuotaExceededError(
            msg, code=code, status_code=status_code, param=param, response_body=body,
            remaining_gb=_as_float(extra.get("remaining_gb")))
    if status_code in (400, 422):
        return ValidationError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code == 404:
        return NotFoundError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code == 429:
        return RateLimitError(
            msg, code=code, status_code=status_code, param=param, response_body=body,
            limit=_as_int(extra.get("limit")), active=_as_int(extra.get("active")),
            scope=extra.get("scope"), retry_after=_parse_retry_after(headers))
    return ApiError(msg, code=code, status_code=status_code, param=param, response_body=body)


def _as_int(v) -> Optional[int]:
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _as_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
