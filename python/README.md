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
    # destination="st_9f1c2a34b5d6e7f8",           # optional: your own bucket (see below)
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

Connect a bucket once and reference it by its storage id (`st_…`) from every job — the
provider, bucket, region and credentials stay on the server. Billing is identical to
platform delivery, and failed or cancelled jobs are never charged.

```python
# 1. Connect once (or Dashboard → Storage). test() probes connect → write → cleanup.
check = client.storage.test(provider="s3", bucket="my-bucket", region="us-east-1",
                            access_key_id="AKIA...", secret_access_key="...")
if not check.ok:
    raise SystemExit(f"{check.code}: {check.message} — {check.hint}")
conn = client.storage.create(provider="s3", bucket="my-bucket", region="us-east-1",
                             access_key_id="AKIA...", secret_access_key="...",
                             is_default=True)
print(conn.id)                                   # st_9f1c2a34b5d6e7f8

# 2. Reference it. The result says exactly where the file landed.
result = client.downloads.create(url=..., destination=conn.id).wait()
print(result.delivery.uri)                       # s3://my-bucket/youtube/<video_id>/video.mp4
```

| `destination` | where the file goes |
|---|---|
| omitted | the account's default connection, else the platform (`download_url`, 7 days) |
| `"st_…"` | that saved connection |
| `{"id": "st_…", "path": "clips/{video_id}/"}` or `{"id": …, "key": "a/{video_id}.{ext}"}` | saved connection, object key overridden for this job only |
| `"url"` | the platform, even when a default connection is set |
| `{"type": "s3", "bucket": …, "access_key_id": …, "secret_access_key": …}` | inline credentials for **this job only**; add `"save": True, "name": …` to keep them |

Path variables: `{video_id}`, `{job_id}`, `{format}`, `{date}` (`key` also accepts `{ext}`).

### When delivery fails

A bad destination is rejected up front with `StorageError` (422 — `storage_not_found`,
`storage_config_invalid`, `storage_endpoint_blocked`, `storage_unreachable`); `param` names
the field and `hint` says how to fix it. An upload that fails after the download makes
`job.wait()` raise `DeliveryFailedError`. The file is held for 24 hours, so fix the bucket
and redeliver — nothing is downloaded or charged again:

```python
try:
    result = client.downloads.create(url=..., destination="st_...").wait()
except videofetch.DeliveryFailedError as e:
    print(e.code, e.provider_code, e.hint)      # storage_permission_denied AccessDenied Grant s3:PutObject …
    if e.redeliverable:                          # held until e.hold_expires_at
        result = client.downloads.redeliver(e.job_id).wait()
        # or to another target: client.downloads.redeliver(e.job_id, destination="st_other")
```

Delivery error codes: `storage_unreachable`, `storage_auth_failed`,
`storage_permission_denied`, `storage_bucket_not_found`, `storage_region_mismatch`,
`storage_rate_limited`, `storage_quota_exceeded`, `storage_upload_failed`,
`storage_not_found`. `e.retryable` is True for transient ones (uploads are already retried
3 times). A permanent failure marks the connection `status="failing"` and sends the
`storage.connection_failed` webhook once.

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
| `StorageError` | destination rejected (422, `storage_*`); has `param` and `hint` |
| `NotFoundError` | job/connection not found (404) |
| `ConflictError` | `storage_in_use` (delete with `force=True`) / `not_redeliverable` (409) |
| `RateLimitError` | slow down (429) |
| `JobFailedError` | job reached `failed` — **never charged**; `stage`, `retryable`, `hint` |
| `DeliveryFailedError` | `JobFailedError` at the delivery stage; `redeliverable`, `hold_expires_at` |
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
