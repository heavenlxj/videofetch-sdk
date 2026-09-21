# videofetch-go

Official [VideoFetch](https://vidfetch.dev) Go SDK — video ingestion API:
give us a video URL, we deliver MP4/MP3 to your storage.

```bash
go get github.com/heavenlxj/videofetch-sdk/go
```

## Usage

```go
package main

import (
    "context"
    "fmt"
    "time"

    videofetch "github.com/heavenlxj/videofetch-sdk/go"
)

func main() {
    client := videofetch.NewClient("vf_live_sk_...", nil)

    // L1: create a job (returns immediately)
    job, err := client.Downloads.Create(context.Background(), videofetch.DownloadCreateParams{
        URL:    "https://www.youtube.com/watch?v=...",
        Format: videofetch.Format1080p,
        Trim:   &videofetch.TrimSpec{ /* Start/End float64 ptr, seconds */ },
    })
    if err != nil { panic(err) }

    // L2: wait for the terminal state
    result, err := job.Wait(context.Background(), 2*time.Minute)
    if err != nil { panic(err) }
    fmt.Println(result.Status)                  // completed
    fmt.Println(*result.DownloadURL)            // presigned link (url destination)
    fmt.Println(*result.StorageKey)             // user://bucket/key (bucket destination)

    // L3: one-shot
    // result, err := client.Downloads.CreateAndWait(ctx, params, timeout)
}
```

Free metadata lookup:

```go
info, err := client.Info.Lookup(ctx, "https://www.youtube.com/watch?v=...")
fmt.Println(*info.Title, *info.Duration, info.Formats)
```

Webhooks (net/http):

```go
func handleWebhook(w http.ResponseWriter, r *http.Request) {
    body, _ := io.ReadAll(r.Body)
    event, err := videofetch.VerifyWebhookSignature(
        body, r.Header.Get("X-VideoFetch-Signature"), secret,
    )
    if err != nil {
        http.Error(w, "bad signature", http.StatusBadRequest)
        return
    }
    if event.Event == videofetch.EventCompleted {
        // fetch final result via client.Downloads.Retrieve(ctx, event.ID)
    }
    w.WriteHeader(200)
}
```

## Configuration

- `NewClient(apiKey, opts)` — apiKey falls back to `VIDEOFETCH_API_KEY`.
- `opts.BaseURL` — default hosted API; override for local dev (`http://localhost:8301`).
  Env: `VIDEOFETCH_BASE_URL`.
- `opts.HTTPClient` / `opts.Timeout` / `opts.MaxRetries` — automatic retry on 429/5xx.

## Errors

- `*APIError` — HTTP errors with `.Code`, `.Message`, `.Param`, `.StatusCode`
- `*QuotaExceededError` — 402 monthly quota exhausted
- `*JobFailedError` — job reached `failed` (**never charged**)

## Serverless warning

Do **not** call `Job.Wait` in a Vercel/Cloudflare/Lambda function — it burns
billed execution time. Create the job, store the id, then let the
`download.completed` webhook tell you when to `Retrieve(id)`.

## Development

```bash
go test ./...
go vet ./...
```

## License

MIT
