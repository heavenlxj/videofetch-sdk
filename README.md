# VideoFetch SDKs (monorepo)

Official SDKs for the [VideoFetch](https://vidfetch.dev) video ingestion API:
give us a video URL, we deliver the MP4/MP3 to your storage.

| Language | Package | Source | Status |
|---|---|---|---|
| Python | `videofetch` | [`python/`](python/) | 0.5.0 |
| TypeScript | `@videofetch/sdk` | [`typescript/`](typescript/) | 0.5.0 |
| Go | `github.com/heavenlxj/videofetch-sdk/go` | [`go/`](go/) | v0.5.0 |

- `openapi/openapi.json` — the API contract (single source of truth, exported from the backend).
  SDK types are hand-written against it; endpoint/method behaviour must stay in sync.

## Install

```bash
# Python
pip install videofetch-sdk

# TypeScript
npm install @videofetch/sdk

# Go
go get github.com/heavenlxj/videofetch-sdk/go
```

## Quickstart (all three, same shape)

```python
import videofetch

client = videofetch.VideoFetch(api_key="vf_live_sk_...")

job = client.downloads.create(
    url="https://www.youtube.com/watch?v=...",
    format="1080p",
)
result = job.wait(timeout=120)
print(result.download_url)
```

```ts
import { VideoFetch } from "@videofetch/sdk";

const client = new VideoFetch({ apiKey: "vf_live_sk_..." });

const job = await client.downloads.create({
  url: "https://www.youtube.com/watch?v=...",
  format: "1080p",
});
const result = await job.wait({ timeoutMs: 120_000 });
console.log(result.download_url);
```

```go
package main

import (
    "context"
    "fmt"
    videofetch "github.com/heavenlxj/videofetch-sdk/go"
)

func main() {
    client := videofetch.NewClient("vf_live_sk_...", nil)
    job, _ := client.Downloads.Create(context.Background(), videofetch.DownloadCreateParams{
        URL: "https://www.youtube.com/watch?v=...", Format: "1080p",
    })
    result, err := job.Wait(context.Background())
    if err != nil {
        panic(err)
    }
    fmt.Println(result.DownloadURL)
}
```

> Note: the API key above is an example. Create your own key in the Dashboard.

## Async model — read this first

`POST /v1/downloads` returns `202 Accepted` with a job id immediately. The actual
download happens asynchronously. Every SDK wraps this in a `job` object with a
`.wait()` helper that polls `GET /v1/downloads/{id}` with backoff until the job
reaches a terminal state. You can also ignore `wait()` and poll yourself, or use
webhooks.

> **Serverless warning:** do NOT call `job.wait()` inside a Vercel/Cloudflare/Lambda
> function — it will burn billed execution time. Instead: create the job, store the
> id, and let a webhook (`download.completed`) tell you when to fetch the result.

## Base URL / local development

By default SDKs point at the hosted API. During development you can point them at
your own single-server deployment:

```python
client = videofetch.VideoFetch(api_key="...", base_url="http://localhost:8301")
# env: VIDEOFETCH_API_KEY, VIDEOFETCH_BASE_URL
```

## Docs

- `docs/getting-started.md` — async model, webhook events, formats, destinations, serverless warning
- `docs/releasing.md` — publish runbook (PyPI / npm / Go)
- `openapi/openapi.json` — API contract (single source of truth)

## Development

```bash
# Python
cd python && pip install -e ".[dev]" && pytest

# TypeScript
cd typescript && npm install && npm test && npm run build

# Go
cd go && go test ./...
```

## Releasing

See [docs/SDK_RELEASE_GUIDE.md](../youtuber/docs/SDK_RELEASE_GUIDE.md) in the main
repo for the full playbook. Short version:

- Python: tag `python-v0.1.0` → GitHub Actions builds + PyPI trusted publishing
- TypeScript: tag `ts-v0.1.0` → npm publish (NPM_TOKEN)
- Go: tag `go-v0.1.0` → proxy.golang.org picks it up automatically

License: MIT
