# Changelog

## 0.2.0

Added
- `client.usage` — account-level quota snapshot (`get()`) with `used_pct`, `remaining_gb`,
  `active_jobs`, `concurrency_limit`, `alert_level` / `alert_message`, plus month-to-date
  account usage that matches `GET /v1/stats/overview`.
- `client.usage.alerts()` — live alert state (level, crossed/next threshold, balance hints,
  recommended action), the alerts already fired this month, configured thresholds and
  top-up presets. New models `Usage`, `AlertState`, `AlertEvent`, `UsageAlerts`.
- `client.webhooks` — create / list / delete / test account-level webhook endpoints using an
  API key (no dashboard session required). `create()` returns the full signing secret once;
  `list()` masks it. `test()` sends a `webhook.test` ping and reports the delivery status.
- Webhook events `quota.warning`, `quota.exceeded`, `balance.low` (in addition to the four
  `download.*` events).
- `verify_webhook_signature(raw_body, signature_header, secret)` module-level helper
  (constant-time compare over the raw body).
- Typed errors: `RateLimitError` (429 — carries `code`, `limit`, `active`, `scope`,
  `retry_after`), `QuotaExceededError` (402 with `remaining_gb`), `PermissionDeniedError`
  (403, e.g. `account_suspended`); `PermissionDeniedError` is now exported.
- `downloads.create(...)` accepts flat `trim_start` / `trim_end` aliases equivalent to
  `trim={"start": ..., "end": ...}`; conflicting values raise `ValueError` instead of
  silently ignoring one form.

Fixed
- Webhook signature verification now always uses the raw body bytes (never a re-serialized
  payload) and the `sha256=<hex>` format the server sends.

## 0.1.0

- Initial release: `downloads` (create / retrieve / list / cancel / `job.wait()`),
  `info`, typed error hierarchy, webhook signature verification, httpx-based sync + async
  clients.
