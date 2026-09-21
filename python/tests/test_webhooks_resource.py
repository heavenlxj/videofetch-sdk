"""Webhooks *resource* (endpoint CRUD + test) tests — httpx MockTransport, no network."""
import asyncio
import json

import httpx

import videofetch
from videofetch.models import WebhookEndpoint, WebhookList, WebhookTestResult

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
