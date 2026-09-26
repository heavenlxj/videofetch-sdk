/** Error hierarchy mirroring the server error contract. */

import type { Download } from "./types";

export class VideoFetchError extends Error {
  code?: string | null;
  statusCode?: number | null;
  param?: string | null;
  responseBody?: unknown;

  constructor(message: string, opts: {
    code?: string | null; statusCode?: number | null; param?: string | null; responseBody?: unknown;
  } = {}) {
    super(message);
    this.name = "VideoFetchError";
    this.code = opts.code ?? null;
    this.statusCode = opts.statusCode ?? null;
    this.param = opts.param ?? null;
    this.responseBody = opts.responseBody;
  }
}

export class AuthenticationError extends VideoFetchError { name = "AuthenticationError"; }
export class PermissionDeniedError extends VideoFetchError { name = "PermissionDeniedError"; }
export class ValidationError extends VideoFetchError { name = "ValidationError"; }
export class NotFoundError extends VideoFetchError { name = "NotFoundError"; }
export class ApiError extends VideoFetchError { name = "ApiError"; }

/**
 * 422 — a storage destination was rejected when the job was created.
 * code ∈ storage_not_found | storage_config_invalid | storage_endpoint_blocked | storage_unreachable.
 * `param` names the field (e.g. `destination.endpoint`); `hint` says how to fix it.
 */
export class StorageError extends ValidationError {
  name = "StorageError";
  hint: string | null = null;
}

/** 409 — code ∈ storage_in_use (delete with `{ force: true }`) | not_redeliverable. */
export class ConflictError extends VideoFetchError { name = "ConflictError"; }

/**
 * 429 — the request was throttled. Typically an account concurrency guard:
 *
 *   code:  concurrency_limit_exceeded | queue_limit_exceeded | platform_at_capacity
 *   limit: the cap that was hit   active: in-flight jobs at the time
 *   scope: "account" | "platform"
 *   retryAfter: seconds, parsed from the `Retry-After` response header (if present)
 *
 * Also surfaced from the `X-Concurrency-Limit` / `X-Concurrency-Active` headers.
 */
export class RateLimitError extends VideoFetchError {
  name = "RateLimitError";
  limit: number | null = null;
  active: number | null = null;
  scope: string | null = null;
  retryAfter: number | null = null;
}

/**
 * 402 — monthly quota exhausted (or the account has no credit balance left for
 * overage). `remainingGb` mirrors the `remaining_gb` field the server returns.
 */
export class QuotaExceededError extends VideoFetchError {
  name = "QuotaExceededError";
  remainingGb: number | null = null;
}

/**
 * The download job reached a terminal failed state. Failed jobs are never charged.
 * `stage` / `retryable` / `hint` / `providerCode` come from `Download.error`.
 */
export class JobFailedError extends VideoFetchError {
  jobId: string;
  failedNotCharged = true;
  download: Download | null;
  stage: string | null;
  retryable: boolean | null;
  hint: string | null;
  providerCode: string | null;

  constructor(jobId: string, errorCode?: string | null, errorMessage?: string | null, download?: Download | null) {
    super(
      `Download job ${jobId} failed` + (errorCode || errorMessage ? ` [${errorCode ?? ""}]: ${errorMessage ?? ""}` : ""),
      { code: errorCode ?? "job_failed" },
    );
    this.name = "JobFailedError";
    this.jobId = jobId;
    this.download = download ?? null;
    const err = download?.error;
    this.stage = err?.stage ?? null;
    this.retryable = err?.retryable ?? null;
    this.hint = err?.hint ?? null;
    this.providerCode = err?.provider_code ?? null;
  }
}

/**
 * The file was downloaded but could not be written to your storage (`stage: "delivery"`).
 * When `redeliverable` is true the file is held until `holdExpiresAt`: fix the bucket and call
 * `client.downloads.redeliver(jobId)` — nothing is downloaded or charged again.
 */
export class DeliveryFailedError extends JobFailedError {
  get redeliverable(): boolean { return !!this.download?.delivery?.redeliverable; }
  get holdExpiresAt(): string | null { return this.download?.delivery?.hold_expires_at ?? null; }

  constructor(jobId: string, errorCode?: string | null, errorMessage?: string | null, download?: Download | null) {
    super(jobId, errorCode, errorMessage, download);
    this.name = "DeliveryFailedError";
  }
}

/** The right {@link JobFailedError} subclass for a failed download. */
export function jobFailedError(dl: Download): JobFailedError {
  const Cls = dl.error?.stage === "delivery" ? DeliveryFailedError : JobFailedError;
  return new Cls(dl.id, dl.error_code ?? null, dl.error_message ?? null, dl);
}

interface ErrorDetail {
  code?: string; message?: string; msg?: string; param?: string; type?: string;
  remaining_gb?: number; limit?: number; active?: number; scope?: string; hint?: string;
}

function numHeader(headers: Headers | null | undefined, name: string): number | null {
  const raw = headers?.get(name);
  if (raw == null) return null;
  const n = Number(raw);
  return Number.isFinite(n) ? n : null;
}

/**
 * Map an HTTP status + parsed body (and optional response headers) to the typed
 * error hierarchy. `headers` lets us surface retry/concurrency semantics for 429.
 */
export function mapError(
  statusCode: number,
  body: unknown,
  headers?: Headers | null,
  fallback = "Request failed",
): VideoFetchError {
  let code: string | undefined;
  let message = fallback;
  let param: string | undefined;
  let detailObj: ErrorDetail | undefined;
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "object" && detail !== null) {
    const d = detail as ErrorDetail;
    detailObj = d;
    code = d.code ?? d.type;
    message = d.message ?? d.msg ?? fallback;
    param = d.param;
  } else if (typeof detail === "string") {
    message = detail;
  }

  const base = { code, statusCode, param, responseBody: body };
  switch (statusCode) {
    case 401:
      return new AuthenticationError(message, base);
    case 403:
      // e.g. code "account_suspended" — surfaced as a PermissionDeniedError,
      // inspect `.code` to distinguish suspension from a plain permission error.
      return new PermissionDeniedError(message, base);
    case 402: {
      const err = new QuotaExceededError(message, base);
      const remaining = detailObj?.remaining_gb ?? (body as { remaining_gb?: number })?.remaining_gb;
      err.remainingGb = typeof remaining === "number" ? remaining : null;
      return err;
    }
    case 400:
    case 422: {
      if (code?.startsWith("storage_")) {
        const err = new StorageError(message, base);
        err.hint = detailObj?.hint ?? null;
        return err;
      }
      return new ValidationError(message, base);
    }
    case 404:
      return new NotFoundError(message, base);
    case 409:
      return new ConflictError(message, base);
    case 429: {
      const err = new RateLimitError(message, base);
      err.limit = detailObj?.limit ?? numHeader(headers, "X-Concurrency-Limit");
      err.active = detailObj?.active ?? numHeader(headers, "X-Concurrency-Active");
      err.scope = detailObj?.scope ?? null;
      err.retryAfter = numHeader(headers, "Retry-After");
      return err;
    }
    default:
      return new ApiError(message, base);
  }
}
