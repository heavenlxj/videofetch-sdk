import { describe, expect, it, vi, beforeEach } from "vitest";
import { VideoFetch, JobFailedError, QuotaExceededError, ValidationError } from "../src";

function downloadJson(status: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "dl_abc123", status, url: "https://www.youtube.com/watch?v=x",
    format: "1080p", progress: 0, title: "T", cost_usd: 0, attempts: 0,
    ...overrides,
  };
}

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

describe("VideoFetch client", () => {
  it("creates a queued job (POST /v1/downloads)", async () => {
    const fetchMock = makeFetch(async (url, init) => {
      expect(url).toBe("http://mock/v1/downloads");
      const body = JSON.parse(String(init.body));
      expect(body.format).toBe("1080p");
      expect(body.trim).toEqual({ start: 10, end: 20 });
      return jsonResponse(202, downloadJson("queued"));
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const job = await client.downloads.create({
      url: "https://youtu.be/x", format: "1080p", trim: { start: 10, end: 20 },
    });
    expect(job.id).toBe("dl_abc123");
    expect(job.status).toBe("queued");
  });

  it("wait() polls until completed and returns the result", async () => {
    let getCalls = 0;
    const fetchMock = makeFetch(async (_url, init) => {
      const method = (init.method ?? "GET").toUpperCase();
      if (method === "POST") return jsonResponse(202, downloadJson("queued"));
      getCalls += 1;
      if (getCalls < 3) return jsonResponse(200, downloadJson("processing", { progress: 55 }));
      return jsonResponse(200, downloadJson("completed", {
        progress: 100, download_url: "https://cdn.example/v.mp4",
        size_bytes: 12345, cost_usd: 0.0042, strategy: "direct", attempts: 1,
      }));
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const result = await client.downloads.createAndWait(
      { url: "https://youtu.be/x", format: "720p" },
      { timeoutMs: 10_000 },
    );
    expect(result.status).toBe("completed");
    expect(result.download_url).toContain("cdn.example");
    expect(getCalls).toBe(3);
  }, 15_000);

  it("wait() throws JobFailedError on failed job", async () => {
    const fetchMock = makeFetch(async (_url, init) => {
      const method = (init.method ?? "GET").toUpperCase();
      if (method === "POST") return jsonResponse(202, downloadJson("queued"));
      return jsonResponse(200, downloadJson("failed", {
        error_code: "download_failed", error_message: "blocked",
      }));
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const job = await client.downloads.create({ url: "https://youtu.be/x" });
    await expect(job.wait({ timeoutMs: 10_000, pollIntervalMs: 10 }))
      .rejects.toBeInstanceOf(JobFailedError);
  }, 15_000);

  it("maps 402 to QuotaExceededError", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(402, { detail: { code: "quota_exceeded", message: "Free tier exhausted", remaining_gb: 0 } }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await expect(client.downloads.create({ url: "https://youtu.be/x", format: "8k" as never }))
      .rejects.toBeInstanceOf(QuotaExceededError);
  });

  it("maps 422 invalid_format to ValidationError", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(422, { detail: { code: "invalid_format", message: "bad format", param: "format" } }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    await expect(client.downloads.retrieve("dl_missing")).rejects.toBeInstanceOf(ValidationError);
  });

  it("info.lookup hits POST /v1/info", async () => {
    const fetchMock = makeFetch(async () => jsonResponse(200, {
      id: "abc", url: "https://youtu.be/x", title: "Hello", duration: 120,
      formats: [{ quality: "720p", size: 1000 }],
    }));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });
    const info = await client.info.lookup("https://youtu.be/x");
    expect(info.title).toBe("Hello");
    expect(info.formats[0].quality).toBe("720p");
  });
});
