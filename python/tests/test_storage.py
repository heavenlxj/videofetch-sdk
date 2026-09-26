"""Storage connections, destination shorthands, delivery/error objects and redeliver (v0.5.0)."""
import asyncio
import json

import httpx
import pytest

import videofetch
from videofetch import (
    ConflictError,
    DeliveryFailedError,
    JobFailedError,
    StorageError,
    ValidationError,
)
from videofetch.webhooks import WEBHOOK_EVENTS

CONN = {
    "id": "st_9f1c2a34b5d6e7f8", "name": "Prod bucket", "provider": "s3", "bucket": "acme-media",
    "path_prefix": "youtube/{video_id}/", "region": "us-east-1", "access_key_masked": "AKIA••••MPLE",
    "is_default": True, "status": "failing", "deliveries_count": 12,
    "last_error": {"code": "storage_permission_denied", "message": "denied", "at": "2026-09-26T10:00:00Z"},
    "last_used_at": "2026-09-26T09:59:00Z", "created_at": "2026-09-01T00:00:00Z",
}


def _client(handler) -> videofetch.VideoFetch:
    return videofetch.VideoFetch(
        api_key="vf_live_sk_test", base_url="http://mock", max_retries=0,
        http_client=httpx.Client(base_url="http://mock", transport=httpx.MockTransport(handler)),
    )


def _dl(status="queued", **kw) -> dict:
    base = {"id": "dl_abc123", "status": status, "url": "https://youtu.be/x", "format": "720p",
            "progress": 0, "cost_usd": 0.0, "attempts": 0}
    base.update(kw)
    return base


def _body(req: httpx.Request):
    raw = req.read().decode()
    return json.loads(raw) if raw else None


# ── destination forms ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("dest", ["st_9f1c2a34b5d6e7f8", "url",
                                  {"id": "st_9f1c2a34b5d6e7f8", "key": "clips/{video_id}.{ext}"},
                                  {"type": "r2", "bucket": "b", "endpoint": "https://a.r2.cloudflarestorage.com",
                                   "access_key_id": "k", "secret_access_key": "s", "save": True, "name": "R2"}])
def test_destination_forms_are_forwarded(dest):
    seen = {}

    def handler(req):
        seen.update(_body(req))
        return httpx.Response(202, json=_dl())

    _client(handler).downloads.create("https://youtu.be/x", destination=dest)
    assert seen["destination"] == dest


def test_destination_rejects_bad_types():
    c = _client(lambda req: httpx.Response(202, json=_dl()))
    with pytest.raises(TypeError):
        c.downloads.create("https://youtu.be/x", destination=123)
    with pytest.raises(ValueError):
        c.downloads.create("https://youtu.be/x", destination="   ")


# ── sync errors ────────────────────────────────────────────────────────────────────────────

def test_storage_422_maps_to_storage_error_with_hint_and_param():
    def handler(req):
        return httpx.Response(422, json={"detail": {
            "code": "storage_not_found", "message": "No storage connection st_nope",
            "hint": "List connections with GET /v1/storage", "param": "destination.id"}})

    with pytest.raises(StorageError) as exc:
        _client(handler).downloads.create("https://youtu.be/x", destination="st_nope")
    e = exc.value
    assert isinstance(e, ValidationError)
    assert e.code == "storage_not_found" and e.param == "destination.id"
    assert e.hint.startswith("List connections")


def test_plain_422_stays_validation_error():
    def handler(req):
        return httpx.Response(422, json={"detail": {"code": "invalid_format", "message": "bad"}})

    with pytest.raises(ValidationError) as exc:
        _client(handler).downloads.create("https://youtu.be/x")
    assert not isinstance(exc.value, StorageError)


# ── delivery / error objects ───────────────────────────────────────────────────────────────

