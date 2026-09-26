import { describe, expect, it, vi } from "vitest";
import {
  ConflictError,
  DeliveryFailedError,
  JobFailedError,
  StorageError,
  ValidationError,
  VideoFetch,
  WEBHOOK_EVENTS,
} from "../src";

const CONN = {
  id: "st_9f1c2a34b5d6e7f8", name: "Prod", provider: "s3", bucket: "acme-media",
  path_prefix: "youtube/{video_id}/", is_default: true, status: "failing", deliveries_count: 3,
  last_error: { code: "storage_permission_denied", message: "denied", at: "2026-09-26T10:00:00Z" },
  created_at: "2026-09-01T00:00:00Z",
};

const job = (status = "queued", extra: Record<string, unknown> = {}) => ({
  id: "dl_abc123", status, url: "https://youtu.be/x", format: "720p", ...extra,
});

interface Seen { method: string; url: URL; body: unknown }

function client(handler: (req: Seen) => [number, unknown?]) {
  const seen: Seen[] = [];
  const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
    const req = {
      method: init?.method ?? "GET",
      url: new URL(String(input)),
      body: init?.body ? JSON.parse(String(init.body)) : undefined,
    };
    seen.push(req);
    const [status, body] = handler(req);
    return body === undefined
      ? new Response(null, { status })
      : new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return { c: new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock, maxRetries: 0 }), seen };
}

describe("destination shorthands", () => {
  it.each([
    "st_9f1c2a34b5d6e7f8",
    "url",
    { id: "st_9f1c2a34b5d6e7f8", key: "clips/{video_id}.{ext}" },
    { type: "gcs", bucket: "b", access_key_id: "k", secret_access_key: "s", save: true, name: "GCS" },
  ] as const)("forwards %j unchanged", async (destination) => {
    const { c, seen } = client(() => [202, job()]);
    await c.downloads.create({ url: "https://youtu.be/x", destination });
    expect((seen[0].body as { destination: unknown }).destination).toEqual(destination);
  });

  it("rejects an empty string", async () => {
    const { c } = client(() => [202, job()]);
    await expect(c.downloads.create({ url: "https://youtu.be/x", destination: "  " })).rejects.toThrow(/empty/);
  });
});

describe("storage errors", () => {
  it("maps 422 storage_* to StorageError with hint + param", async () => {
    const { c } = client(() => [422, { detail: {
      code: "storage_config_invalid", message: "R2 needs an endpoint", hint: "Use https://<account>.r2…",
      param: "destination.endpoint" } }]);
    const err = await c.downloads.create({ url: "https://youtu.be/x", destination: "st_x" }).catch((e) => e);
    expect(err).toBeInstanceOf(StorageError);
    expect(err).toBeInstanceOf(ValidationError);
    expect(err.code).toBe("storage_config_invalid");
    expect(err.param).toBe("destination.endpoint");
    expect(err.hint).toMatch(/^Use https/);
  });

  it("keeps other 422s as plain ValidationError", async () => {
    const { c } = client(() => [422, { detail: { code: "invalid_format", message: "bad" } }]);
    const err = await c.downloads.create({ url: "https://youtu.be/x" }).catch((e) => e);
    expect(err).toBeInstanceOf(ValidationError);
    expect(err).not.toBeInstanceOf(StorageError);
  });

  it("maps 409 to ConflictError", async () => {
    const { c } = client(() => [409, { detail: { code: "storage_in_use", message: "2 jobs" } }]);
    const err = await c.storage.delete("st_x").catch((e) => e);
    expect(err).toBeInstanceOf(ConflictError);
    expect(err.code).toBe("storage_in_use");
  });
});

