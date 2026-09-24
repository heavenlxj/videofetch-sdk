/** Typed models mirroring the VideoFetch API contract (openapi/openapi.json). */

export type DownloadFormat = "144p" | "240p" | "360p" | "480p" | "720p" | "1080p" | "1440p" | "2160p" | "mp3";
export type DownloadStatus = "queued" | "processing" | "completed" | "failed" | "deleted";
export type DestinationType = "url" | "s3" | "r2" | "gcs" | "s3_compatible";
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

export interface DownloadCreateParams {
  url: string;
  format?: DownloadFormat;
  /** optional clip window in seconds */
  trim?: TrimSpec;
  /** where the finished file should land — see {@link DestinationSpec}. Omit to let the
   *  platform keep the file and return a presigned `download_url`. */
  destination?: DestinationSpec;
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
 *  repeat) the provider here. Every other field is ignored. */
export interface SavedDestination {
  /** connection id, from `POST /v1/storage` or the Dashboard → Storage page */
  id: string;
  /** optional, and ignored when `id` is given; kept for backwards compatibility */
  type?: DestinationType;
}

/** Inline credentials. `type` is required here: without a concrete provider the server
 *  would fall back to `"url"` and silently ignore the bucket. */
export interface InlineDestination {
  type: Exclude<DestinationType, "url">;
  bucket: string;
  access_key_id: string;
  secret_access_key: string;
  endpoint?: string;
  region?: string;
  /** object key prefix for the connection created from these credentials;
   *  defaults to `youtube/{video_id}/` */
  path?: string;
}

export type DestinationSpec = PlatformDestination | SavedDestination | InlineDestination;

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
  | "balance.low";

/** All events the account-level webhook endpoints can subscribe to. */
export const WEBHOOK_EVENTS: WebhookEvent[] = [
  "download.queued",
  "download.processing",
  "download.completed",
  "download.failed",
  "quota.warning",
  "quota.exceeded",
  "balance.low",
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
