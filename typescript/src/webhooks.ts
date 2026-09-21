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
}
