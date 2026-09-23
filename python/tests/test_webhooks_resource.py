"""Webhooks *resource* (endpoint CRUD + test) tests — httpx MockTransport, no network."""
import asyncio
import json

import httpx
import pytest

import videofetch
from videofetch.errors import NotFoundError
from videofetch.models import (
    ReplayResult,
    WebhookDeliveriesResult,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookList,
    WebhookTestResult,
)

CREATE_JSON = {
    "id": "wh_1", "url": "https://acme.dev/hooks/vf",
    "secret": "whsec_" + "a" * 48,   # FULL secret only on create
    "events": ["download.queued", "download.processing", "download.completed",
               "download.failed", "quota.warning", "quota.exceeded", "balance.low"],
    "active": True, "last_delivery_at": None, "last_status": None,
    "failure_count": 0, "created_at": "2026-09-21T12:00:00",
}
LIST_JSON = {
    "items": [{**CREATE_JSON, "secret": "whsec_aaaaaa" + "*" * 8 + "aaaa"}],
}
DELIVERIES_JSON = {
    "endpoint_id": "wh_1", "active": True, "auto_disabled_at": None,
    "consecutive_failures": 0, "max_attempts": 3, "retry_schedule_seconds": "30,300",
    "health": {"total": 2, "succeeded": 1, "dead": 0, "pending": 1, "success_rate": 50.0},
    "items": [
        {"event_id": "evt_1", "event": "download.completed", "seq": 1, "status": "succeeded",
         "attempts": 1, "max_attempts": 3, "last_status_code": 200, "last_error": None,
         "next_attempt_at": None, "created_at": "2026-09-23T08:00:00+00:00",
         "delivered_at": "2026-09-23T08:00:01+00:00", "download_id": "dl_1"},
        {"event_id": "evt_2", "event": "download.failed", "seq": 2, "status": "pending",
         "attempts": 1, "max_attempts": 3, "last_status_code": 500, "last_error": "HTTP 500",
         "next_attempt_at": "2026-09-23T09:00:00+00:00",
         "created_at": "2026-09-23T08:30:00+00:00", "delivered_at": None, "download_id": "dl_2"},
    ],
}


def _client(handler, max_retries: int = 2) -> videofetch.VideoFetch:
    transport = httpx.MockTransport(handler)
    return videofetch.VideoFetch(
        api_key="vf_live_sk_test", base_url="http://mock", max_retries=max_retries,
        http_client=httpx.Client(base_url="http://mock", transport=transport),
    )


def _aclient(handler, max_retries: int = 2) -> videofetch.AsyncVideoFetch:
    transport = httpx.MockTransport(handler)
    return videofetch.AsyncVideoFetch(
        api_key="vf_live_sk_test", base_url="http://mock", max_retries=max_retries,
        http_client=httpx.AsyncClient(base_url="http://mock", transport=transport),
    )


def test_create_returns_full_secret():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["path"] = req.url.path
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(201, json=CREATE_JSON)

    c = _client(handler)
    ep = c.webhooks.create("https://acme.dev/hooks/vf",
                           events=["download.completed", "quota.exceeded"])
    assert captured["method"] == "POST" and captured["path"] == "/v1/webhooks"
    assert captured["body"] == {"url": "https://acme.dev/hooks/vf",
                                "events": ["download.completed", "quota.exceeded"]}
    assert isinstance(ep, WebhookEndpoint)
    assert ep.id == "wh_1" and ep.active is True
    assert ep.secret == CREATE_JSON["secret"]          # full, not masked
    assert len(ep.secret) == 54 and ep.secret.startswith("whsec_")


def test_create_without_events_omits_key():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(req.read().decode())
        return httpx.Response(201, json=CREATE_JSON)

    c = _client(handler)
    c.webhooks.create("https://acme.dev/hooks/vf")
    assert captured["body"] == {"url": "https://acme.dev/hooks/vf"}


def test_list_masks_secret():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/webhooks" and req.method == "GET"
        return httpx.Response(200, json=LIST_JSON)

    c = _client(handler)
    wl = c.webhooks.list()
    assert isinstance(wl, WebhookList) and len(wl.items) == 1
    assert wl.items[0].id == "wh_1"
    assert wl.items[0].secret != CREATE_JSON["secret"]
    assert "*" in wl.items[0].secret


def test_delete_is_204_none():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["method"] = req.method
        seen["path"] = req.url.path
        return httpx.Response(204)

    c = _client(handler)
    assert c.webhooks.delete("wh_1") is None
    assert seen == {"method": "DELETE", "path": "/v1/webhooks/wh_1"}


def test_test_returns_delivery_report():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST" and req.url.path == "/v1/webhooks/wh_1/test"
        return httpx.Response(200, json={
            "delivered": True, "url": "https://acme.dev/hooks/vf", "last_status": 200,
            "signature_header": "X-VideoFetch-Signature",
            "signature_format": "sha256=<hex hmac-sha256 of raw body>"})

    c = _client(handler)
    res = c.webhooks.test("wh_1")
    assert isinstance(res, WebhookTestResult)
    assert res.delivered is True and res.last_status == 200
    assert res.signature_header == "X-VideoFetch-Signature"
    assert "sha256=" in res.signature_format


