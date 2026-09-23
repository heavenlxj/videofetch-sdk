# Changelog

All notable changes to `@videofetch/sdk` are documented here.
This project follows [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-09-22

### Added

- **`client.downloads.downloadTo(id, path?)`** — stream a completed job's file
  straight to a local file (Node.js only) and return the **absolute path**
  written. With no `path` the name is derived in the current directory as
  `<sanitized title|id>.<mp3|mp4>` (a directory or trailing separator writes the
  derived name inside it). The file is streamed in chunks, never fully buffered.
- **`client.downloads.downloadBytes(id)`** — return the finished file as a
  `Uint8Array` in **any** runtime (Node, browsers, edge) so the caller can
  persist it (e.g. as a `Blob`). Both helpers fetch the self-authorising
  download link **without** the API key, and re-sign + retry once on a `403`
  (expired link). `downloadTo()` throws a clear error outside Node — use
  `downloadBytes()` there. Also exported: `defaultDownloadFileName()` /
  `sanitizeFileStem()`.
- **`client.webhooks.deliveries(endpointId, limit?)`** → `GET /v1/webhooks/{endpoint_id}/deliveries` —
  recent delivery history (`WebhookDelivery` items with `seq`, `status`, `attempts`,
  `max_attempts`, `last_status_code`, `last_error`, `next_attempt_at`) plus endpoint
  health (`WebhookDeliveryHealth`) and the backoff schedule (`retry_schedule_seconds`).
- **`client.webhooks.replay(eventId)`** → `POST /v1/webhooks/deliveries/{event_id}/replay` —
  re-queue one recorded delivery (`{queued, event_id}`); the replay keeps the original
  `event_id`.
- **Webhook request headers**: `X-VideoFetch-Delivery` (the event id — an **idempotency
  key**), `X-VideoFetch-Attempt` (1-based attempt number) and `X-VideoFetch-Timestamp`,
  on top of the existing `X-VideoFetch-Event` / `X-VideoFetch-Signature`.
- Exported helpers **`getDeliveryId(headers)`** and **`getAttemptNumber(headers)`**
  (case-insensitive header lookup) so a consumer can de-duplicate deliveries easily.
- **Queue progress on `Download`**: `queue_position`, `ahead_of_you` and
  `estimated_wait_seconds` (populated only while `status === "queued"`, `null` otherwise).
- **Per-key usage on `Usage`**: `key_used_bytes` / `key_used_gb`.

### Changed (breaking)

- **Webhook delivery semantics.** At most **3** delivery attempts per event (the first
  counts; 0.2.0 allowed up to 5), with a `30s → 300s` backoff (±20%). A **4xx** response
  (except `408` / `429`) is a **permanent failure** and is not retried. Delivery is
  **at-least-once** — the same event may arrive more than once (retries and manual
  replays) — and events are **not** guaranteed to arrive in order; sort by
  `WebhookDelivery.seq`. De-duplicate on `X-VideoFetch-Delivery` (see `getDeliveryId`).
- **`Usage.used_bytes` / `used_gb` are now account-level** for the current month (0.2.0
  reported a single key's usage). Per-key usage moved to
  `key_used_bytes` / `key_used_gb`.
- **`GET /v1/downloads` list and detail are account-level visible**: any API key of the
  account can see (and delete) that account's jobs.

- **Attempt records no longer expose a raw egress host.** `DownloadAttempt.egress` replaces the
  0.2.0 host field with a neutral label: `"relay"` when the attempt was served through an alternate
  route, `null` for a direct attempt. Internal egress hosts are not part of the public contract.
- **`DownloadStrategy` is now `"direct" | "relay" | "relay_secondary"`** for both
  `Download.strategy` and `DownloadAttempt.strategy`. Values outside the vocabulary are normalised
  to `"relay"`.
- Attempt `error_message` values are scrubbed of egress addresses and credentials before being
  returned.

### Migration

- If you read the raw host field from 0.2.0, read `egress` instead — it is a label, not a hostname.
- Branch on `strategy === "direct"` vs anything else. Pin `@videofetch/sdk@0.2.x` if you need the
  old response shape while you migrate.

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
