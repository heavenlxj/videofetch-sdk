/** Typed models mirroring the VideoFetch API contract (openapi/openapi.json). */

export type DownloadFormat = "144p" | "240p" | "360p" | "480p" | "720p" | "1080p" | "1440p" | "2160p" | "mp3";
export type DownloadStatus = "queued" | "processing" | "completed" | "failed" | "deleted";
export type DestinationType = "url" | "s3" | "r2" | "gcs" | "s3_compatible";
export type StorageProvider = Exclude<DestinationType, "url">;
export type DownloadStrategy = "direct" | "relay" | "relay_secondary";

export interface TrimSpec {
  /** clip start, seconds (float ok) */
  start?: number | null;
  /** clip end, seconds (float ok); must be > start */
  end?: number | null;
}

export interface DownloadAttempt {
  attempt_no: number;
  strategy: string;
  /** Neutral relay label ("relay") when the attempt used one, otherwise null. */
  egress?: string | null;
  result: string;
  error_code?: string | null;
  error_message?: string | null;
  latency_ms?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
}

/** A download job (dl_xxx). Mirrors GET /v1/downloads/{id}. */
export interface Download {
  id: string;
  status: DownloadStatus;
  url: string;
  format: DownloadFormat;
  progress?: number;
  /** position in the queue while status=queued, null otherwise */
  queue_position?: number | null;
  /** number of jobs ahead of this one while status=queued, null otherwise */
  ahead_of_you?: number | null;
  /** rough wait estimate in seconds while status=queued, null otherwise */
  estimated_wait_seconds?: number | null;
  title?: string | null;
  video_id?: string | null;
  channel?: string | null;
  upload_date?: string | null;
  thumbnail?: string | null;
  duration_seconds?: number | null;
  size_bytes?: number | null;
  trim?: TrimSpec | null;
  destination_type?: DestinationType | null;
  /** st_… saved connection this job delivers to (null for platform / one-off inline credentials) */
  destination_id?: string | null;
  /** where the file went — see {@link Delivery} */
  delivery?: Delivery | null;
  /** structured failure reason when status=failed */
  error?: DownloadErrorInfo | null;
  /** presigned 7-day link (url destination only) */
  download_url?: string | null;
  download_url_expires_at?: string | null;
  /** user://<bucket>/<key> when a destination bucket was used */
  storage_key?: string | null;
  processing_time_ms?: number | null;
  cost_usd?: number;
  attempts?: number;
  strategy?: DownloadStrategy | null;
  error_code?: string | null;
  error_message?: string | null;
  created_at?: string | null;
  completed_at?: string | null;
  estimated_bytes?: number | null;
  attempt_details?: DownloadAttempt[];
}

/**
 * Where the finished file went.
 * `type: "url"` — the platform keeps it and `download_url` is set.
 * `type: "storage"` — written to your bucket (`uri` / `bucket` / `key`).
 * `status: "failed"` with `redeliverable: true` — the file is held until `hold_expires_at`;
 * `client.downloads.redeliver(id)` retries without re-downloading.
 */
export interface Delivery {
  type: "url" | "storage";
  status: "pending" | "delivered" | "failed";
  destination_id?: string | null;
  /** inline credentials used for this job only */
  ephemeral?: boolean;
  provider?: string | null;
  bucket?: string | null;
  key?: string | null;
  /** s3:// · gs:// · r2:// */
  uri?: string | null;
  etag?: string | null;
  size_bytes?: number | null;
  /** upload attempts in the last delivery run */
  attempts?: number | null;
  delivered_at?: string | null;
  redeliverable?: boolean;
  hold_expires_at?: string | null;
}

/** Structured failure reason (`Download.error`). */
export interface DownloadErrorInfo {
  code: string;
  message?: string | null;
  /** fetch | process | billing | delivery */
  stage?: "fetch" | "process" | "billing" | "delivery" | null;
  retryable?: boolean | null;
  /** raw storage provider error, e.g. `AccessDenied` */
  provider_code?: string | null;
  hint?: string | null;
}

export interface DownloadCreateParams {
  url: string;
  format?: DownloadFormat;
  /** optional clip window in seconds */
  trim?: TrimSpec;
  /** where the finished file should land — see {@link DestinationInput}. Omit to use the
   *  account's default storage connection (or the platform when none is set). */
  destination?: DestinationInput;
  /** receive download.* events for this job */
  webhook_url?: string;
}

/** Platform-hosted delivery: the platform keeps the file and returns a presigned
 *  `download_url`. Equivalent to omitting `destination` entirely. */
export interface PlatformDestination {
  type: "url";
}

/** A saved storage connection. Only `id` is required — the server reads the provider,
 *  bucket and credentials from the connection itself, so you do not need to know (or
 *  repeat) the provider here. */
export interface SavedDestination {
  /** `st_…` id, from `client.storage.create()` or the Dashboard → Storage page */
  id: string;
  /** optional, and ignored when `id` is given; kept for backwards compatibility */
  type?: DestinationType;
  /** object key prefix for this job only, e.g. `clips/{video_id}/` */
  path?: string;
  /** full object key for this job only, e.g. `clips/{video_id}.{ext}` */
  key?: string;
}