def test_deliveries_returns_health_and_items():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["path"] = req.url.path
        captured["limit"] = req.url.params.get("limit")
        return httpx.Response(200, json=DELIVERIES_JSON)

    c = _client(handler)
    res = c.webhooks.deliveries("wh_1")
    assert captured["method"] == "GET"
    assert captured["path"] == "/v1/webhooks/wh_1/deliveries"
    assert captured["limit"] == "50"                       # default limit
    assert isinstance(res, WebhookDeliveriesResult)
    assert res.endpoint_id == "wh_1" and res.active is True
    assert res.auto_disabled_at is None and res.consecutive_failures == 0
    assert res.max_attempts == 3 and res.retry_schedule_seconds == "30,300"
    assert res.health.total == 2 and res.health.succeeded == 1
    assert res.health.pending == 1 and res.health.dead == 0
    assert res.health.success_rate == 50.0
    assert len(res.items) == 2
    first = res.items[0]
    assert isinstance(first, WebhookDelivery)
    assert first.event_id == "evt_1" and first.event == "download.completed"
    assert first.seq == 1 and first.status == "succeeded"
    assert first.attempts == 1 and first.max_attempts == 3
    assert first.last_status_code == 200 and first.download_id == "dl_1"
    assert first.delivered_at == "2026-09-23T08:00:01+00:00"

    second = res.items[1]
    assert second.status == "pending" and second.last_status_code == 500
    assert second.last_error == "HTTP 500"
    assert second.next_attempt_at == "2026-09-23T09:00:00+00:00"
    assert second.delivered_at is None


def test_deliveries_custom_limit_is_sent():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["limit"] = req.url.params.get("limit")
        return httpx.Response(200, json=DELIVERIES_JSON)

    c = _client(handler)
    c.webhooks.deliveries("wh_1", limit=5)
    assert captured["limit"] == "5"


def test_replay_queues_event():
    captured = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["method"] = req.method
        captured["path"] = req.url.path
        return httpx.Response(200, json={"queued": True, "event_id": "evt_1"})

    c = _client(handler)
    res = c.webhooks.replay("evt_1")
    assert captured == {"method": "POST", "path": "/v1/webhooks/deliveries/evt_1/replay"}
    assert isinstance(res, ReplayResult)
    assert res.queued is True and res.event_id == "evt_1"


def test_replay_unknown_event_raises_not_found():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": {"code": "not_found",
                                                    "message": "No such delivery"}})

    c = _client(handler, max_retries=0)
    with pytest.raises(NotFoundError):
        c.webhooks.replay("evt_missing")


def test_async_webhooks_crud_and_test():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and req.url.path == "/v1/webhooks":
            return httpx.Response(201, json=CREATE_JSON)
        if req.method == "GET" and req.url.path == "/v1/webhooks":
            return httpx.Response(200, json=LIST_JSON)
        if req.method == "POST" and req.url.path.endswith("/test"):
            return httpx.Response(200, json={"delivered": False, "url": CREATE_JSON["url"],
                                             "last_status": 500,
                                             "signature_header": "X-VideoFetch-Signature",
                                             "signature_format": "sha256=<hex>"})
        if req.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404, json={"detail": {"code": "not_found"}})

    async def run():
        c = _aclient(handler)
        ep = await asyncio.wait_for(c.webhooks.create("https://acme.dev/hooks/vf"), timeout=5)
        wl = await asyncio.wait_for(c.webhooks.list(), timeout=5)
        res = await asyncio.wait_for(c.webhooks.test(ep.id), timeout=5)
        deleted = await asyncio.wait_for(c.webhooks.delete(ep.id), timeout=5)
        await c.close()
        return ep, wl, res, deleted

    ep, wl, res, deleted = asyncio.run(run())
    assert ep.secret == CREATE_JSON["secret"]
    assert len(wl.items) == 1
    assert res.delivered is False and res.last_status == 500
    assert deleted is None


def test_async_deliveries_and_replay():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/v1/webhooks/wh_1/deliveries":
            return httpx.Response(200, json=DELIVERIES_JSON)
        if req.method == "POST" and req.url.path.endswith("/replay"):
            return httpx.Response(200, json={"queued": True, "event_id": "evt_1"})
        return httpx.Response(404, json={"detail": {"code": "not_found"}})

    async def run():
        c = _aclient(handler)
        res = await asyncio.wait_for(c.webhooks.deliveries("wh_1"), timeout=5)
        rep = await asyncio.wait_for(c.webhooks.replay("evt_1"), timeout=5)
        await c.close()
        return res, rep

    res, rep = asyncio.run(run())
    assert isinstance(res, WebhookDeliveriesResult) and len(res.items) == 2
    assert res.health.total == 2 and res.max_attempts == 3
    assert isinstance(rep, ReplayResult)
    assert rep.queued is True and rep.event_id == "evt_1"
