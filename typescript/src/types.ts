/** Typed models mirroring the VideoFetch API contract (openapi/openapi.json). */

export type DownloadFormat = "144p" | "240p" | "360p" | "480p" | "720p" | "1080p" | "1440p" | "2160p" | "mp3";
export type DownloadStatus = "queued" | "processing" | "completed" | "failed" | "deleted";
export type DestinationType = "url" | "s3" | "r2" | "gcs" | "s3_compatible";
export type DownloadStrategy = "direct" | "decodo_isp" | "decodo_dc";

export interface TrimSpec {
  /** clip start, seconds (float ok) */
  start?: number | null;
  /** clip end, seconds (float ok); must be > start */
  end?: number | null;
}

export interface DownloadAttempt {
  attempt_no: number;
  strategy: string;
  proxy_host?: string | null;
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
  /** saved connection: {type, id} or inline {type, bucket, access_key_id, ...} */
  destination?: DestinationSpec;
  /** receive download.* events for this job */
  webhook_url?: string;
}

export interface DestinationSpec {
  type: DestinationType;
  id?: string;
  bucket?: string;
  endpoint?: string;
  region?: string;
  path?: string;
  access_key_id?: string;
  secret_access_key?: string;
}

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
  | "download.failed";

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
