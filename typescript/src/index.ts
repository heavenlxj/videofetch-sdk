/**
 * @videofetch/sdk — official VideoFetch TypeScript SDK (zero runtime deps).
 *
 *   import { VideoFetch } from "@videofetch/sdk";
 *
 *   const client = new VideoFetch({ apiKey: "vf_live_sk_..." });
 *   const job = await client.downloads.create({ url, format: "1080p" });
 *   const result = await job.wait();          // polls until terminal
 *   console.log(result.downloadUrl);          // presigned 7-day link
 *
 * Webhooks:
 *   import { constructEvent } from "@videofetch/sdk";
 *   const event = await constructEvent(rawBody, sigHeader, endpointSecret);
 */

export { VideoFetch, DEFAULT_BASE_URL } from "./client";
export type { VideoFetchOptions } from "./client";
export { DownloadJob, DownloadsResource, DEFAULT_JOB_TIMEOUT_MS } from "./downloads";
export { defaultDownloadFileName, sanitizeFileStem } from "./downloads";
export { InfoResource } from "./info";
export { UsageResource } from "./usage";
export {
  VideoFetchError,
  AuthenticationError,
  PermissionDeniedError,
  QuotaExceededError,
  ValidationError,
  NotFoundError,
  RateLimitError,
  ApiError,
  JobFailedError,
} from "./errors";
export {
  computeSignature,
  constructEvent,
  getDeliveryId,
  getAttemptNumber,
  SignatureVerificationError,
  WebhooksResource,
} from "./webhooks";

export * from "./types";
