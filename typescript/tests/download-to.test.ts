import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import {
  VideoFetch, VideoFetchError, defaultDownloadFileName, sanitizeFileStem,
} from "../src";

/** Deterministic payload that is clearly not valid UTF-8 text. */
const FILE_BYTES = new Uint8Array(Array.from({ length: 2048 }, (_, i) => i % 256));

const tmpDirs: string[] = [];

async function makeTmpDir(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "videofetch-dl-"));
  tmpDirs.push(dir);
  return dir;
}

afterEach(async () => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  await Promise.all(tmpDirs.splice(0).map((d) => rm(d, { recursive: true, force: true })));
});

function makeFetch(handler: (url: string, init: RequestInit) => Promise<Response>) {
  return vi.fn(async (url: string | URL | Request, init?: RequestInit) =>
    handler(String(url), init ?? {})) as unknown as typeof fetch;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function bytesResponse(status: number, bytes: Uint8Array): Response {
  return new Response(bytes, {
    status,
    headers: { "Content-Type": "application/octet-stream" },
  });
}

function completedDownload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    id: "dl_abc123", status: "completed", url: "https://www.youtube.com/watch?v=x",
    format: "1080p", title: "My Clip", destination_type: "url",
    download_url: "https://cdn.example/clip.mp4", cost_usd: 0, attempts: 1,
    ...overrides,
  };
}

/** Await a promise expected to reject and return the thrown error, typed. */
async function rejection(promise: Promise<unknown>): Promise<VideoFetchError> {
  try {
    await promise;
  } catch (e) {
    return e as VideoFetchError;
  }
  throw new Error("expected the call to reject");
}

