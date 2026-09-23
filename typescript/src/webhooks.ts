/**
 * Webhook signature verification.
 *
 * The server signs the raw request body with your endpoint secret (HMAC-SHA256)
 * and sends it in the `X-VideoFetch-Signature` header:
 *
 *     X-VideoFetch-Signature: sha256=<hex digest of raw body>
 *
 * Usage (Next.js route handler):
 *
 *     import { constructEvent } from "@videofetch/sdk";
 *     const payload = await request.text();
 *     const event = constructEvent(payload, request.headers.get("x-videoFetch-signature"), secret);
 */

import { VideoFetchError } from "./errors";
import type { VideoFetch } from "./client";
import type {
  WebhookEndpoint, WebhookEvent, WebhookList, WebhookPayload, WebhookTestResult,
  WebhookDeliveriesResult, WebhookReplayResult,
} from "./types";

export class SignatureVerificationError extends VideoFetchError {
  name = "SignatureVerificationError";
}

/**
 * Compute the expected signature header value for a payload.
 * Pure helper — same as the server side.
 */
export async function computeSignature(payload: string | Uint8Array, secret: string): Promise<string> {
  const subtle = await getSubtle();
  const key = await subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const data = typeof payload === "string" ? new TextEncoder().encode(payload) : payload;
  const sig: ArrayBuffer = await subtle.sign("HMAC", key, data as unknown as BufferSource);
  return `sha256=${toHex(new Uint8Array(sig))}`;
}

// DOM SubtleCrypto (browser/Node19+) vs node:crypto webcrypto are structurally
// incompatible in TS; return as `any` and let the runtime decide which exists.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
async function getSubtle(): Promise<any> {
  if (globalThis.crypto?.subtle) return globalThis.crypto.subtle;
  // Node 18 (before global webcrypto) — dynamic import keeps browser bundles safe
  const { webcrypto } = await import("node:crypto");
  return webcrypto.subtle;
}

/** Verify X-VideoFetch-Signature and return the parsed event payload. */
export async function constructEvent(
  payload: string | Uint8Array,
  sigHeader: string | null | undefined,
  secret: string,
): Promise<WebhookPayload> {
  // The signature is computed over the RAW request body. Passing an already
  // parsed object (e.g. `await req.json()`) loses the exact bytes and would
  // otherwise crash with a native TypeError inside TextDecoder — surface a
  // clear, catchable SignatureVerificationError instead.
  if (typeof payload !== "string" && !(payload instanceof Uint8Array)) {
    throw new SignatureVerificationError(
      "Payload must be the raw request body (string or Uint8Array), not a parsed object. " +
      "Read it as text first, e.g. `await request.text()`.",
    );
  }
  if (!sigHeader) {
    throw new SignatureVerificationError("No signature header was present.");
  }
  if (!sigHeader.startsWith("sha256=")) {
    throw new SignatureVerificationError("Signature header is malformed (expected sha256=<hex>).");
  }
  const expected = await computeSignature(payload, secret);
  if (!timingSafeEqual(expected, sigHeader)) {
    throw new SignatureVerificationError("Signature does not match the payload and secret.");
  }
  try {
    return JSON.parse(typeof payload === "string" ? payload : new TextDecoder().decode(payload)) as WebhookPayload;
  } catch {
    throw new SignatureVerificationError("Payload is not valid JSON.");
  }
}

function toHex(bytes: Uint8Array): string {
  let out = "";
  for (const b of bytes) out += b.toString(16).padStart(2, "0");
  return out;
}

/** Constant-time compare for hex strings (length-equalized). */
function timingSafeEqual(a: string, b: string): boolean {
  const maxLen = Math.max(a.length, b.length);
  let diff = a.length ^ b.length;
  for (let i = 0; i < maxLen; i++) {
    diff |= (a.charCodeAt(i) || 0) ^ (b.charCodeAt(i) || 0);
  }
  return diff === 0;
}

/** Case-insensitive header lookup; returns the first value for multi-value headers. */
function headerValue(
  headers: Record<string, string | string[] | undefined>,
  name: string,
): string | null {
  const target = name.toLowerCase();
  for (const key of Object.keys(headers)) {
    if (key.toLowerCase() !== target) continue;
    const raw = headers[key];
    const value = Array.isArray(raw) ? raw[0] : raw;
    return value == null ? null : value;
  }
  return null;
}