describe("delivery and error objects", () => {
  it("throws DeliveryFailedError for a delivery-stage failure", async () => {
    const failed = job("failed", {
      error_code: "storage_bucket_not_found", error_message: "no bucket",
      error: { code: "storage_bucket_not_found", stage: "delivery", retryable: false,
               provider_code: "NoSuchBucket", hint: "Check the bucket name" },
      delivery: { type: "storage", status: "failed", redeliverable: true, hold_expires_at: "2026-09-27T10:00:00Z" },
    });
    const { c } = client((r) => (r.method === "POST" ? [202, job()] : [200, failed]));
    const j = await c.downloads.create({ url: "https://youtu.be/x", destination: "st_x" });
    const err = await j.wait({ timeoutMs: 10_000, pollIntervalMs: 1 }).catch((e) => e);
    expect(err).toBeInstanceOf(DeliveryFailedError);
    expect(err).toBeInstanceOf(JobFailedError);
    expect(err.stage).toBe("delivery");
    expect(err.providerCode).toBe("NoSuchBucket");
    expect(err.redeliverable).toBe(true);
    expect(err.holdExpiresAt).toBe("2026-09-27T10:00:00Z");
    expect(err.download.error.code).toBe("storage_bucket_not_found");
  });

  it("keeps fetch failures as plain JobFailedError", async () => {
    const failed = job("failed", { error_code: "download_failed", error: { code: "download_failed", stage: "fetch", retryable: true } });
    const { c } = client((r) => (r.method === "POST" ? [202, failed] : [200, failed]));
    const j = await c.downloads.create({ url: "https://youtu.be/x" });
    const err = await j.wait().catch((e) => e);
    expect(err).toBeInstanceOf(JobFailedError);
    expect(err).not.toBeInstanceOf(DeliveryFailedError);
    expect(err.retryable).toBe(true);
  });
});

describe("redeliver", () => {
  it("posts an empty body by default", async () => {
    const { c, seen } = client(() => [202, job()]);
    const j = await c.downloads.redeliver("dl_abc123");
    expect(seen[0].method).toBe("POST");
    expect(seen[0].url.pathname).toBe("/v1/downloads/dl_abc123/redeliver");
    expect(seen[0].body).toEqual({});
    expect(j.status).toBe("queued");
  });

  it("can switch destination", async () => {
    const { c, seen } = client(() => [202, job()]);
    await c.downloads.redeliver("dl_abc123", "url");
    expect(seen[0].body).toEqual({ destination: "url" });
  });

  it("surfaces not_redeliverable as ConflictError", async () => {
    const { c } = client(() => [409, { detail: { code: "not_redeliverable", message: "expired" } }]);
    await expect(c.downloads.redeliver("dl_abc123")).rejects.toBeInstanceOf(ConflictError);
  });
});

describe("storage resource", () => {
  it("lists, retrieves, creates, updates", async () => {
    const { c, seen } = client((r) =>
      r.url.pathname === "/v1/storage" && r.method === "GET" ? [200, { items: [CONN] }] : [200, CONN]);
    const items = await c.storage.list();
    expect(items[0].id).toBe(CONN.id);
    expect(items[0].last_error?.code).toBe("storage_permission_denied");
    await c.storage.retrieve(CONN.id);
    await c.storage.create({ provider: "s3", bucket: "acme-media", access_key_id: "A", secret_access_key: "S", is_default: true });
    await c.storage.update(CONN.id, { name: "Renamed" });
    expect(seen.map((s) => `${s.method} ${s.url.pathname}`)).toEqual([
      "GET /v1/storage", `GET /v1/storage/${CONN.id}`, "POST /v1/storage", `PUT /v1/storage/${CONN.id}`,
    ]);
    expect(seen[2].body).toEqual({ provider: "s3", bucket: "acme-media", access_key_id: "A", secret_access_key: "S", is_default: true });
    expect(seen[3].body).toEqual({ name: "Renamed" });
  });

  it("deletes with and without force", async () => {
    const { c, seen } = client(() => [204]);
    await c.storage.delete("st_x");
    await c.storage.delete("st_x", { force: true });
    expect(seen[0].url.search).toBe("");
    expect(seen[1].url.searchParams.get("force")).toBe("true");
  });

  it("tests saved and unsaved connections", async () => {
    const result = { ok: false, code: "storage_unreachable", message: "no route", steps: [{ name: "connect", ok: false }] };
    const { c, seen } = client(() => [200, result]);
    const saved = await c.storage.test("st_x");
    expect(saved.ok).toBe(false);
    expect(saved.steps[0].name).toBe("connect");
    await c.storage.test({ provider: "s3_compatible", bucket: "b", endpoint: "https://minio.acme.dev", access_key_id: "k", secret_access_key: "s" });
    expect(seen[0].url.pathname).toBe("/v1/storage/st_x/test");
    expect(seen[1].url.pathname).toBe("/v1/storage/test");
    expect((seen[1].body as { provider: string }).provider).toBe("s3_compatible");
  });
});

it("webhook events include storage.connection_failed", () => {
  expect(WEBHOOK_EVENTS).toContain("storage.connection_failed");
});