def test_completed_download_exposes_delivery():
    def handler(req):
        return httpx.Response(200, json=_dl(
            "completed", destination_type="s3", destination_id="st_9f1c2a34b5d6e7f8",
            delivery={"type": "storage", "status": "delivered", "destination_id": "st_9f1c2a34b5d6e7f8",
                      "provider": "s3", "bucket": "acme-media", "key": "youtube/x/video.mp4",
                      "uri": "s3://acme-media/youtube/x/video.mp4", "etag": "abc", "size_bytes": 10,
                      "attempts": 1, "delivered_at": "2026-09-26T10:00:00Z"}))

    d = _client(handler).downloads.retrieve("dl_abc123")
    assert d.destination_id == "st_9f1c2a34b5d6e7f8"
    assert d.delivery.type == "storage" and d.delivery.status == "delivered"
    assert d.delivery.uri == "s3://acme-media/youtube/x/video.mp4"
    assert d.delivery.size_bytes == 10 and d.error is None


def test_delivery_failure_raises_delivery_failed_error():
    failed = _dl("failed", error_code="storage_permission_denied", error_message="denied",
                 error={"code": "storage_permission_denied", "message": "denied", "stage": "delivery",
                        "retryable": False, "provider_code": "AccessDenied", "hint": "Grant s3:PutObject"},
                 delivery={"type": "storage", "status": "failed", "redeliverable": True,
                           "hold_expires_at": "2026-09-27T10:00:00Z"})

    def handler(req):
        return httpx.Response(202 if req.method == "POST" else 200,
                              json=_dl() if req.method == "POST" else failed)

    with pytest.raises(DeliveryFailedError) as exc:
        _client(handler).downloads.create_and_wait("https://youtu.be/x", timeout=10)
    e = exc.value
    assert isinstance(e, JobFailedError)
    assert e.stage == "delivery" and e.retryable is False
    assert e.provider_code == "AccessDenied" and e.hint == "Grant s3:PutObject"
    assert e.redeliverable is True and e.hold_expires_at == "2026-09-27T10:00:00Z"
    assert e.download.error.code == "storage_permission_denied"


def test_fetch_failure_stays_plain_job_failed_error():
    failed = _dl("failed", error_code="download_failed", error_message="blocked",
                 error={"code": "download_failed", "stage": "fetch", "retryable": True})

    def handler(req):
        return httpx.Response(202 if req.method == "POST" else 200,
                              json=_dl() if req.method == "POST" else failed)

    with pytest.raises(JobFailedError) as exc:
        _client(handler).downloads.create_and_wait("https://youtu.be/x", timeout=10)
    assert not isinstance(exc.value, DeliveryFailedError)
    assert exc.value.stage == "fetch" and exc.value.retryable is True


def test_legacy_failure_without_error_object():
    failed = _dl("failed", error_code="download_failed", error_message="x")
    with pytest.raises(JobFailedError) as exc:
        videofetch.resources.DownloadJob._raise_if_failed(videofetch.Download.from_dict(failed))
    assert exc.value.stage is None and exc.value.download is not None


# ── redeliver ──────────────────────────────────────────────────────────────────────────────

def test_redeliver_without_destination_sends_empty_body():
    seen = {}

    def handler(req):
        seen["path"], seen["body"] = req.url.path, _body(req)
        return httpx.Response(202, json=_dl("queued"))

    job = _client(handler).downloads.redeliver("dl_abc123")
    assert seen["path"] == "/v1/downloads/dl_abc123/redeliver"
    assert seen["body"] == {}
    assert isinstance(job, videofetch.DownloadJob) and job.status == "queued"


def test_redeliver_to_another_destination():
    seen = {}

    def handler(req):
        seen["body"] = _body(req)
        return httpx.Response(202, json=_dl("queued"))

    _client(handler).downloads.redeliver("dl_abc123", destination="st_other")
    assert seen["body"] == {"destination": "st_other"}


def test_redeliver_conflict():
    def handler(req):
        return httpx.Response(409, json={"detail": {"code": "not_redeliverable", "message": "expired"}})

    with pytest.raises(ConflictError) as exc:
        _client(handler).downloads.redeliver("dl_abc123")
    assert exc.value.code == "not_redeliverable" and exc.value.status_code == 409


