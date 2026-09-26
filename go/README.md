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

Save the finished artifact straight to disk (the presigned `download_url` is
fetched without your API key and streamed to the file in chunks):

```go
// "" derives <title-or-id>.<mp4|mp3> in the current directory; an existing
// directory (or a trailing separator) puts the derived name inside it.
abs, err := client.Downloads.DownloadTo(ctx, result.ID, "")
if err != nil { panic(err) }
fmt.Println(abs) // /absolute/path/to/My Clip.mp4

// A non-completed job fails fast:
if _, err := client.Downloads.DownloadTo(ctx, id, "out.mp4"); errors.Is(err, videofetch.ErrJobNotCompleted) {
    // wait for completion (Job.Wait or the download.completed webhook) first
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

## Storage destinations

Connect a bucket once and reference it by its storage id (`st_…`) from every job — the
provider, bucket, region and credentials stay on the server. Billing is identical to
platform delivery, and failed or cancelled jobs are never charged.

```go
// 1. Connect once (or Dashboard → Storage). Test probes connect → write → cleanup.
check, err := client.Storage.Test(ctx, videofetch.StorageTestParams{
    Provider: "s3", Bucket: "my-bucket", Region: "us-east-1",
    AccessKeyID: "AKIA...", SecretAccessKey: "...",
})
if err == nil && !check.OK {
    log.Fatalf("%s: %s", *check.Code, check.Message)
}
conn, err := client.Storage.Create(ctx, videofetch.StorageCreateParams{
    Provider: "s3", Bucket: "my-bucket", Region: "us-east-1",
    AccessKeyID: "AKIA...", SecretAccessKey: "...", IsDefault: true,
})
fmt.Println(conn.ID) // st_9f1c2a34b5d6e7f8

// 2. Reference it. The result says exactly where the file landed.
dl, err := client.Downloads.CreateAndWait(ctx, videofetch.DownloadCreateParams{
    URL:         url,
    Destination: videofetch.StorageID(conn.ID),
}, 0)
fmt.Println(*dl.Delivery.URI) // s3://my-bucket/youtube/<video_id>/video.mp4
```

| `Destination` | where the file goes |
|---|---|
| `nil` | the account's default connection, else the platform (`DownloadURL`, 7 days) |
| `videofetch.StorageID("st_…")` | that saved connection |
| `&DestinationSpec{ID: "st_…", Path: "clips/{video_id}/"}` (or `Key: "a/{video_id}.{ext}"`) | saved connection, object key overridden for this job only |
| `videofetch.PlatformURL()` | the platform, even when a default connection is set |
| `&DestinationSpec{Type: "s3", Bucket, AccessKeyID, SecretAccessKey}` | inline credentials for **this job only**; set `Save: true, Name: …` to keep them |

Path variables: `{video_id}`, `{job_id}`, `{format}`, `{date}` (`Key` also accepts `{ext}`).

### When delivery fails

A bad destination is rejected up front with `*StorageError` (422 — `storage_not_found`,
`storage_config_invalid`, `storage_endpoint_blocked`, `storage_unreachable`); `Param` names
the field and `Hint` says how to fix it. An upload that fails after the download makes
`Wait` return a `*JobFailedError` with `Stage == "delivery"` (also matched by
`errors.Is(err, videofetch.ErrDeliveryFailed)`). The file is held for 24 hours, so fix the
bucket and redeliver — nothing is downloaded or charged again:

```go
var jf *videofetch.JobFailedError
if errors.As(err, &jf) && errors.Is(err, videofetch.ErrDeliveryFailed) && jf.Redeliverable() {
    log.Printf("%s %s: %s", jf.ErrorCode, jf.ProviderCode, jf.Hint) // storage_permission_denied AccessDenied …
    job, _ := client.Downloads.Redeliver(ctx, jf.JobID, nil)      // or another StorageID(...)
    dl, err = job.Wait(ctx, 0)
}
```

Delivery error codes: `storage_unreachable`, `storage_auth_failed`,
`storage_permission_denied`, `storage_bucket_not_found`, `storage_region_mismatch`,
`storage_rate_limited`, `storage_quota_exceeded`, `storage_upload_failed`,
`storage_not_found`. `Retryable` is true for transient ones (uploads are already retried
3 times). A permanent failure marks the connection `Status == "failing"` and sends the
`storage.connection_failed` webhook once.

## Configuration

- `NewClient(apiKey, opts)` — apiKey falls back to `VIDEOFETCH_API_KEY`.
- `opts.BaseURL` — default hosted API; override for local dev (`http://localhost:8301`).
  Env: `VIDEOFETCH_BASE_URL`.
- `opts.HTTPClient` / `opts.Timeout` / `opts.MaxRetries` — automatic retry on 429/5xx.

## Errors

- `*APIError` — HTTP errors with `.Code`, `.Message`, `.Param`, `.Hint`, `.StatusCode`
- `*QuotaExceededError` — 402 monthly quota exhausted
- `*StorageError` — 422 `storage_*`, destination rejected at create time
- `*ConflictError` — 409 `storage_in_use` (`Storage.Delete(ctx, id, true)` forces) / `not_redeliverable`
- `*JobFailedError` — job reached `failed` (**never charged**); `.Stage`, `.Retryable`, `.Hint`,
  `.ProviderCode`, `.Redeliverable()`; wraps `ErrDeliveryFailed` for delivery-stage failures

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


## Usage, alerts and credits

```go
u, _ := client.Usage.Get(ctx)
*u.QuotaGB            // account plan quota this month (GB)
u.UsedPct             // % consumed
u.RemainingGB         // remaining GB before overage
u.ActiveJobs          // queued + processing on your account
u.ConcurrencyLimit    // max in-flight jobs per account
u.AlertLevel          // ok | warning | critical | exceeded
u.PaygBalanceCents    // pay-as-you-go credit

a, _ := client.Usage.Alerts(ctx)
a.State.Level               // ok | warning | critical | exceeded
a.State.Crossed             // thresholds already crossed, e.g. [80 95]
a.State.Action              // "topup" | "upgrade" | nil
a.Thresholds                // [80 95 100]
a.TopupAmounts              // [10 25 50 100]
a.Fired                     // alerts delivered this month
```

Alert webhook events: `quota.warning` (80%/95%), `quota.exceeded` (100%),
`balance.low` (credit nearly gone). Each threshold fires at most once per month.

## Managing webhook endpoints with your API key

```go
wh, err := client.Webhooks.Create(ctx, "https://api.yourapp.com/hook",
    videofetch.EventCompleted, videofetch.EventQuotaExceeded, videofetch.EventBalanceLow)
wh.Secret   // whsec_... — FULL value, only returned by Create. Store it now.

lst, _ := client.Webhooks.List(ctx)      // secrets are masked
res, _ := client.Webhooks.Test(ctx, wh.ID) // ping; res.Delivered, res.LastStatus
err = client.Webhooks.Delete(ctx, wh.ID)

ev, err := videofetch.VerifyWebhookSignature(rawBody, r.Header.Get("X-VideoFetch-Signature"), wh.Secret)
// err is ErrBadSignature when the raw body and signature disagree.
```

## Concurrency limits and 429s

```go
job, err := client.Downloads.Create(ctx, videofetch.DownloadCreateParams{URL: url, Format: videofetch.Format1080p})
var rl *videofetch.RateLimitError
if errors.As(err, &rl) {
    rl.Code       // concurrency_limit_exceeded | queue_limit_exceeded | platform_at_capacity
    rl.Limit; rl.Active; rl.Scope; rl.RetryAfter
}
```

A suspended account returns a typed permission error with `code=account_suspended`.
