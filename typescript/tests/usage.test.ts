import { describe, expect, it } from "vitest";
import { VideoFetch } from "../src";

function makeFetch(handler: (url: string, init: RequestInit) => Promise<Response>) {
  return handler as unknown as typeof fetch;
}

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function usageBody(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    key_id: "key_1", plan: "free", quota_gb: 1.0, used_bytes: 0, used_gb: 0.0,
    remaining_gb: 1.0, payg_balance_cents: 0, payg_rate_usd_per_gb: 0.5,
    account_used_bytes_month: 0, account_used_gb_month: 0.0, used_pct: 0.0,
    month: "2026-09", active_jobs: 0, concurrency_limit: 5,
    alert_level: "ok", alert_message: "",
    ...overrides,
  };
}

const ALERTS_BODY = {
  state: {
    level: "warning", pct_used: 82.5, thresholds: [80, 95, 100], crossed: [80],
    next_threshold_pct: 95, quota_gb: 1.0, used_gb_month: 0.825, remaining_gb: 0.175,
    month: "2026-09", plan: "free", payg_balance_cents: 0, balance_low: false,
    balance_depleted: true, balance_hint: "top up", message: "82.5% used", action: "upgrade",
  },
  fired: [{
    id: "al_1", kind: "usage_threshold", level: "warning", threshold: 80, pct_used: 82.5,
    used_gb: 0.825, quota_gb: 1.0, balance_cents: 0, message: "80% crossed",
    delivered: true, created_at: "2026-09-21T00:00:00Z",
  }],
  thresholds: [80, 95, 100],
  topup_amounts: [10, 25, 50, 100],
};

describe("usage resource", () => {
  it("get() → GET /v1/usage with account-level fields", async () => {
    let seenUrl = "";
    const fetchMock = makeFetch(async (url) => {
      seenUrl = url;
      return jsonResponse(200, usageBody());
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const usage = await client.usage.get();
    expect(seenUrl).toBe("http://mock/v1/usage");
    expect(usage.quota_gb).toBe(1.0);
    expect(usage.concurrency_limit).toBe(5);
    expect(usage.remaining_gb).toBe(1.0);
    expect(usage.alert_level).toBe("ok");
    expect(usage.payg_rate_usd_per_gb).toBe(0.5);
  });

  it("get() surfaces a warning alert level + message", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(200, usageBody({ used_pct: 96.0, alert_level: "critical", alert_message: "less than 5% left" })));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const usage = await client.usage.get();
    expect(usage.alert_level).toBe("critical");
    expect(usage.alert_message).toContain("5%");
    expect(usage.used_pct).toBe(96.0);
  });

  it("alerts() → GET /v1/usage/alerts with thresholds + topup amounts", async () => {
    let seenUrl = "";
    const fetchMock = makeFetch(async (url) => {
      seenUrl = url;
      return jsonResponse(200, ALERTS_BODY);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const alerts = await client.usage.alerts();
    expect(seenUrl).toBe("http://mock/v1/usage/alerts");
    expect(alerts.thresholds).toEqual([80, 95, 100]);
    expect(alerts.topup_amounts).toEqual([10, 25, 50, 100]);
    expect(alerts.state.level).toBe("warning");
    expect(alerts.state.crossed).toEqual([80]);
    expect(alerts.state.next_threshold_pct).toBe(95);
    expect(alerts.state.action).toBe("upgrade");
    expect(alerts.fired).toHaveLength(1);
    expect(alerts.fired[0].delivered).toBe(true);
  });

  it("get() surfaces account-level used_* alongside key_used_* (v0.3.0)", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(200, usageBody({
        used_bytes: 5_000_000_000, used_gb: 5.0,
        key_used_bytes: 2_000_000_000, key_used_gb: 2.0,
        account_used_bytes_month: 5_000_000_000, account_used_gb_month: 5.0,
        used_pct: 50.0,
      })));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const usage = await client.usage.get();
    expect(usage.used_gb).toBe(5.0);        // account-level usage for the month
    expect(usage.key_used_gb).toBe(2.0);    // this key's own usage
    expect(usage.key_used_bytes).toBe(2_000_000_000);
  });
});
