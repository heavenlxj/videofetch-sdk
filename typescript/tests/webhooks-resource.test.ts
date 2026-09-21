import { describe, expect, it, vi } from "vitest";
import { VideoFetch, WEBHOOK_EVENTS } from "../src";

function makeFetch(handler: (url: string, init: RequestInit) => Promise<Response>) {
  return vi.fn(async (url: string | URL | Request, init?: RequestInit) =>
    handler(String(url), init ?? {})) as unknown as typeof fetch;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const FULL_SECRET = "whsec_0123456789abcdef0123456789abcdef0123456789abcdef";

describe("webhooks resource", () => {
  it("exposes the full download.*/quota.*/balance.low event catalogue", () => {
    expect(WEBHOOK_EVENTS).toEqual([
      "download.queued", "download.processing", "download.completed", "download.failed",
      "quota.warning", "quota.exceeded", "balance.low",
    ]);
  });

  it("create() posts the url + events and returns the plaintext secret (201)", async () => {
    const fetchMock = makeFetch(async (url, init) => {
      expect(url).toBe("http://mock/v1/webhooks");
      expect(init.method).toBe("POST");
      const body = JSON.parse(String(init.body));
      expect(body.url).toBe("https://example.com/hook");
      expect(body.events).toEqual(["download.completed", "quota.exceeded"]);
      return jsonResponse(201, {
        id: "wh_1", url: body.url, secret: FULL_SECRET, events: body.events,
        active: true, last_delivery_at: null, last_status: null, failure_count: 0,
        created_at: "2026-09-21T00:00:00Z",
      });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const wh = await client.webhooks.create("https://example.com/hook", [
      "download.completed", "quota.exceeded",
    ]);
    expect(wh.id).toBe("wh_1");
    expect(wh.secret).toBe(FULL_SECRET);      // full secret only on create
    expect(wh.events).toContain("quota.exceeded");
  });

  it("create() without events omits the events field (server defaults to all)", async () => {
    const fetchMock = makeFetch(async (_url, init) => {
      const body = JSON.parse(String(init.body));
      expect(body).not.toHaveProperty("events");
      return jsonResponse(201, { id: "wh_2", url: body.url, secret: FULL_SECRET, events: WEBHOOK_EVENTS, active: true });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await client.webhooks.create("https://example.com/hook");
  });

  it("list() returns masked secrets", async () => {
    const masked = FULL_SECRET.slice(0, 11) + "********" + FULL_SECRET.slice(-4);
    const fetchMock = makeFetch(async (url) => {
      expect(url).toBe("http://mock/v1/webhooks");
      return jsonResponse(200, { items: [{ id: "wh_1", url: "https://example.com/hook", secret: masked, events: WEBHOOK_EVENTS, active: true }] });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const list = await client.webhooks.list();
    expect(list.items).toHaveLength(1);
    expect(list.items[0].secret).toBe(masked);
    expect(list.items[0].secret).toContain("*");     // masked, not the real one
    expect(list.items[0].secret).not.toBe(FULL_SECRET);
  });

  it("test() POSTs /test and returns the delivery report", async () => {
    const fetchMock = makeFetch(async (url, init) => {
      expect(url).toBe("http://mock/v1/webhooks/wh_1/test");
      expect(init.method).toBe("POST");
      return jsonResponse(200, {
        delivered: true, url: "https://example.com/hook", last_status: 200,
        signature_header: "X-VideoFetch-Signature",
        signature_format: "sha256=<hex hmac-sha256 of raw body>",
      });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const res = await client.webhooks.test("wh_1");
    expect(res.delivered).toBe(true);
    expect(res.signature_header).toBe("X-VideoFetch-Signature");
    expect(res.signature_format).toContain("sha256=");
  });

  it("delete() DELETEs and tolerates a 204 with no body", async () => {
    const fetchMock = makeFetch(async (url, init) => {
      expect(url).toBe("http://mock/v1/webhooks/wh_1");
      expect(init.method).toBe("DELETE");
      return new Response(null, { status: 204 });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await expect(client.webhooks.delete("wh_1")).resolves.toBeUndefined();
  });
});
