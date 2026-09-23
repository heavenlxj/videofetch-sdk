import { describe, expect, it } from "vitest";
import {
  VideoFetch,
  getDeliveryId,
  getAttemptNumber,
  type Download,
  type Usage,
  type WebhookDelivery,
  type WebhookDeliveriesResult,
} from "../src";

function makeFetch(handler: (url: string, init: RequestInit) => Promise<Response>) {
  return handler as unknown as typeof fetch;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const DELIVERIES_BODY: WebhookDeliveriesResult = {
  endpoint_id: "wh_1",
  active: true,
  auto_disabled_at: null,
  consecutive_failures: 0,
  max_attempts: 3,
  retry_schedule_seconds: "30,300",
  health: { total: 1, succeeded: 0, dead: 0, pending: 1, success_rate: null },
  items: [{
    event_id: "evt_1", event: "download.completed", seq: 1, status: "pending",
    attempts: 1, max_attempts: 3, last_status_code: 500, last_error: "HTTP 500",
    next_attempt_at: "2026-09-23T00:00:30Z", created_at: "2026-09-23T00:00:00Z",
    delivered_at: null, download_id: "dl_1",
  }],
};

describe("webhooks.deliveries()", () => {
  it("GETs /v1/webhooks/{id}/deliveries with the limit param", async () => {
    let seenUrl = "";
    const fetchMock = makeFetch(async (url, init) => {
      seenUrl = url;
      expect(init.method).toBe("GET");
      return jsonResponse(200, DELIVERIES_BODY);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const res = await client.webhooks.deliveries("wh_1", 50);

    expect(seenUrl).toBe("http://mock/v1/webhooks/wh_1/deliveries?limit=50");
    expect(res.endpoint_id).toBe("wh_1");
    expect(res.max_attempts).toBe(3);
    expect(res.retry_schedule_seconds).toBe("30,300");
    expect(res.health.success_rate).toBeNull();
    expect(res.items).toHaveLength(1);
    expect(res.items[0].event_id).toBe("evt_1");
    expect(res.items[0].status).toBe("pending");
    expect(res.items[0].attempts).toBe(1);
    expect(res.items[0].last_status_code).toBe(500);
    expect(res.items[0].delivered_at).toBeNull();
  });

  it("omits the limit param when not supplied", async () => {
    let seenUrl = "";
    const fetchMock = makeFetch(async (url) => {
      seenUrl = url;
      return jsonResponse(200, { ...DELIVERIES_BODY, items: [] });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await client.webhooks.deliveries("wh_1");
    expect(seenUrl).toBe("http://mock/v1/webhooks/wh_1/deliveries");
  });

  it("URL-encodes the endpoint id", async () => {
    let seenUrl = "";
    const fetchMock = makeFetch(async (url) => {
      seenUrl = url;
      return jsonResponse(200, { ...DELIVERIES_BODY, items: [] });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await client.webhooks.deliveries("wh/1#2");
    expect(seenUrl).toBe("http://mock/v1/webhooks/wh%2F1%232/deliveries");
  });
});

describe("webhooks.replay()", () => {
  it("POSTs /v1/webhooks/deliveries/{event_id}/replay", async () => {
    const fetchMock = makeFetch(async (url, init) => {
      expect(url).toBe("http://mock/v1/webhooks/deliveries/evt_1/replay");
      expect(init.method).toBe("POST");
      return jsonResponse(200, { queued: true, event_id: "evt_1" });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const res = await client.webhooks.replay("evt_1");
    expect(res.queued).toBe(true);
    expect(res.event_id).toBe("evt_1");
  });

  it("URL-encodes the event id", async () => {
    let seenUrl = "";
    const fetchMock = makeFetch(async (url) => {
      seenUrl = url;
      return jsonResponse(200, { queued: true, event_id: "evt/1" });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await client.webhooks.replay("evt/1");
    expect(seenUrl).toBe("http://mock/v1/webhooks/deliveries/evt%2F1/replay");
  });
});

describe("getDeliveryId()", () => {
  it("reads X-VideoFetch-Delivery case-insensitively", () => {
    expect(getDeliveryId({ "X-VideoFetch-Delivery": "evt_abc" })).toBe("evt_abc");
    expect(getDeliveryId({ "x-videofetch-delivery": "evt_abc" })).toBe("evt_abc");
    expect(getDeliveryId({ "X-VIDEOFETCH-DELIVERY": "evt_abc" })).toBe("evt_abc");
  });

  it("uses the first value when the header repeats", () => {
    expect(getDeliveryId({ "x-videofetch-delivery": ["evt_first", "evt_second"] })).toBe("evt_first");
  });

  it("returns null when absent or undefined", () => {
    expect(getDeliveryId({})).toBeNull();
    expect(getDeliveryId({ "x-videofetch-delivery": undefined })).toBeNull();
    expect(getDeliveryId({ "x-videofetch-event": "download.completed" })).toBeNull();
  });
});

describe("getAttemptNumber()", () => {
  it("parses X-VideoFetch-Attempt case-insensitively", () => {
    expect(getAttemptNumber({ "X-VideoFetch-Attempt": "1" })).toBe(1);
    expect(getAttemptNumber({ "x-videofetch-attempt": "3" })).toBe(3);
    expect(getAttemptNumber({ "x-videofetch-attempt": ["2"] })).toBe(2);
  });

  it("returns null for missing or non-integer values", () => {
    expect(getAttemptNumber({})).toBeNull();
    expect(getAttemptNumber({ "x-videofetch-attempt": "" })).toBeNull();
    expect(getAttemptNumber({ "x-videofetch-attempt": "abc" })).toBeNull();
    expect(getAttemptNumber({ "x-videofetch-attempt": "1.5" })).toBeNull();
  });
});

describe("new typed fields (v0.3.0 contract)", () => {
  it("Download carries the queue-position fields (null outside status=queued)", () => {
    const queued: Download = {
      id: "dl_1", status: "queued", url: "https://youtu.be/x", format: "720p",
      queue_position: 2, ahead_of_you: 1, estimated_wait_seconds: 45,
    };
    expect(queued.queue_position).toBe(2);
    expect(queued.ahead_of_you).toBe(1);
    expect(queued.estimated_wait_seconds).toBe(45);

    const done: Download = {
      id: "dl_1", status: "completed", url: "https://youtu.be/x", format: "720p",
      queue_position: null, ahead_of_you: null, estimated_wait_seconds: null,
    };
    expect(done.queue_position).toBeNull();
  });

  it("Usage exposes account-level used_* plus key_used_* fields", () => {
    const usage: Usage = {
      key_id: "key_1", plan: "free", quota_gb: 10, used_bytes: 5_000_000_000,
      used_gb: 5.0, key_used_bytes: 2_000_000_000, key_used_gb: 2.0,
      remaining_gb: 5.0, payg_balance_cents: 0, payg_rate_usd_per_gb: 0.5,
      account_used_bytes_month: 5_000_000_000, account_used_gb_month: 5.0,
      used_pct: 50.0, month: "2026-09", active_jobs: 0, concurrency_limit: 5,
      alert_level: "ok", alert_message: "",
    };
    expect(usage.used_gb).toBe(5.0);         // account-level
    expect(usage.key_used_gb).toBe(2.0);     // this key only
  });

  it("WebhookDelivery exposes the retry/backoff fields", () => {
    const item: WebhookDelivery = {
      event_id: "evt_1", event: "download.completed", seq: 3, status: "succeeded",
      attempts: 2, max_attempts: 3, last_status_code: 200, last_error: null,
      next_attempt_at: null, created_at: "2026-09-23T00:00:00Z",
      delivered_at: "2026-09-23T00:00:30Z", download_id: "dl_1",
    };
    expect(item.max_attempts).toBe(3);
    expect(item.status).toBe("succeeded");
    expect(item.seq).toBe(3);
  });
});
