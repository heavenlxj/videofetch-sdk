"""Usage + alerts resource tests against a mocked httpx transport (no network)."""
import asyncio

import httpx

import videofetch
from videofetch.models import AlertEvent, AlertState, Usage, UsageAlerts

USAGE_JSON = {
    "key_id": "key_1", "plan": "free", "quota_gb": 1.0,
    "used_bytes": 107374182, "used_gb": 0.1, "remaining_gb": 0.9,
    "key_used_bytes": 53687091, "key_used_gb": 0.05,
    "payg_balance_cents": 0, "payg_rate_usd_per_gb": 0.5,
    "account_used_bytes_month": 107374182, "account_used_gb_month": 0.1,
    "used_pct": 10.0, "month": "2026-09", "active_jobs": 2,
    "concurrency_limit": 5, "alert_level": "ok", "alert_message": "",
}

ALERTS_JSON = {
    "state": {
        "level": "warning", "pct_used": 82.5, "thresholds": [80, 95, 100],
        "crossed": [80], "next_threshold_pct": 95, "quota_gb": 1.0,
        "used_gb_month": 0.825, "remaining_gb": 0.175, "month": "2026-09",
        "plan": "free", "payg_balance_cents": 0, "balance_low": False,
        "balance_depleted": True,
        "balance_hint": "No credit balance left — pay-as-you-go overage is unavailable.",
        "message": "82.5% of your 1 GB monthly quota used.",
        "action": "upgrade",
    },
    "fired": [{
        "id": "al_1", "kind": "usage_threshold", "level": "warning", "threshold": 80,
        "pct_used": 82.5, "used_gb": 0.825, "quota_gb": 1.0, "balance_cents": 0,
        "message": "82.5% of your 1 GB monthly quota used.", "delivered": True,
        "created_at": "2026-09-21T12:00:00",
    }],
    "thresholds": [80, 95, 100],
    "topup_amounts": [10, 25, 50, 100],
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


def test_usage_get_maps_all_fields():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["method"] = req.method
        return httpx.Response(200, json=USAGE_JSON)

    c = _client(handler)
    u = c.usage.get()
    assert seen["path"] == "/v1/usage" and seen["method"] == "GET"
    assert isinstance(u, Usage)
    assert u.key_id == "key_1" and u.plan == "free"
    assert u.quota_gb == 1.0 and u.used_gb == 0.1 and u.remaining_gb == 0.9
    assert u.payg_rate_usd_per_gb == 0.5
    assert u.account_used_bytes_month == 107374182
    assert u.used_pct == 10.0 and u.month == "2026-09"
    assert u.active_jobs == 2 and u.concurrency_limit == 5
    assert u.alert_level == "ok"
    # v0.3.0: used_* is account-level; key_used_* is per-key attribution.
    assert u.used_bytes == u.account_used_bytes_month
    assert u.used_gb == u.account_used_gb_month
    assert u.key_used_bytes == 53687091 and u.key_used_gb == 0.05


def test_usage_key_used_defaults_to_zero_when_absent():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "key_id": "k", "plan": "free", "quota_gb": 1.0,
            "used_bytes": 107374182, "used_gb": 0.1})

    c = _client(handler)
    u = c.usage.get()
    assert u.used_gb == 0.1                          # account-level month
    assert u.key_used_bytes == 0 and u.key_used_gb == 0.0


def test_usage_get_defaults_when_fields_missing():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"key_id": "k", "plan": "free", "quota_gb": None})

    c = _client(handler)
    u = c.usage.get()
    assert u.quota_gb is None and u.used_bytes == 0 and u.concurrency_limit == 0
    assert u.alert_level == "ok" and u.used_pct == 0.0


def test_usage_alerts_full_shape():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        return httpx.Response(200, json=ALERTS_JSON)

    c = _client(handler)
    a = c.usage.alerts()
    assert seen["path"] == "/v1/usage/alerts"
    assert isinstance(a, UsageAlerts)
    assert a.thresholds == [80, 95, 100]
    assert a.topup_amounts == [10, 25, 50, 100]
    st = a.state
    assert isinstance(st, AlertState)
    assert st.level == "warning" and st.crossed == [80] and st.next_threshold_pct == 95
    assert st.quota_gb == 1.0 and st.balance_depleted is True
    assert st.action == "upgrade"
    assert len(a.fired) == 1
    ev = a.fired[0]
    assert isinstance(ev, AlertEvent)
    assert ev.id == "al_1" and ev.threshold == 80 and ev.delivered is True
    assert ev.created_at == "2026-09-21T12:00:00"


def test_usage_alerts_empty_state():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"state": {"level": "ok", "thresholds": [80, 95, 100]},
                                         "fired": [], "thresholds": [80, 95, 100],
                                         "topup_amounts": [10, 25, 50, 100]})

    c = _client(handler)
    a = c.usage.alerts()
    assert a.fired == [] and a.state.level == "ok"
    assert a.state.crossed == [] and a.state.action is None


# ── async parity (wrapped in wait_for so a hang fails fast) ──
def test_async_usage_get_and_alerts():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/usage":
            return httpx.Response(200, json=USAGE_JSON)
        return httpx.Response(200, json=ALERTS_JSON)

    async def run():
        c = _aclient(handler)
        u = await asyncio.wait_for(c.usage.get(), timeout=5)
        a = await asyncio.wait_for(c.usage.alerts(), timeout=5)
        await c.close()
        return u, a

    u, a = asyncio.run(run())
    assert u.quota_gb == 1.0 and u.concurrency_limit == 5
    assert a.thresholds == [80, 95, 100] and a.topup_amounts == [10, 25, 50, 100]
    assert a.state.action == "upgrade"
