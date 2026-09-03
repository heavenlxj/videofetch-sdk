# videofetch (Python SDK)

Official [VideoFetch](https://videofetch.dev) SDK — video ingestion API:
give us a video URL, we deliver MP4/MP3 to your storage.

```bash
pip install videofetch
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
    # destination={"type": "r2", "id": "..."},      # optional direct-to-bucket
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
