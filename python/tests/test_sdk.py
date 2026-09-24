"""SDK tests against a mocked httpx transport (no network)."""
import httpx
import pytest

import videofetch
from videofetch.errors import JobFailedError, QuotaExceededError, ValidationError
from videofetch.models import TrimSpec


def _client(handler) -> videofetch.VideoFetch:
    transport = httpx.MockTransport(handler)
    return videofetch.VideoFetch(
        api_key="vf_live_sk_test", base_url="http://mock",
        http_client=httpx.Client(base_url="http://mock", transport=transport),
    )


def _download_json(status="queued", **kw) -> dict:
    base = {
        "id": "dl_abc123", "status": status, "url": "https://www.youtube.com/watch?v=x",
        "format": "1080p", "progress": 0, "title": "T", "cost_usd": 0.0, "attempts": 0,
    }
    base.update(kw)
    return base


def test_create_returns_queued_job():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/downloads"
        import json as _json
        payload = _json.loads(req.read().decode())
        assert payload["format"] == "1080p"
        assert payload["trim"] == {"start": 10, "end": 20}
        return httpx.Response(202, json=_download_json("queued"))

    c = _client(handler)
    job = c.downloads.create(
        "https://www.youtube.com/watch?v=x", format="1080p",
        trim=TrimSpec(start=10, end=20),
    )
    assert isinstance(job, videofetch.DownloadJob)
    assert job.id == "dl_abc123"
    assert job.status == "queued"


def test_wait_polls_to_completed():
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(202, json=_download_json("queued"))
        # GET /v1/downloads/dl_abc123
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(200, json=_download_json("processing", progress=55))
        return httpx.Response(200, json=_download_json(
            "completed", progress=100, download_url="https://cdn.example/v.mp4",
            size_bytes=12345, cost_usd=0.0042, processing_time_ms=5000,
            strategy="direct", attempts=1))

    c = _client(handler)
    result = c.downloads.create_and_wait("https://www.youtube.com/watch?v=x",
                                         format="720p", timeout=10, )
    assert result.status == "completed"
    assert result.download_url.startswith("https://cdn.example/")
    assert result.size_bytes == 12345
    assert result.strategy == "direct"


def test_wait_raises_job_failed():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(202, json=_download_json("queued"))
        return httpx.Response(200, json=_download_json(
            "failed", error_code="download_failed",
            error_message="YouTube is blocking automated access from this network."))

    c = _client(handler)
    with pytest.raises(JobFailedError) as exc:
        c.downloads.create_and_wait("https://www.youtube.com/watch?v=x", timeout=10)
    assert exc.value.failed_not_charged is True
    assert exc.value.error_code == "download_failed"


def test_error_mapping():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads" and req.method == "POST":
            return httpx.Response(402, json={"detail": {
                "code": "quota_exceeded", "message": "Free tier exhausted (5 GB)",
                "remaining_gb": 0.0}})
        return httpx.Response(422, json={"detail": {
            "code": "invalid_format", "message": "format must be one of ...", "param": "format"}})

    c = _client(handler)
    with pytest.raises(QuotaExceededError):
        c.downloads.create("https://youtu.be/x", format="8k")
    with pytest.raises(ValidationError):
        c.downloads.retrieve("dl_missing")


def test_info_lookup():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/info"
        return httpx.Response(200, json={
            "id": "abc", "url": "https://youtu.be/x", "title": "Hello",
            "duration": 120.0, "formats": [{"quality": "720p", "size": 1000}],
        })

    c = _client(handler)
    info = c.info.lookup("https://youtu.be/x")
    assert info.title == "Hello"
    assert info.formats[0].quality == "720p"


def test_queued_download_exposes_queue_hints():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            return httpx.Response(202, json=_download_json(
                "queued", queue_position=1, ahead_of_you=0, estimated_wait_seconds=42))
        return httpx.Response(200, json=_download_json(
            "queued", queue_position=2, ahead_of_you=1, estimated_wait_seconds=90))

    c = _client(handler)
    job = c.downloads.create("https://www.youtube.com/watch?v=x")
    assert job.download.queue_position == 1
    assert job.download.ahead_of_you == 0
    assert job.download.estimated_wait_seconds == 42

    detail = c.downloads.retrieve(job.id)
    assert detail.queue_position == 2 and detail.ahead_of_you == 1
    assert detail.estimated_wait_seconds == 90


def test_queue_hints_are_none_when_not_queued():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_download_json(
            "processing", progress=50, queue_position=None, ahead_of_you=None,
            estimated_wait_seconds=None))

    c = _client(handler)
    detail = c.downloads.retrieve("dl_abc123")
    assert detail.queue_position is None
    assert detail.ahead_of_you is None
    assert detail.estimated_wait_seconds is None


# ── destination ────────────────────────────────────────────────────────────────────────────
# The API resolves a saved connection from its id alone (the provider, bucket and credentials
# live on the connection), so the SDK must forward the dict untouched and never inject a
# default of its own. A fabricated "type" would either be ignored or, for an empty value,
# rejected as an unknown enum member.

def _capture_body(**create_kwargs) -> dict:
    seen: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        import json as _json
        seen.update(_json.loads(req.read().decode()))
        return httpx.Response(202, json=_download_json("queued"))

    c = _client(handler)
    c.downloads.create("https://www.youtube.com/watch?v=x", **create_kwargs)
    return seen


def test_destination_saved_connection_is_sent_as_bare_id():
    body = _capture_body(destination={"id": "conn_9f1c2a34"})
    assert body["destination"] == {"id": "conn_9f1c2a34"}


def test_destination_keeps_provider_when_given():
    body = _capture_body(destination={"type": "s3", "id": "conn_9f1c2a34"})
    assert body["destination"] == {"type": "s3", "id": "conn_9f1c2a34"}


def test_destination_inline_credentials_pass_through():
    inline = {"type": "s3", "bucket": "b", "access_key_id": "k", "secret_access_key": "s"}
    body = _capture_body(destination=inline)
    assert body["destination"] == inline


def test_destination_omitted_is_not_sent():
    body = _capture_body(format="720p")
    assert "destination" not in body