/**
 * Read the delivery id from a webhook request (`X-VideoFetch-Delivery`).
 *
 * The value is the event id (`evt_…`) and is stable across every delivery of
 * the same event. Delivery is **at-least-once**: the same event may be sent
 * more than once (retries and manual replays), and the order of events is not
 * guaranteed (use `WebhookDelivery.seq` to order them). De-duplicate on this
 * value — e.g. remember handled ids and make a repeat a no-op — so consumers
 * stay idempotent.
 *
 * The header name is matched case-insensitively. Returns null when absent.
 */
export function getDeliveryId(headers: Record<string, string | string[] | undefined>): string | null {
  return headerValue(headers, "X-VideoFetch-Delivery");
}

/**
 * Read the delivery attempt number from a webhook request (`X-VideoFetch-Attempt`).
 *
 * The first delivery is attempt 1; retries increment it (up to `max_attempts`,
 * currently 3). Combined with {@link getDeliveryId}, use this to observe retry
 * behaviour — the same delivery id arrives more than once under at-least-once
 * semantics. The header name is matched case-insensitively. Returns null when
 * the header is absent or not an integer.
 */
export function getAttemptNumber(headers: Record<string, string | string[] | undefined>): number | null {
  const raw = headerValue(headers, "X-VideoFetch-Attempt");
  if (raw == null || raw.trim() === "") return null;
  const n = Number(raw);
  return Number.isInteger(n) ? n : null;
}

/**
 * Account-level webhook endpoint management.
 *
 * These endpoints are authenticated by API key (no JWT needed), so a backend
 * integration can self-provision callbacks:
 *
 *   const wh = await client.webhooks.create("https://example.com/hook"); // secret shown once
 *   await client.webhooks.list();                                        // secret is masked
 *   await client.webhooks.test(wh.id);                                   // ping + verify
 *   await client.webhooks.delete(wh.id);                                 // 204
 */
export class WebhooksResource {
  constructor(private client: VideoFetch) {}

  /**
   * POST /v1/webhooks — register an endpoint. Returns the FULL plaintext
   * `secret` (this is the only time it is ever returned; store it now).
   * `events` defaults to every event on the server side.
   */
  async create(url: string, events?: WebhookEvent[]): Promise<WebhookEndpoint> {
    const body: Record<string, unknown> = { url };
    if (events && events.length > 0) body.events = events;
    return this.client.request<WebhookEndpoint>("POST", "/v1/webhooks", { json: body });
  }

  /** GET /v1/webhooks — list endpoints; each `secret` is masked. */
  async list(): Promise<WebhookList> {
    return this.client.request<WebhookList>("GET", "/v1/webhooks");
  }

  /** POST /v1/webhooks/{id}/test — send a `webhook.test` ping to the endpoint. */
  async test(id: string): Promise<WebhookTestResult> {
    return this.client.request<WebhookTestResult>(
      "POST", `/v1/webhooks/${encodeURIComponent(id)}/test`,
    );
  }

  /** DELETE /v1/webhooks/{id} — 204 No Content. */
  async delete(id: string): Promise<void> {
    await this.client.request("DELETE", `/v1/webhooks/${encodeURIComponent(id)}`);
  }

  /**
   * GET /v1/webhooks/{endpoint_id}/deliveries — recent delivery history plus
   * endpoint health: `attempts`, `last_status_code`, `next_attempt_at`, the
   * backoff `retry_schedule_seconds` and `consecutive_failures`.
   *
   * `limit` is the page size (the server default applies when omitted). The
   * endpoint must belong to the caller's account.
   */
  async deliveries(endpointId: string, limit?: number): Promise<WebhookDeliveriesResult> {
    return this.client.request<WebhookDeliveriesResult>(
      "GET",
      `/v1/webhooks/${encodeURIComponent(endpointId)}/deliveries`,
      { params: { limit } },
    );
  }

  /**
   * POST /v1/webhooks/deliveries/{event_id}/replay — re-queue one recorded
   * delivery.
   *
   * The replay reuses the original `event_id` and is at-least-once, so a
   * consumer that de-duplicates on `X-VideoFetch-Delivery` treats an already
   * handled event as a no-op.
   */
  async replay(eventId: string): Promise<WebhookReplayResult> {
    return this.client.request<WebhookReplayResult>(
      "POST",
      `/v1/webhooks/deliveries/${encodeURIComponent(eventId)}/replay`,
    );
  }
}
