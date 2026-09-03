/**
 * Downloads resource: create / retrieve / list / cancel + Job.wait() polling.
 *
 * Three layers (see docs/SDK_RELEASE_GUIDE.md):
 *   L1  const job = await client.downloads.create({url, format})   // POST only
 *   L2  const result = await job.wait({timeoutMs})                  // poll with backoff
 *   L3  const result = await client.downloads.createAndWait({...})
 */

import { VideoFetch } from "./client";
import { JobFailedError, VideoFetchError } from "./errors";
import {
  Download, DownloadCreateParams, DownloadFormat, DownloadList, isTerminal,
} from "./types";

export const DEFAULT_JOB_TIMEOUT_MS = 120_000;

function pollDelayMs(attempt: number): number {
  // 2s → 3s → 5s → 8s → 13s, cap 30s, with jitter
  const fib = [2, 3, 5, 8, 13, 21, 30];
  const base = fib[Math.min(attempt, fib.length - 1)];
  return base * 1000 * (0.8 + Math.random() * 0.4);
}

export class DownloadJob {
  private _download: Download;

  constructor(
    private client: VideoFetch,
    initial: Download,
  ) {
    this._download = initial;
  }

  get id(): string { return this._download.id; }
  get status(): Download["status"] { return this._download.status; }
  get download(): Download { return this._download; }

  /** Fetch the latest state from the API. */
  async refresh(): Promise<Download> {
    this._download = await this.client.downloads.retrieve(this.id);
    return this._download;
  }

  /**
   * Poll until terminal (completed / failed / deleted).
   *
   * - Network errors never abort; we keep polling until timeout.
   * - A failed job throws JobFailedError (failed downloads are never charged).
   * - timeoutMs: 0/undefined = wait forever. Cancelling locally does NOT cancel
   *   the server-side job — call client.downloads.cancel(id) for that.
   * - Serverless warning: do not call wait() inside a Vercel/CF/Lambda function.
   */
  async wait(opts: { timeoutMs?: number; pollIntervalMs?: number } = {}): Promise<Download> {
    const timeoutMs = opts.timeoutMs ?? DEFAULT_JOB_TIMEOUT_MS;
    const baseInterval = opts.pollIntervalMs ?? 2000;
    const deadline = timeoutMs > 0 ? Date.now() + timeoutMs : undefined;

    if (isTerminal(this._download.status)) {
      return raiseIfFailed(this._download);
    }

    let attempt = 0;
    for (;;) {
      if (deadline !== undefined) {
        const remaining = deadline - Date.now();
        if (remaining <= 0) {
          throw new VideoFetchError(
            `Timed out after ${timeoutMs}ms waiting for job ${this.id}. The job is still running server-side — retrieve() it later.`,
            { code: "job_timeout" },
          );
        }
        await sleep(Math.min(baseInterval, remaining));
      } else {
        await sleep(baseInterval);
      }
      try {
        this._download = await this.client.downloads.retrieve(this.id);
      } catch (e) {
        if (e instanceof VideoFetchError && deadline !== undefined && Date.now() > deadline) throw e;
        attempt += 1;
        await sleep(pollDelayMs(attempt));
        continue;
      }
      if (isTerminal(this._download.status)) {
        return raiseIfFailed(this._download);
      }
      attempt += 1;
    }
  }
}

function raiseIfFailed(dl: Download): Download {
  if (dl.status === "failed") {
    throw new JobFailedError(dl.id, dl.error_code ?? null, dl.error_message ?? null);
  }
  return dl;
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export class DownloadsResource {
  constructor(private client: VideoFetch) {}

  /** POST /v1/downloads — returns immediately with a queued job handle. */
  async create(params: DownloadCreateParams): Promise<DownloadJob> {
    const body: Record<string, unknown> = {
      url: params.url,
      format: (params.format ?? "720p") as DownloadFormat,
    };
    if (params.trim) body.trim = params.trim;
    if (params.destination) body.destination = params.destination;
    if (params.webhook_url) body.webhook_url = params.webhook_url;

    const data = await this.client.request<Download>("POST", "/v1/downloads", { json: body });
    return new DownloadJob(this.client, data);
  }

  /** GET /v1/downloads/{id} */
  async retrieve(id: string): Promise<Download> {
    return this.client.request<Download>("GET", `/v1/downloads/${encodeURIComponent(id)}`);
  }

  /** GET /v1/downloads */
  async list(opts: { status?: string; q?: string; limit?: number; offset?: number } = {}): Promise<DownloadList> {
    return this.client.request<DownloadList>("GET", "/v1/downloads", {
      params: { status: opts.status, q: opts.q, limit: opts.limit ?? 20, offset: opts.offset ?? 0 },
    });
  }

  /** DELETE /v1/downloads/{id} — cancel a queued/processing job (or delete a finished one). */
  async cancel(id: string): Promise<void> {
    await this.client.request("DELETE", `/v1/downloads/${encodeURIComponent(id)}`);
  }

  /** L3 convenience: create + wait for the terminal state. */
  async createAndWait(params: DownloadCreateParams, opts: { timeoutMs?: number } = {}): Promise<Download> {
    const job = await this.create(params);
    return job.wait(opts);
  }
}
