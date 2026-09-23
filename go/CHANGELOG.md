# Changelog

## 0.3.0 — 2026-09-22

Added
- `client.Webhooks.Deliveries(ctx, endpointID, limit)` — per-endpoint delivery history plus
  aggregate health (`WebhookDeliveriesResult`, `WebhookDelivery`, `WebhookDeliveryHealth`).
  `limit <= 0` uses the server default (50). Items are ordered by `seq`, not by timestamp.
- `client.Webhooks.Replay(ctx, eventID)` — re-queue a delivery by event id (e.g. after fixing a
  receiver); returns `ReplayResult{Queued, EventID}`.
- Webhook header helpers: `DeliveryID(headers)` reads `X-VideoFetch-Delivery` (the idempotency
  key) and `AttemptNumber(headers)` reads `X-VideoFetch-Attempt` (1-based; 0 when absent/invalid).
  Delivery requests also carry `X-VideoFetch-Timestamp`.
- `Download` gained nullable queue telemetry — `QueuePosition`, `AheadOfYou`,
  `EstimatedWaitSeconds` (`*int`) — populated only while `status == "queued"` (null otherwise).
- `Usage` gained `KeyUsedBytes` / `KeyUsedGB` for per-API-key month-to-date usage.
- `client.Downloads.DownloadTo(ctx, id, path)` — save a completed artifact straight to a local
  file and get back its absolute path. The file is streamed to disk in chunks and fetched from
  the platform-issued `download_url` (self-authorising, so no API key is sent). An empty `path`
  (or an existing directory / trailing separator) derives a safe `<title-or-id>.<mp4|mp3>` name;
  a non-completed job returns `*JobNotCompletedError` (wraps `ErrJobNotCompleted`). An expired
  link (403) re-fetches the job and retries once.

Changed (breaking)
- `DownloadAttempt.Egress` (json `egress`) replaces the 0.2.0 raw host field and carries a neutral
  label: `"relay"` when the attempt was served through an alternate route, nil for a direct
  attempt. Internal egress hosts are not part of the public contract.
- `DownloadStrategy` values are now `"direct" | "relay" | "relay_secondary"` for both
  `Download.Strategy` and `DownloadAttempt.Strategy`. Unknown values are normalised to `"relay"`.
- Attempt `ErrorMessage` values are scrubbed of egress addresses and credentials before being
  returned.
- `Usage.UsedBytes` / `Usage.UsedGB` now report **account-level** month-to-date usage (previously
  per API key). Use `KeyUsedBytes` / `KeyUsedGB` for the per-key figure.
- `GET /v1/downloads` list and detail are now **account-level** visible (every key on the account
  sees all of the account's jobs).

Changed — webhook delivery semantics
- Retries: at most **3** delivery attempts in total (the first try counts; previously 5), with a
  30s → 300s backoff (±20%).
- **4xx responses are permanent failures and are not retried** (408 and 429 are the exceptions).
- Deliveries remain **at-least-once** (the same event may be delivered more than once) and are
  **not ordered** — deduplicate on `X-VideoFetch-Delivery` and order by `seq`.

Migration
- If you read the raw host field from 0.2.0, read `Egress` instead — it is a label, not a hostname.
- Branch on `dl.Strategy == "direct"` vs anything else. Stay on `v0.2.x` if you need the old shape
  while you migrate.
- Add idempotent handling keyed on `X-VideoFetch-Delivery` (see `DeliveryID`) before the retry
  change lands; process events by `seq`, not arrival order.
- If you relied on per-key `UsedGB`, switch to `KeyUsedGB` (`UsedGB` is now account-level).

## 0.2.0

Added
- `client.Usage.Get(ctx)` / `client.Usage.Alerts(ctx)` — account quota snapshot
  (`UsedPct`, `RemainingGB`, `ActiveJobs`, `ConcurrencyLimit`, `AlertLevel`) and live alert
  state + fired-history + thresholds / top-up presets.
- `client.Webhooks` — `Create` / `List` / `Test` / `Delete` account-level endpoints with an API
  key. `Create` returns the full secret once; `List` masks it.
- Event constants `EventQuotaWarning`, `EventQuotaExceeded`, `EventBalanceLow` and the
  `WebhookEvents` slice listing every subscribable event.
- Typed errors: `RateLimitError` (with `Limit`, `Active`, `Scope`, `RetryAfter`),
  `QuotaExceededError` (`RemainingGB`), `PermissionDeniedError`; all unwrap to `*APIError`
  so `errors.As` works for either level.

Changed
- `VerifyWebhookSignature` keeps the `sha256=<hex>` (raw body) contract and now returns
  `ErrBadSignature` for tampered payloads.

## 0.1.0

- Initial release: downloads (create / retrieve / list / cancel / `Wait`), info, typed errors,
  webhook signature verification.