# ── storage resource ───────────────────────────────────────────────────────────────────────

def test_storage_list_and_retrieve():
    def handler(req):
        if req.url.path == "/v1/storage":
            return httpx.Response(200, json={"items": [CONN]})
        assert req.url.path == "/v1/storage/st_9f1c2a34b5d6e7f8"
        return httpx.Response(200, json=CONN)

    c = _client(handler)
    items = c.storage.list()
    assert len(items) == 1
    s = items[0]
    assert s.id.startswith("st_") and s.is_default and s.status == "failing"
    assert s.last_error_code == "storage_permission_denied" and s.deliveries_count == 12
    assert c.storage.retrieve(s.id).bucket == "acme-media"


def test_storage_create_drops_unset_fields():
    seen = {}

    def handler(req):
        seen.update(_body(req))
        return httpx.Response(201, json=CONN)

    conn = _client(handler).storage.create(provider="s3", bucket="acme-media", region="us-east-1",
                                           access_key_id="AKIA", secret_access_key="sec", is_default=True)
    assert seen == {"provider": "s3", "bucket": "acme-media", "region": "us-east-1",
                    "access_key_id": "AKIA", "secret_access_key": "sec", "is_default": True}
    assert conn.id == CONN["id"]


def test_storage_update_and_delete_force():
    seen = []

    def handler(req):
        seen.append((req.method, req.url.path, dict(req.url.params), _body(req)))
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(200, json=CONN)

    c = _client(handler)
    c.storage.update("st_x", name="New", is_default=False)
    c.storage.delete("st_x")
    c.storage.delete("st_x", force=True)
    assert seen[0] == ("PUT", "/v1/storage/st_x", {}, {"name": "New", "is_default": False})
    assert seen[1][2] == {} and seen[2][2] == {"force": "true"}


def test_storage_delete_in_use_conflict():
    def handler(req):
        return httpx.Response(409, json={"detail": {"code": "storage_in_use", "message": "2 jobs"}})

    with pytest.raises(ConflictError) as exc:
        _client(handler).storage.delete("st_x")
    assert exc.value.code == "storage_in_use"


def test_storage_test_saved_and_inline():
    seen = []
    result = {"ok": False, "code": "storage_permission_denied", "message": "denied", "hint": "h",
              "provider_code": "AccessDenied", "probe_key": "youtube/.vf-probe",
              "steps": [{"name": "connect", "ok": True},
                        {"name": "write", "ok": False, "code": "storage_permission_denied", "message": "denied"}]}

    def handler(req):
        seen.append((req.url.path, _body(req)))
        return httpx.Response(200, json=result)

    c = _client(handler)
    r = c.storage.test("st_x")
    assert not r.ok and r.code == "storage_permission_denied"
    assert [s.name for s in r.steps] == ["connect", "write"] and r.steps[1].ok is False
    c.storage.test(provider="gcs", bucket="b", access_key_id="k", secret_access_key="s")
    assert seen[0] == ("/v1/storage/st_x/test", None)
    assert seen[1] == ("/v1/storage/test", {"provider": "gcs", "bucket": "b",
                                            "access_key_id": "k", "secret_access_key": "s"})


def test_async_storage_and_redeliver():
    def handler(req):
        if req.url.path == "/v1/storage":
            return httpx.Response(200, json={"items": [CONN]})
        return httpx.Response(202, json=_dl("queued"))

    async def run():
        c = videofetch.AsyncVideoFetch(
            api_key="vf_live_sk_test", base_url="http://mock", max_retries=0,
            http_client=httpx.AsyncClient(base_url="http://mock", transport=httpx.MockTransport(handler)))
        items = await c.storage.list()
        job = await c.downloads.redeliver("dl_abc123", destination={"id": items[0].id, "path": "x/"})
        return items, job

    items, job = asyncio.run(run())
    assert items[0].id == CONN["id"] and job.id == "dl_abc123"


def test_webhook_events_include_storage_connection_failed():
    assert "storage.connection_failed" in WEBHOOK_EVENTS
