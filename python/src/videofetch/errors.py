"""Type hierarchy for VideoFetch SDK errors.

Mirrors the server error contract:
  HTTP 4xx/5xx → {"detail": {"code": ..., "message": ..., "param": ...}}
Terminal job failure → DownloadOut {status: "failed", error_code, error_message}
"""


class VideoFetchError(Exception):
    """Base class for all SDK errors."""

    def __init__(self, message: str, *, code: str | None = None,
                 status_code: int | None = None, param: str | None = None,
                 response_body: object | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.param = param
        self.response_body = response_body


class AuthenticationError(VideoFetchError):
    """Invalid/expired API key or JWT (401)."""


class PermissionDeniedError(VideoFetchError):
    """Authenticated but not allowed (403)."""


class QuotaExceededError(VideoFetchError):
    """Monthly quota exhausted (402)."""


class ValidationError(VideoFetchError):
    """Request rejected (400/422): bad url/format/trim/destination/webhook."""


class NotFoundError(VideoFetchError):
    """Resource does not exist or does not belong to this key (404)."""


class RateLimitError(VideoFetchError):
    """Too many requests (429). Respect Retry-After when present."""


class ApiError(VideoFetchError):
    """Server-side failure (5xx) or unknown non-2xx."""


class JobFailedError(VideoFetchError):
    """The download job reached a terminal failed state.

    A failed download is never charged — see job.failed_not_charged.
    """

    def __init__(self, *, job_id: str, error_code: str | None, error_message: str | None):
        super().__init__(
            f"Download job {job_id} failed"
            + (f" [{error_code}]: {error_message}" if error_code or error_message else ""),
            code=error_code or "job_failed",
        )
        self.job_id = job_id
        self.error_code = error_code
        self.error_message = error_message
        self.failed_not_charged = True


def map_error(status_code: int, body: object, *, message: str | None = None) -> VideoFetchError:
    """Translate an HTTP response into the right SDK error."""
    detail = None
    if isinstance(body, dict):
        detail = body.get("detail")
    if isinstance(detail, dict):
        code = detail.get("code") or detail.get("type")
        msg = detail.get("message") or detail.get("msg") or message or "Request failed"
        param = detail.get("param")
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
        return QuotaExceededError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code in (400, 422):
        return ValidationError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code == 404:
        return NotFoundError(msg, code=code, status_code=status_code, param=param, response_body=body)
    if status_code == 429:
        return RateLimitError(msg, code=code, status_code=status_code, param=param, response_body=body)
    return ApiError(msg, code=code, status_code=status_code, param=param, response_body=body)
