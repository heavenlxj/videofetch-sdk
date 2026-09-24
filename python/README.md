# videofetch (Python SDK)

Official [VideoFetch](https://vidfetch.dev) SDK — video ingestion API:
give us a video URL, we deliver MP4/MP3 to your storage.

```bash
pip install videofetch-sdk
```

## Usage

```python
import videofetch

client = videofetch.VideoFetch(api_key="vf_live_sk_...")

# L1: create a job (returns immediately, status "queued")
job = client.downloads.create(
    url="https://www.youtube.com/watch?v=...",
    format="1080p",                 # 144p..2160p | mp3
    trim=videofetch.TrimSpec(start=120, end=420),   # optional clip window
    # destination={"id": "conn_9f1c2a34"},          # optional direct-to-bucket (see below)
)

# L2: wait for the terminal state (polls with backoff)
result = job.wait(timeout=120)
print(result.status)        # "completed"
print(result.download_url)  # presigned link, valid 7 days (url destination)
print(result.storage_key)   # "user://<bucket>/<key>" (bucket destination)
print(result.size_bytes, result.cost_usd)

# L3: one-shot
result = client.downloads.create_and_wait(url=..., format="1080p")
```

Save the artifact locally. Created with no destination configured, the job completes
with a time-limited `download_url`; `download_to` streams it to disk and returns the
absolute path of the saved file:

```python
path = client.downloads.download_to(result.id)          # ./<title>.mp4 in the current dir
path = client.downloads.download_to(result.id, "out/clip.mp4")   # explicit file path
path = client.downloads.download_to(result.id, "out/")           # existing directory
print(path)   # "/abs/path/out/clip.mp4"
```

The default name is the sanitized title (or the job id) plus `.mp3` for `format="mp3"`
and `.mp4` otherwise. The self-authorizing link is fetched without your API key, and an
expired link is re-signed and retried once. A job that is not `completed` raises
`DownloadNotCompletedError`.

Async (FastAPI / Next.js backends):

```python
from videofetch.asyncio import AsyncVideoFetch

async with AsyncVideoFetch(api_key="...") as client:
    job = await client.downloads.create(url=..., format="1080p")
    result = await job.wait(timeout=120)
```

Free metadata lookup:

```python
info = client.info.lookup("https://www.youtube.com/watch?v=...")
print(info.title, info.duration, info.formats)   # available quality tiers
```

Webhooks (FastAPI):

```python
from fastapi import Request, HTTPException
from videofetch.webhooks import construct_event, SignatureVerificationError

@app.post("/webhooks/videofetch")
async def on_event(request: Request):
    body = await request.body()
    try:
        event = construct_event(body, request.headers.get("X-VideoFetch-Signature"), WEBHOOK_SECRET)
    except SignatureVerificationError:
        raise HTTPException(status_code=400, detail="bad signature")
    if event["event"] == "download.completed":
        ...  # fetch the result via client.downloads.retrieve(event["id"])
    return {"ok": True}
```

## Storage destinations

By default the platform keeps the finished file and returns a presigned `download_url`
(valid 7 days). Pass `destination` to have it written straight into your own bucket
instead — the job then reports `storage_key` as `user://<bucket>/<key>` and
`download_url` is null. Billing is identical either way, and failed or cancelled jobs are
never charged.

```python
# A saved connection. Connect the bucket once (Dashboard → Storage, or POST /v1/storage)
# and reuse the id: the provider, bucket and credentials all come from the connection,
# so you never have to know — or repeat — the provider.
job = client.downloads.create(url=..., format="1080p", destination={"id": "conn_9f1c2a34"})

# Inline credentials. These are stored as a connection for your account and reused by
# later jobs. `type` is required in this form — without a concrete provider the server
# falls back to "url" and would ignore the bucket.
job = client.downloads.create(url=..., format="1080p", destination={
    "type": "s3",                 # s3 | r2 | gcs | s3_compatible
    "bucket": "my-bucket",
    "region": "us-east-1",
    "access_key_id": "...",
    "secret_access_key": "...",
    "path": "videos/",            # optional; key prefix of the new connection (default youtube/{video_id}/)
})
```

## Configuration

- `api_key` — required. Create keys in the Dashboard (`vf_live_sk_...`).
  Falls back to the `VIDEOFETCH_API_KEY` env var.
- `base_url` — defaults to the hosted API; override for local/single-server dev
  (`http://localhost:8301`). Env: `VIDEOFETCH_BASE_URL`.
- `timeout` (s), `max_retries` (default 2, automatic on 429/5xx).

## Errors

All SDK errors derive from `videofetch.VideoFetchError`:

| error | meaning |
|---|---|
| `AuthenticationError` | bad/expired key (401) |
| `QuotaExceededError` | monthly quota exhausted (402) |
| `ValidationError` | bad url/format/trim/destination (400/422) |
| `NotFoundError` | job/connection not found (404) |
| `RateLimitError` | slow down (429) |
| `JobFailedError` | job reached `failed` — **never charged** |
| `DownloadNotCompletedError` | `download_to()` called before the job is `completed` |
| `DownloadURLUnavailableError` | completed job has no `download_url` (bucket destination) |

## Serverless warning

Do **not** call `job.wait()` in a Vercel/Cloudflare/Lambda function — it burns
billed execution time. Create the job, persist its id, then respond to the
`download.completed` webhook and `retrieve(id)` the final result.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT


## Usage, alerts and credits

```python
u = client.usage.get()
u.plan            # "free" | "developer" | "growth" | "scale"
u.quota_gb        # account plan quota for this month (GB)
u.used_pct        # % of the monthly quota consumed
u.remaining_gb    # remaining GB before overage
u.active_jobs     # jobs currently queued + processing on your account
u.concurrency_limit  # max in-flight jobs per account
u.alert_level     # ok | warning | critical | exceeded
u.payg_balance_cents  # pay-as-you-go credit balance

a = client.usage.alerts()
a.state.level          # ok | warning | critical | exceeded
a.state.crossed        # e.g. [80, 95] — thresholds already crossed
a.state.next_threshold_pct
a.state.action         # "topup" | "upgrade" | None  → drive your own UI
a.fired                # alerts already delivered this month (kind/level/pct/created_at)
a.thresholds           # [80, 95, 100]
a.topup_amounts        # [10, 25, 50, 100]
```

Alerts are evaluated after every successful download and delivered to your webhook
endpoints as `quota.warning` (80%/95%) and `quota.exceeded` (100%); a low credit
balance emits `balance.low`. Each threshold fires at most once per calendar month,
so your handler will not be spammed.

## Managing webhook endpoints with your API key

```python
wh = client.webhooks.create(
    "https://api.yourapp.com/videofetch/hook",
    events=["download.completed", "quota.exceeded", "balance.low"],
)
wh.secret            # whsec_... — FULL value, shown only on create. Store it now.

client.webhooks.list()          # secrets are masked here
client.webhooks.test(wh.id)     # send a webhook.test ping, check delivery
client.webhooks.delete(wh.id)
```

Available events: `download.queued`, `download.processing`, `download.completed`,
`download.failed`, `quota.warning`, `quota.exceeded`, `balance.low`.

Verification mirrors the server exactly — HMAC-SHA256 over the **raw** request body:

```python
from videofetch import construct_event   # or verify_webhook_signature(raw, header, secret)
event = construct_event(request.body, request.headers["X-VideoFetch-Signature"], wh.secret)
```

## Concurrency limits and 429s

Your account may run a limited number of jobs at once (queued + processing). When the
cap is reached the API answers `429` with a typed `RateLimitError` instead of silently
queueing forever:

```python
from videofetch import RateLimitError
try:
    client.downloads.create(url=url, format="1080p")
except RateLimitError as e:
    e.code        # concurrency_limit_exceeded | queue_limit_exceeded | platform_at_capacity
    e.limit, e.active, e.scope
    e.retry_after # seconds, from the Retry-After header
```

`GET /v1/usage` returns `active_jobs` / `concurrency_limit` so you can schedule work
before hitting the cap. A suspended account returns `403` with
`code=account_suspended` (surface it to your own operators rather than retrying).
