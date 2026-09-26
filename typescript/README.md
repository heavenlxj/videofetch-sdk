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
  // destination: "st_9f1c2a34b5d6e7f8",   // optional: your own bucket (see below)
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

Connect a bucket once and reference it by its storage id (`st_…`) from every job — the
provider, bucket, region and credentials stay on the server. Billing is identical to
platform delivery, and failed or cancelled jobs are never charged.

```ts
// 1. Connect once (or Dashboard → Storage). test() probes connect → write → cleanup.
const creds = { provider: "s3", bucket: "my-bucket", region: "us-east-1",
                access_key_id: "AKIA...", secret_access_key: "..." } as const;
const check = await client.storage.test(creds);
if (!check.ok) throw new Error(`${check.code}: ${check.message} — ${check.hint}`);
const conn = await client.storage.create({ ...creds, is_default: true });
console.log(conn.id);                              // st_9f1c2a34b5d6e7f8

// 2. Reference it. The result says exactly where the file landed.
const done = await (await client.downloads.create({ url, destination: conn.id })).wait();
console.log(done.delivery?.uri);                   // s3://my-bucket/youtube/<video_id>/video.mp4
```

| `destination` | where the file goes |
|---|---|
| omitted | the account's default connection, else the platform (`download_url`, 7 days) |
| `"st_…"` | that saved connection |
| `{ id: "st_…", path: "clips/{video_id}/" }` or `{ id, key: "a/{video_id}.{ext}" }` | saved connection, object key overridden for this job only |
| `"url"` | the platform, even when a default connection is set |
| `{ type: "s3", bucket, access_key_id, secret_access_key }` | inline credentials for **this job only**; add `save: true, name` to keep them |

Path variables: `{video_id}`, `{job_id}`, `{format}`, `{date}` (`key` also accepts `{ext}`).

### When delivery fails

A bad destination is rejected up front with `StorageError` (422 — `storage_not_found`,
`storage_config_invalid`, `storage_endpoint_blocked`, `storage_unreachable`); `param` names
the field and `hint` says how to fix it. An upload that fails after the download makes
`job.wait()` throw `DeliveryFailedError`. The file is held for 24 hours, so fix the bucket
and redeliver — nothing is downloaded or charged again:

```ts
import { DeliveryFailedError } from "@videofetch/sdk";

try {
  await (await client.downloads.create({ url, destination: "st_..." })).wait();
} catch (e) {
  if (e instanceof DeliveryFailedError && e.redeliverable) {   // held until e.holdExpiresAt
    console.warn(e.code, e.providerCode, e.hint);            // storage_permission_denied AccessDenied …
    await (await client.downloads.redeliver(e.jobId)).wait();
    // or elsewhere: client.downloads.redeliver(e.jobId, "st_other")
  } else throw e;
}
```

Delivery error codes: `storage_unreachable`, `storage_auth_failed`,
`storage_permission_denied`, `storage_bucket_not_found`, `storage_region_mismatch`,
`storage_rate_limited`, `storage_quota_exceeded`, `storage_upload_failed`,
`storage_not_found`. `e.retryable` is true for transient ones (uploads are already retried
3 times). A permanent failure marks the connection `status: "failing"` and sends the
`storage.connection_failed` webhook once.

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
- `StorageError` — 422 `storage_*`, destination rejected; has `param` and `hint`
- `NotFoundError` — 404
- `ConflictError` — 409 `storage_in_use` (delete with `{ force: true }`) / `not_redeliverable`
- `RateLimitError` — 429
- `JobFailedError` — job reached `failed` (**never charged**); `stage`, `retryable`, `hint`
- `DeliveryFailedError` — `JobFailedError` at the delivery stage; `redeliverable`, `holdExpiresAt`

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
