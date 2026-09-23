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

/** Upper bound for the derived file-name stem (keeps paths portable). */
const MAX_FILE_STEM_LENGTH = 80;

type FsPromises = typeof import("node:fs/promises");
type PathModule = typeof import("node:path");

/**
 * Sanitize a title/id into a safe file-name stem: drops path separators and
 * control characters and trims surrounding whitespace/dots, capped in length.
 */
export function sanitizeFileStem(raw: string): string {
  return raw
    .replace(/[/\\]/g, "")
    // eslint-disable-next-line no-control-regex
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .replace(/^[\s.]+/, "")
    .slice(0, MAX_FILE_STEM_LENGTH)
    .replace(/[\s.]+$/, "");
}

/** Default file name for a finished job: `<sanitized title|id>.<mp3|mp4>`. */
export function defaultDownloadFileName(
  dl: Pick<Download, "id" | "title" | "format">,
): string {
  const ext = dl.format === "mp3" ? "mp3" : "mp4";
  const stem = sanitizeFileStem(dl.title?.trim() || dl.id) || sanitizeFileStem(dl.id) || "download";
  return `${stem}.${ext}`;
}

function isNodeRuntime(): boolean {
  return typeof process !== "undefined" && !!process.versions?.node;
}

async function isDirectory(fs: FsPromises, target: string): Promise<boolean> {
  try {
    return (await fs.stat(target)).isDirectory();
  } catch {
    return false;
  }
}

/**
 * Resolve where to write. No path → current directory. A path ending in a
 * separator, or an existing directory, gets the derived name inside it.
 */
async function resolveTargetPath(
  pathMod: PathModule,
  fs: FsPromises,
  dl: Download,
  path?: string,
): Promise<string> {
  const fileName = defaultDownloadFileName(dl);
  if (!path) return pathMod.resolve(process.cwd(), fileName);
  const endsWithSeparator = path.endsWith("/") || path.endsWith("\\") || path.endsWith(pathMod.sep);
  if (endsWithSeparator || (await isDirectory(fs, path))) {
    return pathMod.resolve(path, fileName);
  }
  return pathMod.resolve(path);
}

async function writeChunk(handle: import("node:fs/promises").FileHandle, chunk: Uint8Array): Promise<void> {
  let offset = 0;
  while (offset < chunk.byteLength) {
    const { bytesWritten } = await handle.write(chunk, offset, chunk.byteLength - offset);
    offset += bytesWritten;
  }
}

/** Stream a response body into `target` in chunks (never buffering the whole file). */
async function writeResponseToFile(response: Response, target: string, fs: FsPromises): Promise<number> {
  const handle = await fs.open(target, "w");
  let written = 0;
  try {
    const body = response.body;
    if (!body) {
      const bytes = new Uint8Array(await response.arrayBuffer());
      await writeChunk(handle, bytes);
      return bytes.byteLength;
    }
    const reader = body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (value && value.byteLength) {
        await writeChunk(handle, value);
        written += value.byteLength;
      }
    }
    return written;
  } finally {
    await handle.close();
  }
}

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

  /**
   * GET the job and assert it is downloadable: `completed` + a `download_url`.
   * Throws a typed {@link VideoFetchError} otherwise.
   */
  private async requireDownloadable(id: string): Promise<Download> {
    const dl = await this.retrieve(id);
    if (dl.status !== "completed") {
      throw new VideoFetchError(
        `Download job ${id} is not ready: status is "${dl.status}". ` +
          "Wait for it to reach \"completed\" (e.g. job.wait()) before downloading.",
        { code: "job_not_completed" },
      );
    }
    if (!dl.download_url) {
      throw new VideoFetchError(
        `Download job ${id} has no download_url (destination_type="${dl.destination_type ?? "unknown"}"). ` +
          "This method only serves jobs with a \"url\" destination — use storage_key for bucket destinations.",
        { code: "missing_download_url" },
      );
    }
    return dl;
  }

  /**
   * Open the self-authorising download link (no API key is sent).
   * A 403 means the link expired: re-GET the job — the server re-signs it — and
   * retry once. Any remaining failure throws.
   */
  private async openDownloadStream(id: string, url: string): Promise<Response> {
    let response = await this.client.fetchPresigned(url);
    if (response.status === 403) {
      const refreshed = await this.retrieve(id);
      if (!refreshed.download_url) {
        throw new VideoFetchError(
          `The download link for job ${id} expired and could not be refreshed (no download_url).`,
          { code: "missing_download_url" },
        );
      }
      response = await this.client.fetchPresigned(refreshed.download_url);
    }
    if (!response.ok) {
      throw new VideoFetchError(
        `Failed to fetch the download link for job ${id}: HTTP ${response.status}.`,
        { statusCode: response.status, code: "download_fetch_failed" },
      );
    }
    return response;
  }

  /**
   * Download the finished file into a `Uint8Array`. Works in every runtime
   * (Node, browsers, edge). In the browser persist it yourself, e.g.
   * `URL.createObjectURL(new Blob([bytes]))`.
   */
  async downloadBytes(id: string): Promise<Uint8Array> {
    const dl = await this.requireDownloadable(id);
    const response = await this.openDownloadStream(id, dl.download_url as string);
    return new Uint8Array(await response.arrayBuffer());
  }

  /**
   * Stream the finished file to a local file (Node.js only) and return the
   * absolute path written. `path` may be a file or a directory; when omitted
   * the file lands in the current directory as `<sanitized title|id>.<ext>`.
   *
   * Browsers have no filesystem — this throws; use {@link downloadBytes} instead.
   */
  async downloadTo(id: string, path?: string): Promise<string> {
    if (!isNodeRuntime()) {
      throw new VideoFetchError(
        "downloadTo() needs a Node.js filesystem and is not available in the browser. " +
          "Use downloadBytes() and persist the Uint8Array yourself (e.g. as a Blob download).",
        { code: "unsupported_runtime" },
      );
    }
    const dl = await this.requireDownloadable(id);
    // `node:` prefix + dynamic import keep the browser bundle free of Node built-ins.
    const fs = await import("node:fs/promises");
    const pathMod = await import("node:path");
    const target = await resolveTargetPath(pathMod, fs, dl, path);
    const response = await this.openDownloadStream(id, dl.download_url as string);
    await writeResponseToFile(response, target, fs);
    return target;
  }
}
