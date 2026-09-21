import { describe, expect, it } from "vitest";
import {
  VideoFetch, RateLimitError, QuotaExceededError, PermissionDeniedError, ValidationError,
} from "../src";

function makeFetch(handler: (url: string, init: RequestInit) => Promise<Response>) {
  return handler as unknown as typeof fetch;
}

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

describe("error semantics (v0.2.0)", () => {
  it("429 concurrency_limit_exceeded → RateLimitError with limit/active/scope/retryAfter", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(429, {
        detail: {
          code: "concurrency_limit_exceeded",
          message: "Too many in-flight jobs: 5/5 (queued+processing).",
          param: "url", limit: 5, active: 5, scope: "account",
        },
      }, {
        "Retry-After": "10",
        "X-Concurrency-Limit": "5",
        "X-Concurrency-Active": "5",
      }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 });
    const err = await client.downloads.create({ url: "https://youtu.be/x" }).catch((e) => e as RateLimitError);
    expect(err).toBeInstanceOf(RateLimitError);
    expect(err.code).toBe("concurrency_limit_exceeded");
    expect(err.limit).toBe(5);
    expect(err.active).toBe(5);
    expect(err.scope).toBe("account");
    expect(err.retryAfter).toBe(10);
    expect(err.statusCode).toBe(429);
  });

  it("429 platform_at_capacity keeps code + Retry-After", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(429, {
        detail: { code: "platform_at_capacity", message: "Platform at capacity.", limit: 100, active: 100, scope: "platform" },
      }, { "Retry-After": "30" }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 });
    const err = await client.downloads.create({ url: "https://youtu.be/x" }).catch((e) => e as RateLimitError);
    expect(err).toBeInstanceOf(RateLimitError);
    expect(err.code).toBe("platform_at_capacity");
    expect(err.scope).toBe("platform");
    expect(err.retryAfter).toBe(30);
  });

  it("429 retryAfter falls back to the X-Concurrency headers when detail is sparse", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(429, { detail: { code: "queue_limit_exceeded", message: "queue full" } },
        { "Retry-After": "7", "X-Concurrency-Limit": "50", "X-Concurrency-Active": "50" }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 });
    const err = await client.downloads.create({ url: "https://youtu.be/x" }).catch((e) => e as RateLimitError);
    expect(err).toBeInstanceOf(RateLimitError);
    expect(err.code).toBe("queue_limit_exceeded");
    expect(err.limit).toBe(50);
    expect(err.active).toBe(50);
    expect(err.retryAfter).toBe(7);
  });

  it("403 account_suspended → PermissionDeniedError carrying .code", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(403, {
        detail: { code: "account_suspended", message: "This account is suspended. Contact support." },
      }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 });
    const err = await client.usage.get().catch((e) => e as PermissionDeniedError);
    expect(err).toBeInstanceOf(PermissionDeniedError);
    expect(err.code).toBe("account_suspended");
    expect(err.statusCode).toBe(403);
  });

  it("402 quota_exceeded → QuotaExceededError with remaining_gb", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(402, { detail: { code: "quota_exceeded", message: "Free tier exhausted", remaining_gb: 0.25 } }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 });
    const err = await client.downloads.create({ url: "https://youtu.be/x" }).catch((e) => e as QuotaExceededError);
    expect(err).toBeInstanceOf(QuotaExceededError);
    expect(err.remainingGb).toBe(0.25);
    expect(err.statusCode).toBe(402);
  });

  it("422 invalid_webhook → ValidationError with code/param", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(422, { detail: { code: "invalid_webhook", message: "url must be http(s).", param: "url" } }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 });
    const err = await client.webhooks.create("ftp://nope").catch((e) => e as ValidationError);
    expect(err).toBeInstanceOf(ValidationError);
    expect(err.code).toBe("invalid_webhook");
  });
});