/** Inline credentials, used for this job only unless `save: true`. `type` is required:
 *  without a concrete provider the server would fall back to `"url"`. */
export interface InlineDestination {
  type: StorageProvider;
  bucket: string;
  access_key_id: string;
  secret_access_key: string;
  /** required for r2 and s3_compatible */
  endpoint?: string;
  region?: string;
  /** object key prefix; defaults to `youtube/{video_id}/` */
  path?: string;
  /** full object key template (overrides `path`); also accepts `{ext}` */
  key?: string;
  /** keep these credentials as a saved connection (reused if an identical one exists) */
  save?: boolean;
  /** name of the saved connection when `save` is true */
  name?: string;
}

export type DestinationSpec = PlatformDestination | SavedDestination | InlineDestination;

/** `"st_…"` (saved connection) or `"url"` (force platform delivery). */
export type DestinationShorthand = "url" | `st_${string}` | (string & {});

/** Everything `destination` accepts on create / redeliver. */
export type DestinationInput = DestinationShorthand | DestinationSpec;

export interface DownloadList {
  items: Download[];
  total: number;
  has_more: boolean;
}

export interface FormatInfo {
  quality: string;
  size?: number | null;
  container?: string;
  note?: string | null;
}

/** POST /v1/info result (free metadata lookup). */
export interface VideoInfo {
  id?: string | null;
  url: string;
  title?: string | null;
  duration?: number | null;
  thumbnail?: string | null;
  channel?: string | null;
  upload_date?: string | null;
  view_count?: number | null;
  formats: FormatInfo[];
}

export type WebhookEvent =
  | "download.queued"
  | "download.processing"
  | "download.completed"
  | "download.failed"
  | "quota.warning"
  | "quota.exceeded"
  | "balance.low"
  | "storage.connection_failed";

/** All events the account-level webhook endpoints can subscribe to. */
export const WEBHOOK_EVENTS: WebhookEvent[] = [
  "download.queued",
  "download.processing",
  "download.completed",
  "download.failed",
  "quota.warning",
  "quota.exceeded",
  "balance.low",
  "storage.connection_failed",
];

/** A registered account-level webhook endpoint (GET/POST /v1/webhooks). */
export interface WebhookEndpoint {
  id: string;
  url: string;
  /** Full plaintext secret on create only; masked (`whsec_…****`) on list. */
  secret: string;
  events: WebhookEvent[];
  active: boolean;
  last_delivery_at?: string | null;
  last_status?: number | null;
  failure_count?: number;
  created_at?: string | null;
}

export interface WebhookList {
  items: WebhookEndpoint[];
}

/** Result of POST /v1/webhooks/{id}/test. */
export interface WebhookTestResult {
  delivered: boolean;
  url: string;
  last_status?: number | null;
  signature_header: string;
  signature_format: string;
}

export type WebhookDeliveryStatus = "pending" | "succeeded" | "dead";

/** Aggregate counters returned alongside a deliveries listing. */
export interface WebhookDeliveryHealth {
  total: number;
  succeeded: number;
  dead: number;
  pending: number;
  /** succeeded / total as a 0..1 ratio, or null when no deliveries were recorded */
  success_rate: number | null;
}

/** One recorded webhook delivery attempt group for an endpoint. */
export interface WebhookDelivery {
  event_id: string;
  event: WebhookEvent;
  /** monotonic per-endpoint sequence number — deliveries are NOT guaranteed to arrive in order */
  seq: number;
  status: WebhookDeliveryStatus;
  attempts: number;
  max_attempts: number;
  last_status_code?: number | null;
  last_error?: string | null;
  next_attempt_at?: string | null;
  created_at?: string | null;
  delivered_at?: string | null;
  download_id?: string | null;
}

/** Result of GET /v1/webhooks/{endpoint_id}/deliveries. */
export interface WebhookDeliveriesResult {
  endpoint_id: string;
  active: boolean;
  auto_disabled_at?: string | null;
  consecutive_failures: number;
  max_attempts: number;
  /** comma-separated backoff schedule in seconds, e.g. "30,300" */
  retry_schedule_seconds: string;
  health: WebhookDeliveryHealth;
  items: WebhookDelivery[];
}

/** Result of POST /v1/webhooks/deliveries/{event_id}/replay. */
export interface WebhookReplayResult {
  queued: boolean;
  event_id: string;
}

export interface WebhookPayload {
  event: WebhookEvent;
  id: string;
  status: DownloadStatus;
  format?: DownloadFormat;
  file_size?: number | null;
  duration?: number | null;
  download_url?: string | null;
  destination?: string;
  destination_id?: string | null;
  storage_key?: string | null;
  delivery?: Delivery | null;
  error?: DownloadErrorInfo | null;
  cost_usd?: number;
  created_at?: string | null;
  completed_at?: string | null;
}

