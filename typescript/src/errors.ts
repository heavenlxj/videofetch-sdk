/** Error hierarchy mirroring the server error contract. */

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

/** The download job reached a terminal failed state. Failed jobs are never charged. */
export class JobFailedError extends VideoFetchError {
  jobId: string;
  failedNotCharged = true;

  constructor(jobId: string, errorCode?: string | null, errorMessage?: string | null) {
    super(
      `Download job ${jobId} failed` + (errorCode || errorMessage ? ` [${errorCode ?? ""}]: ${errorMessage ?? ""}` : ""),
      { code: errorCode ?? "job_failed" },
    );
    this.name = "JobFailedError";
    this.jobId = jobId;
  }
}

interface ErrorDetail {
  code?: string; message?: string; msg?: string; param?: string; type?: string;
  remaining_gb?: number; limit?: number; active?: number; scope?: string;
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
    case 422:
      return new ValidationError(message, base);
    case 404:
      return new NotFoundError(message, base);
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
