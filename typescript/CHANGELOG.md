# Changelog

All notable changes to `@videofetch/sdk` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-09-21

### Added

- **`client.usage`** resource:
  - `usage.get()` → `GET /v1/usage` — plan, `quota_gb`, month-to-date usage
    (`account_used_bytes_month` / `account_used_gb_month`), `remaining_gb`,
    pay-as-you-go balance/rate, `used_pct`, `active_jobs`, `concurrency_limit`
    and the live `alert_level` / `alert_message`.
  - `usage.alerts()` → `GET /v1/usage/alerts` — alert `state` (crossed
    thresholds, `next_threshold_pct`, balance hints, `action`), the `fired`
    alert history, `thresholds` (`[80, 95, 100]`) and `topup_amounts`.
- **`client.webhooks`** resource (account-level, API-key authenticated — no JWT):
  - `webhooks.create(url, events?)` → `201` with the **full plaintext secret**
    (returned only once).
  - `webhooks.list()` → endpoints with the secret **masked**.
  - `webhooks.test(id)` → sends a `webhook.test` ping and reports
    `{delivered, url, last_status, signature_header, signature_format}`.
  - `webhooks.delete(id)` → `204`.
  - Event catalogue extended with `quota.warning`, `quota.exceeded`,
    `balance.low` (exported as `WEBHOOK_EVENTS`).
- **Typed error semantics**:
  - `RateLimitError` (429) now carries `code`
    (`concurrency_limit_exceeded` | `queue_limit_exceeded` |
    `platform_at_capacity`), `limit`, `active`, `scope` and `retryAfter`
    (parsed from the `Retry-After` header; falls back to
    `X-Concurrency-Limit` / `X-Concurrency-Active`).
  - `QuotaExceededError` (402) exposes `remainingGb`.
  - `PermissionDeniedError` (403) exposes `.code`, e.g. `account_suspended`.

### Changed

- `constructEvent()` now throws `SignatureVerificationError` (not a native
  `TypeError`) when handed an already-parsed object instead of the raw body.
- `mapError()` accepts the response headers so 429 semantics are preserved.

## [0.1.0] — 2025-09-03

### Added

- Initial release: `downloads` (create / retrieve / list / cancel /
  `createAndWait` with polling `wait()`), `info.lookup`, webhook signature
  verification (`constructEvent` / `computeSignature`) and the typed error
  hierarchy. Zero runtime dependencies (global `fetch`).