export const SUPPORTED_FORMATS: DownloadFormat[] = [
  "144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "mp3",
];

export function isTerminal(status: string): boolean {
  return status === "completed" || status === "failed" || status === "deleted";
}

// ────────────────────────── Usage / alerts (v0.2.0) ──────────────────────────

export type AlertLevel = "ok" | "warning" | "critical" | "exceeded";

/** GET /v1/usage — account-level quota snapshot + concurrency + alert level. */
export interface Usage {
  /** null when the account-level figures came from a dashboard session rather than an API key */
  key_id: string | null;
  plan: string;
  quota_gb: number | null;
  /** account-level usage for the current month */
  used_bytes: number;
  /** account-level usage for the current month */
  used_gb: number;
  /** this API key's own usage for the current month */
  key_used_bytes?: number;
  key_used_gb?: number;
  remaining_gb: number | null;
  /** quota left on the subscription itself, excluding any top-up packs */
  plan_remaining_gb: number;
  /** total GB bought as top-up packs for the current period */
  pack_gb: number;
  /** GB left across all top-up packs for the current period */
  pack_remaining_gb: number;
  /** start of the current billing period (ISO 8601); null on legacy accounts */
  period_start: string | null;
  /** end of the current billing period (ISO 8601); null on legacy accounts */
  period_end: string | null;
  payg_balance_cents: number;
  payg_rate_usd_per_gb: number;
  /** month-to-date bytes for the whole account (matches /v1/stats/overview) */
  account_used_bytes_month: number;
  account_used_gb_month: number;
  used_pct: number;
  month: string;
  active_jobs: number;
  concurrency_limit: number;
  alert_level: AlertLevel;
  alert_message: string;
}

/** Live alert state returned inside GET /v1/usage/alerts. */
export interface UsageAlertState {
  level: AlertLevel;
  pct_used: number;
  thresholds: number[];
  crossed: number[];
  next_threshold_pct: number | null;
  quota_gb: number;
  used_gb_month: number;
  remaining_gb: number | null;
  month: string;
  plan: string;
  payg_balance_cents: number;
  balance_low: boolean;
  balance_depleted: boolean;
  balance_hint: string | null;
  message: string;
  /** `topup` | `upgrade` | null — drives the dashboard call-to-action button */
  action: string | null;
}

/** A fired alert record (deduped: one per threshold per month). */
export interface UsageAlertEvent {
  id: string;
  kind: string;
  level: string;
  threshold: number;
  pct_used: number;
  used_gb: number;
  quota_gb: number;
  balance_cents: number;
  message: string;
  delivered: boolean;
  created_at: string;
}

/** GET /v1/usage/alerts. */
export interface UsageAlerts {
  state: UsageAlertState;
  fired: UsageAlertEvent[];
  /** e.g. [80, 95, 100] */
  thresholds: number[];
  /** top-up presets in USD, e.g. [10, 25, 50, 100] */
  topup_amounts: number[];
}

// ────────────────────────── Storage connections (v0.5.0) ─────────────────────

/** A saved storage connection (GET /v1/storage). Pass `id` as `destination`. */
export interface StorageConnection {
  /** `st_…` */
  id: string;
  name: string;
  provider: StorageProvider;
  bucket: string;
  path_prefix: string;
  endpoint?: string | null;
  region?: string | null;
  /** e.g. `AKIA••••MPLE` — the secret is never returned */
  access_key_masked?: string | null;
  is_default: boolean;
  /** `failing` after a permanent delivery error; reset by a successful delivery/test */
  status: "active" | "failing";
  last_error?: { code: string; message?: string | null; at?: string | null } | null;
  last_used_at?: string | null;
  deliveries_count: number;
  last_tested_at?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface StorageConnectionList {
  items: StorageConnection[];
}

export interface StorageCreateParams {
  provider: StorageProvider;
  bucket: string;
  access_key_id: string;
  secret_access_key: string;
  name?: string;
  /** required for r2 and s3_compatible */
  endpoint?: string;
  region?: string;
  /** default `youtube/{video_id}/` */
  path_prefix?: string;
  /** jobs without a destination go here */
  is_default?: boolean;
}

/** Passing both keys rotates credentials and resets `status`. */
export type StorageUpdateParams = Partial<Omit<StorageCreateParams, "provider" | "bucket">>;

export type StorageTestParams = Omit<StorageCreateParams, "name" | "is_default">;

export interface StorageTestStep {
  name: "connect" | "write" | "cleanup";
  ok: boolean;
  /** cleanup failures are warnings: delivery only needs PutObject */
  warning?: boolean;
  code?: string | null;
  message?: string | null;
}

/** POST /v1/storage/test — a failed probe is `ok: false`, not a thrown error. */
export interface StorageTestResult {
  ok: boolean;
  /** `storage_*` when ok is false */
  code?: string | null;
  message: string;
  hint?: string | null;
  provider_code?: string | null;
  probe_key?: string | null;
  steps: StorageTestStep[];
}
