# Getting started (all SDKs)

The three official SDKs expose the same shape:

| concept | Python | TypeScript | Go |
|---|---|---|---|
| client | `videofetch.VideoFetch(api_key=...)` | `new VideoFetch({apiKey})` | `videofetch.NewClient(key, nil)` |
| create job | `client.downloads.create(url, format=...)` | `client.downloads.create({url, format})` | `client.Downloads.Create(ctx, params)` |
| wait | `job.wait(timeout=120)` | `await job.wait({timeoutMs})` | `job.Wait(ctx, 2*time.Minute)` |
| one-shot | `create_and_wait(...)` | `createAndWait(...)` | `CreateAndWait(...)` |
| retrieve | `client.downloads.retrieve(id)` | `client.downloads.retrieve(id)` | `client.Downloads.Retrieve(ctx, id)` |
| cancel | `client.downloads.cancel(id)` | `client.downloads.cancel(id)` | `client.Downloads.Cancel(ctx, id)` |
| metadata | `client.info.lookup(url)` | `client.info.lookup(url)` | `client.Info.Lookup(ctx, url)` |
| webhook | `construct_event(body, sig, secret)` | `constructEvent(body, sig, secret)` | `VerifyWebhookSignature(body, sig, secret)` |

## Async model — read this first

`POST /v1/downloads` returns `202 Accepted` with a job id (`dl_...`) immediately.
The actual download runs asynchronously:

```
create → queued → processing → completed | failed
                                 ↓              ↓
                    download_url        never charged
                    (or storage_key)    attempt_details visible
```

You have three options:
1. **`job.wait()`** — SDK polls `GET /v1/downloads/{id}` with backoff until terminal.
   Convenient in scripts and long-running services.
2. **Poll yourself** — `retrieve(id)` on your own schedule.
3. **Webhooks** — the recommended way for serverless / high-throughput apps.

## Webhook events

| event | meaning |
|---|---|
| `download.queued` | job accepted |
| `download.processing` | download started |
| `download.completed` | done — contains `download_url` or `destination` + `id` |
| `download.failed` | failed — contains `error_code`/`error_message`; **not charged** |

Verify the `X-VideoFetch-Signature` header (format `sha256=<hex>` of the raw body,
HMAC-SHA256 with your endpoint secret) before trusting a payload — see the
webhook example in each language README.

## Formats

`144p 240p 360p 480p 720p 1080p 1440p 2160p mp3` (mp3 = 128kbps audio).

## Destination (direct-to-bucket)

Pass `destination: {type: "r2", id: "..."}` (saved connection) or inline
credentials. When delivered to your bucket the response carries
`storage_key: "user://<bucket>/<key>"` and no `download_url` — pull the file
with your own storage credentials. See the main repo's
`docs/STORAGE_API_REFERENCE.md` for the full provider matrix and scope.

## Serverless warning

Do **not** call `wait()` inside a Vercel / Cloudflare Workers / AWS Lambda
function — it burns billed execution time:

```
❌ export async function handler() {
     await job.wait();            // bills you for the whole download time
   }

✅ export async function handler() {
     const job = await client.downloads.create({...});
     await db.save(job.id);       // store it
     return { jobId: job.id };    // respond immediately
   }
   // a download.completed webhook later tells you when to retrieve(id)
```

## Errors

All SDKs map the server error contract `{code, message, param}` to typed errors:
`AuthenticationError` (401), `QuotaExceededError` (402), `ValidationError`
(400/422 invalid url/format/trim/destination), `NotFoundError` (404),
`RateLimitError` (429), `JobFailedError` (job failed — never charged).
