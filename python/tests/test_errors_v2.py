"""v0.2.0 error semantics: 429 rate-limit, 403 suspension, 402 quota, 400 validation."""
import httpx
import pytest

import videofetch
from videofetch.errors import (
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ValidationError,
)


def _client(handler, max_retries: int = 0) -> videofetch.VideoFetch:
    """max_retries=0 so 429 is surfaced immediately (no retry sleeps in tests)."""
    transport = httpx.MockTransport(handler)
    return videofetch.VideoFetch(
        api_key="vf_live_sk_test", base_url="http://mock", max_retries=max_retries,
        http_client=httpx.Client(base_url="http://mock", transport=transport),
    )


DL = {"id": "dl_x", "status": "queued", "url": "https://youtu.be/x", "format": "720p"}


def test_429_concurrency_limit_maps_fields_and_retry_after():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"detail": {"code": "concurrency_limit_exceeded",
                             "message": "Too many in-flight jobs: 5/5 (queued+processing).",
                             "param": "url", "limit": 5, "active": 5, "scope": "account"}},
            headers={"Retry-After": "10", "X-Concurrency-Limit": "5",
                     "X-Concurrency-Active": "5"},
        )

    c = _client(handler)
    with pytest.raises(RateLimitError) as exc:
        c.downloads.create("https://youtu.be/x")
    e = exc.value
    assert e.status_code == 429
    assert e.code == "concurrency_limit_exceeded"
    assert e.limit == 5 and e.active == 5 and e.scope == "account"
    assert e.retry_after == 10.0
    assert e.param == "url"


def test_429_without_retry_after_header():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": {
            "code": "queue_limit_exceeded", "message": "queue full",
            "limit": 50, "active": 50, "scope": "account"}})

    c = _client(handler)
    with pytest.raises(RateLimitError) as exc:
        c.downloads.create("https://youtu.be/x")
    assert exc.value.code == "queue_limit_exceeded"
    assert exc.value.retry_after is None


def test_429_platform_at_capacity_scope():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"detail": {
            "code": "platform_at_capacity", "message": "Platform is at capacity.",
            "limit": 100, "active": 100, "scope": "platform"}},
            headers={"Retry-After": "10"})

    c = _client(handler)
    with pytest.raises(RateLimitError) as exc:
        c.downloads.create("https://youtu.be/x")
    assert exc.value.code == "platform_at_capacity"
    assert exc.value.scope == "platform"
    assert exc.value.retry_after == 10.0


def test_429_is_retried_then_succeeds():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(429, json={"detail": {"code": "concurrency_limit_exceeded",
                                                        "message": "slow down"}},
                                  headers={"Retry-After": "0"})
        return httpx.Response(202, json=DL)

    c = _client(handler, max_retries=1)
    job = c.downloads.create("https://youtu.be/x")
    assert job.id == "dl_x" and calls["n"] == 2


def test_403_account_suspended_is_permission_denied():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": {
            "code": "account_suspended",
            "message": "This account is suspended. Unpaid invoice.",
            "disabled_at": "2026-09-01T00:00:00"}})

    c = _client(handler)
    with pytest.raises(PermissionDeniedError) as exc:
        c.downloads.create("https://youtu.be/x")
    assert exc.value.status_code == 403
    assert exc.value.code == "account_suspended"
    assert "suspended" in exc.value.message


def test_402_quota_exceeded_carries_remaining_gb():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"detail": {
            "code": "quota_exceeded", "message": "Free tier exhausted (1 GB)",
            "remaining_gb": 0.0}})

    c = _client(handler)
    with pytest.raises(QuotaExceededError) as exc:
        c.downloads.create("https://youtu.be/x")
    assert exc.value.code == "quota_exceeded"
    assert exc.value.remaining_gb == 0.0


@pytest.mark.parametrize("code,param", [
    ("invalid_format", "format"),
    ("invalid_trim", "trim"),
    ("invalid_url", "url"),
    ("invalid_webhook", "webhook_url"),
])
def test_400_validation_codes_carry_param(code, param):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": {
            "code": code, "message": f"bad {param}", "param": param}})

    c = _client(handler)
    with pytest.raises(ValidationError) as exc:
        c.downloads.create("https://youtu.be/x")
    assert exc.value.code == code
    assert exc.value.param == param
    assert exc.value.status_code == 400


def test_permission_denied_exported_and_subclass():
    assert "PermissionDeniedError" in videofetch.__all__
    assert videofetch.PermissionDeniedError is PermissionDeniedError
    assert issubclass(PermissionDeniedError, videofetch.VideoFetchError)


def test_version_bumped_to_0_2_0():
    assert videofetch.__version__ == "0.2.0"
