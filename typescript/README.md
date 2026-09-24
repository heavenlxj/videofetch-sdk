# @videofetch/sdk (TypeScript)

Official [VideoFetch](https://vidfetch.dev) SDK for TypeScript / JavaScript —
zero runtime dependencies (uses the global `fetch`, works in Node >= 18, browsers
and edge runtimes).

```bash
npm install @videofetch/sdk
```

## Usage

```ts
import { VideoFetch } from "@videofetch/sdk";

const client = new VideoFetch({ apiKey: "vf_live_sk_..." });

// L1: create a job (returns immediately)
const job = await client.downloads.create({
  url: "https://www.youtube.com/watch?v=...",
  format: "1080p",                       // 144p..2160p | mp3
  trim: { start: 120, end: 420 },        // optional clip window
  // destination: { id: "conn_9f1c2a34" },  // optional direct-to-bucket (see below)
});

// L2: wait for the terminal state (polls with backoff)
const result = await job.wait({ timeoutMs: 120_000 });
console.log(result.status);         // "completed"
console.log(result.download_url);   // presigned link (url destination)
console.log(result.storage_key);    // "user://bucket/key" (bucket destination)

// L3: one-shot
const r = await client.downloads.createAndWait({ url, format: "720p" });

// Save the finished file locally (Node.js only) — streams to disk, returns the path
const path = await client.downloads.downloadTo(r.id);
// path === "/abs/cwd/<title-or-id>.mp4"   (pass a file or a directory to override)

// Any runtime (browser / edge): get the raw bytes and persist them yourself
const bytes = await client.downloads.downloadBytes(r.id);
// e.g. browser: const url = URL.createObjectURL(new Blob([bytes]))
```

Webhooks (Next.js route handler / Hono / Fastify):

```ts
import { constructEvent } from "@videofetch/sdk";

export async function POST(request: Request) {
  const payload = await request.text();
  let event;
  try {
    event = await constructEvent(
      payload,
      request.headers.get("X-VideoFetch-Signature"),
      process.env.VIDEOFETCH_WEBHOOK_SECRET!,
    );
  } catch {
    return new Response("bad signature", { status: 400 });
  }
  if (event.event === "download.completed") {
    // persist / react to the finished job
  }
  return Response.json({ ok: true });
}
```

## Storage destinations

By default the platform keeps the finished file and returns a presigned `download_url`
(valid 7 days). Pass `destination` to have it written straight into your own bucket
instead — the job then reports `storage_key` as `user://<bucket>/<key>` and
`download_url` is null. Billing is identical either way, and failed or cancelled jobs are
never charged.

```ts
// A saved connection. Connect the bucket once (Dashboard → Storage, or POST /v1/storage)
// and reuse the id: the provider, bucket and credentials all come from the connection,
// so you never have to know — or repeat — the provider.
await client.downloads.create({
  url, format: "1080p",
  destination: { id: "conn_9f1c2a34" },
});

// Inline credentials. These are stored as a connection for your account and reused by
// later jobs. `type` is required in this form — the SavedDestination vs InlineDestination
// union enforces it, because without a concrete provider the server falls back to "url"
// and would ignore the bucket.
await client.downloads.create({
  url, format: "1080p",
  destination: {
    type: "s3",                 // s3 | r2 | gcs | s3_compatible
    bucket: "my-bucket",
    region: "us-east-1",
    access_key_id: "...",
    secret_access_key: "...",
    path: "videos/",            // optional; key prefix of the new connection (default youtube/{video_id}/)
  },
});
```

## Configuration

```ts
new VideoFetch({
  apiKey: "vf_live_sk_...",      // or process.env.VIDEOFETCH_API_KEY
  baseUrl: "https://api.vidfetch.dev",   // override for local dev
  timeoutMs: 30_000,
  maxRetries: 2,                 // automatic on 429/5xx/network errors
});
```

## Errors

- `QuotaExceededError` — 402 monthly quota exhausted
- `ValidationError` — 400/422 bad url/format/trim/destination
- `NotFoundError` — 404
- `RateLimitError` — 429
- `JobFailedError` — job reached `failed` (**never charged**)

## Serverless warning

Do **not** call `job.wait()` in a Vercel/Cloudflare/Lambda function — it burns
billed execution time. Create the job, persist its id, then respond to the
`download.completed` webhook and call `client.downloads.retrieve(id)`.

## Development

```bash
npm install
npm test          # vitest (mock fetch, no network)
npm run build     # tsup → dist/index.js (esm) + index.cjs + index.d.ts
npm run typecheck
```

## License

MIT
