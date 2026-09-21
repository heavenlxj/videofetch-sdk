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
  // destination: { type: "r2", id: "..." },   // optional direct-to-bucket
});

// L2: wait for the terminal state (polls with backoff)
const result = await job.wait({ timeoutMs: 120_000 });
console.log(result.status);         // "completed"
console.log(result.download_url);   // presigned link (url destination)
console.log(result.storage_key);    // "user://bucket/key" (bucket destination)

// L3: one-shot
const r = await client.downloads.createAndWait({ url, format: "720p" });
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
