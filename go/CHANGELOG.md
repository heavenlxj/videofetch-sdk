# Changelog

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