describe("DownloadsResource.downloadTo / downloadBytes", () => {
  it("downloadTo() streams the bytes to disk and returns the absolute path", async () => {
    const dir = await makeTmpDir();
    const filePath = join(dir, "out.mp4");
    const fetchMock = makeFetch(async (url) => {
      if (url.includes("/v1/downloads/")) return jsonResponse(200, completedDownload());
      return bytesResponse(200, FILE_BYTES);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const saved = await client.downloads.downloadTo("dl_abc123", filePath);

    expect(saved).toBe(resolve(filePath));
    const written = new Uint8Array(await readFile(saved));
    expect(written).toEqual(FILE_BYTES);
    expect(written.byteLength).toBe(2048);
  });

  it("derives the default file name from a sanitized title + format extension", async () => {
    const dir = await makeTmpDir();
    vi.spyOn(process, "cwd").mockReturnValue(dir);
    const fetchMock = makeFetch(async (url) => {
      if (url.includes("/v1/downloads/")) return jsonResponse(200, completedDownload());
      return bytesResponse(200, FILE_BYTES);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const saved = await client.downloads.downloadTo("dl_abc123");

    expect(saved).toBe(join(dir, "My Clip.mp4"));
    expect((await readFile(saved)).byteLength).toBe(2048);
  });

  it("uses .mp3 and strips path separators / control chars from the title", async () => {
    const dir = await makeTmpDir();
    vi.spyOn(process, "cwd").mockReturnValue(dir);
    const fetchMock = makeFetch(async (url) => {
      if (url.includes("/v1/downloads/"))
        return jsonResponse(200, completedDownload({
          format: "mp3", title: "  ../a/b\\c\td\n  ",
        }));
      return bytesResponse(200, FILE_BYTES);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const saved = await client.downloads.downloadTo("dl_abc123");

    expect(saved.endsWith(".mp3")).toBe(true);
    expect(saved).toBe(join(dir, "abcd.mp3"));
  });

  it("falls back to the job id (and an unknown format → .mp4) when there is no title", async () => {
    expect(defaultDownloadFileName({ id: "dl_x1", title: null, format: "480p" })).toBe("dl_x1.mp4");
    expect(defaultDownloadFileName({ id: "dl_x2", title: "   ", format: "mp3" })).toBe("dl_x2.mp3");
    expect(sanitizeFileStem("...   ")).toBe("");
  });

  it("treats an existing directory path as a directory to write into", async () => {
    const dir = await makeTmpDir();
    const fetchMock = makeFetch(async (url) => {
      if (url.includes("/v1/downloads/")) return jsonResponse(200, completedDownload({ title: "dir clip" }));
      return bytesResponse(200, FILE_BYTES);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const saved = await client.downloads.downloadTo("dl_abc123", dir);

    expect(saved).toBe(join(dir, "dir clip.mp4"));
    expect((await readFile(saved)).byteLength).toBe(2048);
  });

  it("treats a trailing-separator path as a directory", async () => {
    const dir = await makeTmpDir();
    const fetchMock = makeFetch(async (url) => {
      if (url.includes("/v1/downloads/")) return jsonResponse(200, completedDownload({ title: "sep clip" }));
      return bytesResponse(200, FILE_BYTES);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const saved = await client.downloads.downloadTo("dl_abc123", `${dir}/`);

    expect(saved).toBe(join(dir, "sep clip.mp4"));
  });

  it("throws a typed error when the job is not completed yet", async () => {
    const dir = await makeTmpDir();
    const fetchMock = makeFetch(async () =>
      jsonResponse(200, completedDownload({ status: "processing", download_url: null })));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const err = await rejection(client.downloads.downloadTo("dl_abc123", join(dir, "x.mp4")));
    expect(err).toBeInstanceOf(VideoFetchError);
    expect(err.code).toBe("job_not_completed");
    expect(err.message).toContain("processing");
    expect(err.message.toLowerCase()).toContain("wait");
  });

  it("throws when a completed job has no download_url", async () => {
    const fetchMock = makeFetch(async () =>
      jsonResponse(200, completedDownload({ destination_type: "s3", download_url: null })));
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const err = await rejection(client.downloads.downloadBytes("dl_abc123"));
    expect(err).toBeInstanceOf(VideoFetchError);
    expect(err.code).toBe("missing_download_url");
  });

  it("re-fetches the job and retries once on 403 — the API key is never sent to storage", async () => {
    const dir = await makeTmpDir();
    const filePath = join(dir, "retry.mp4");
    const jobAuthHeaders: Array<string | undefined> = [];
    const storageAuthHeaders: Array<string | undefined> = [];
    let jobGets = 0;

    const fetchMock = makeFetch(async (url, init) => {
      const headers = (init.headers ?? {}) as Record<string, string>;
      if (url.startsWith("http://mock/v1/downloads/")) {
        jobGets += 1;
        jobAuthHeaders.push(headers["Authorization"]);
        const link = jobGets === 1 ? "https://cdn.example/old.mp4" : "https://cdn.example/fresh.mp4";
        return jsonResponse(200, completedDownload({ download_url: link }));
      }
      storageAuthHeaders.push(headers["Authorization"]);
      if (url.endsWith("/old.mp4")) return new Response("expired", { status: 403 });
      return bytesResponse(200, FILE_BYTES);
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const saved = await client.downloads.downloadTo("dl_abc123", filePath);

    expect(jobGets).toBe(2);                              // initial GET + re-sign after 403
    expect(storageAuthHeaders).toHaveLength(2);           // old link (403) + fresh link
    expect(storageAuthHeaders.every((h) => h === undefined)).toBe(true);
    expect(jobAuthHeaders[0]).toBe("Bearer k");           // API calls do carry the key
    expect(new Uint8Array(await readFile(saved))).toEqual(FILE_BYTES);
  });

  it("throws when the retried link is still forbidden", async () => {
    const dir = await makeTmpDir();
    let jobGets = 0;
    const fetchMock = makeFetch(async (url) => {
      if (url.includes("/v1/downloads/")) {
        jobGets += 1;
        return jsonResponse(200, completedDownload({ download_url: `https://cdn.example/s${jobGets}.mp4` }));
      }
      return new Response("nope", { status: 403 });
    });
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    const err = await rejection(client.downloads.downloadTo("dl_abc123", join(dir, "x.mp4")));
    expect(err).toBeInstanceOf(VideoFetchError);
    expect(err.statusCode).toBe(403);
    expect(jobGets).toBe(2);
  });

  it("downloadTo() throws a clear error without a Node runtime; downloadBytes() still works", async () => {
    // Pre-build responses so no fetch machinery runs while `process` is stubbed out.
    const jobResponse = jsonResponse(200, completedDownload());
    const fileResponse = bytesResponse(200, FILE_BYTES);
    const fetchMock = makeFetch(async (url) =>
      url.includes("/v1/downloads/") ? jobResponse : fileResponse);
    const client = new VideoFetch({ apiKey: "k", baseUrl: "http://mock", fetch: fetchMock });

    vi.stubGlobal("process", undefined);

    const err = await rejection(client.downloads.downloadTo("dl_abc123"));
    expect(err).toBeInstanceOf(VideoFetchError);
    expect(err.code).toBe("unsupported_runtime");
    expect(err.message).toContain("downloadBytes");

    const bytes = await client.downloads.downloadBytes("dl_abc123");
    expect(bytes).toEqual(FILE_BYTES);
  });
});
