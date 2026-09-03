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
export class QuotaExceededError extends VideoFetchError { name = "QuotaExceededError"; }
export class ValidationError extends VideoFetchError { name = "ValidationError"; }
export class NotFoundError extends VideoFetchError { name = "NotFoundError"; }
export class RateLimitError extends VideoFetchError { name = "RateLimitError"; }
export class ApiError extends VideoFetchError { name = "ApiError"; }

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

interface ErrorDetail { code?: string; message?: string; msg?: string; param?: string; type?: string; }

export function mapError(statusCode: number, body: unknown, fallback = "Request failed"): VideoFetchError {
  let code: string | undefined;
  let message = fallback;
  let param: string | undefined;
  const detail = (body as { detail?: unknown })?.detail;
  if (typeof detail === "object" && detail !== null) {
    const d = detail as ErrorDetail;
    code = d.code ?? d.type;
    message = d.message ?? d.msg ?? fallback;
    param = d.param;
  } else if (typeof detail === "string") {
    message = detail;
  }

  const base = { code, statusCode, param, responseBody: body };
  switch (statusCode) {
    case 401: return new AuthenticationError(message, base);
    case 403: return new PermissionDeniedError(message, base);
    case 402: return new QuotaExceededError(message, base);
    case 400:
    case 422: return new ValidationError(message, base);
    case 404: return new NotFoundError(message, base);
    case 429: return new RateLimitError(message, base);
    default: return new ApiError(message, base);
  }
}
