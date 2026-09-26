/**
 * Core HTTP client with retry/backoff, error mapping and resource wiring.
 * Zero runtime dependencies — uses the global fetch (Node >= 18, browsers, edge).
 */

import { mapError, VideoFetchError } from "./errors";
import { DownloadsResource } from "./downloads";
import { InfoResource } from "./info";
import { StorageResource } from "./storage";
import { UsageResource } from "./usage";
import { WebhooksResource } from "./webhooks";

export const DEFAULT_BASE_URL =
  (typeof process !== "undefined" && process.env?.VIDEOFETCH_BASE_URL) || "https://api.vidfetch.dev";
export const DEFAULT_MAX_RETRIES = 2;
export const DEFAULT_TIMEOUT_MS = 30_000;

export interface VideoFetchOptions {
  apiKey?: string;
  baseUrl?: string;
  /** per-request timeout in ms */
  timeoutMs?: number;
  /** automatic retries on 429/5xx/network errors */
  maxRetries?: number;
  /** custom fetch impl (testing / edge runtimes) */
  fetch?: typeof fetch;
  headers?: Record<string, string>;
}

function fibonacci(n: number): number {
  let a = 2, b = 3;
  for (let i = 0; i < n; i++) { const t = a + b; a = b; b = t; }
  return Math.min(a, 30);
}

function jittered(sec: number): number {
  return sec * (0.8 + Math.random() * 0.4) * 1000;
}

export class VideoFetch {
  readonly apiKey: string;
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly maxRetries: number;
  private readonly _fetch: typeof fetch;
  private readonly _extraHeaders: Record<string, string>;

  downloads: DownloadsResource;
  info: InfoResource;
  usage: UsageResource;
  webhooks: WebhooksResource;
  storage: StorageResource;

  constructor(options: VideoFetchOptions = {}) {
    this.apiKey = options.apiKey ?? (typeof process !== "undefined" ? process.env?.VIDEOFETCH_API_KEY : undefined) ?? "";
    if (!this.apiKey) {
      throw new Error("No API key provided. Pass apiKey or set VIDEOFETCH_API_KEY.");
    }
    this.baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/+$/, "");
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = options.maxRetries ?? DEFAULT_MAX_RETRIES;
    this._fetch = options.fetch ?? globalThis.fetch;
    this._extraHeaders = options.headers ?? {};

    this.downloads = new DownloadsResource(this);
    this.info = new InfoResource(this);
    this.usage = new UsageResource(this);
    this.webhooks = new WebhooksResource(this);
    this.storage = new StorageResource(this);
  }

  /**
   * Fetch a self-authorising absolute URL (e.g. a time-limited download link).
   * Deliberately sends **no** Authorization header — an API key must never be
   * forwarded to a storage host. Uses the same injected `fetch` as `request()`.
   */
  fetchPresigned(url: string): Promise<Response> {
    return this._fetch(url, { method: "GET" });
  }

  async request<T = unknown>(
    method: string,
    path: string,
    opts: { json?: unknown; params?: Record<string, unknown>; headers?: Record<string, string> } = {},
  ): Promise<T> {
    let url = path.startsWith("http") ? path : `${this.baseUrl}${path}`;
    if (opts.params) {
      const qs = new URLSearchParams(
        Object.entries(opts.params).filter(([, v]) => v !== undefined && v !== null)
          .map(([k, v]) => [k, String(v)]),
      ).toString();
      if (qs) url += (url.includes("?") ? "&" : "?") + qs;
    }

    const headers: Record<string, string> = {
      Authorization: `Bearer ${this.apiKey}`,
      "Content-Type": "application/json",
      ...this._extraHeaders,
      ...opts.headers,
    };

    let lastError: unknown;
    for (let attempt = 0; attempt <= this.maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), this.timeoutMs);
        let response: Response;
        try {
          response = await this._fetch(url, {
            method,
            headers,
            body: opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
            signal: controller.signal,
          });
        } finally {
          clearTimeout(timer);
        }

        if (response.status === 429 || response.status >= 500) {
          if (attempt < this.maxRetries) {
            const retryAfter = response.headers.get("Retry-After");
            const delay = retryAfter && /^\d+$/.test(retryAfter)
              ? Number(retryAfter) * 1000
              : jittered(fibonacci(attempt));
            await new Promise((r) => setTimeout(r, Math.min(delay, 30_000)));
            continue;
          }
        }
        if (!response.ok) {
          const body = await parseBody(response);
          throw mapError(response.status, body, response.headers);
        }
        if (response.status === 204) return undefined as T;
        return (await parseBody(response)) as T;
      } catch (e) {
        if (e instanceof VideoFetchError) throw e;
        if (attempt < this.maxRetries) {
          lastError = e;
          await new Promise((r) => setTimeout(r, jittered(fibonacci(attempt))));
          continue;
        }
        throw new VideoFetchError(`Network error calling ${method} ${path}: ${(e as Error).message}`, {
          statusCode: null,
        });
      }
    }
    throw lastError instanceof Error
      ? new VideoFetchError(lastError.message)
      : new VideoFetchError("Request failed");
  }
}

async function parseBody(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return undefined;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}
