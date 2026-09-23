# Changelog

## 0.3.0 — 2026-09-22

Added
- **Webhook delivery inspection:** `client.webhooks.deliveries(endpoint_id, limit=50)` returns a
  `WebhookDeliveriesResult` with the endpoint's current state, aggregate `health`
  (`total`/`succeeded`/`dead`/`pending`/`success_rate`, plus `max_attempts` and
  `retry_schedule_seconds`), and the recent `items` (each a `WebhookDelivery`).
- **Webhook replay:** `client.webhooks.replay(event_id)` re-queues a past event and returns a
  `ReplayResult(queued, event_id)`. A `NotFoundError` means the delivery is not visible to your
  account.
- **Idempotency helpers:** `delivery_id(headers)` and `attempt_number(headers)` read the new
  `X-VideoFetch-Delivery` and `X-VideoFetch-Attempt` headers case-insensitively.
- **Queue hints on queued downloads:** `Download.queue_position` (1 == next to be claimed),
  `ahead_of_you`, and `estimated_wait_seconds`. All three are populated only while
  `status == "queued"` and are `None` in every other state.
- **Per-key usage attribution:** `Usage.key_used_bytes` / `Usage.key_used_gb` report this key's own
  accumulated usage, alongside the account-level figures.
- **Save the result locally:** `client.downloads.download_to(download_id, path=None)` (and the async
  `await client.downloads.download_to(...)`) streams a completed job's file to disk in chunks and
  returns the absolute path of the saved file. With no destination configured for the job the
  platform issues a time-limited, self-authorizing `download_url`, and this method saves it for you —
  to `<sanitized title or job id>.<mp3|mp4>` in the current directory by default, or to the file path
  (or existing directory) you pass. The API key is never sent to that link; if it has expired the
  server re-signs it on the next job fetch and the save is retried once. Preconditions are typed:
  a non-completed job raises `DownloadNotCompletedError`, and a completed job without a
  `download_url` raises `DownloadURLUnavailableError`.

Changed (breaking)
- **Attempt records no longer expose a raw egress host.** `DownloadAttempt.egress` replaces the
  0.2.0 host field and carries a neutral label: `"relay"` when the attempt was served through an
  alternate route, `null` for a direct attempt. Internal egress hosts are not part of the public
  contract.
- **The strategy vocabulary is now `"direct" | "relay" | "relay_secondary"`** for both
  `Download.strategy` and `DownloadAttempt.strategy`. Any value outside the vocabulary is
  normalised to `"relay"`.
- Attempt `error_message` strings are scrubbed of egress addresses and credentials before they are
  returned to you.
- **`Usage.used_bytes` / `Usage.used_gb` are now account-level.** They report the whole account's
  current-month billable usage (the quota is account-level and shared by every key), not the calling
  key's usage. Use the new `key_used_bytes` / `key_used_gb` for per-key attribution.
- **Downloads are account-level visible.** `GET /v1/downloads` (list) and
  `GET /v1/downloads/{id}` (detail) now return every job owned by the account, regardless of which
  key created it; any key in the account may also cancel/delete any of the account's jobs.
- **Webhook delivery semantics changed.** Deliveries are now **at-least-once**: the same event may be
  delivered more than once. Retries are capped at **3 attempts** (the first send counts as attempt 1;
  the previous limit was 5) with a 30s → 300s backoff (±20% jitter). **4xx responses are permanent
  failures and are not retried**, except `408` and `429`. **Ordering is not guaranteed** — sort by
  each event's `seq`. New headers accompany every attempt:
  - `X-VideoFetch-Delivery` — stable per-event idempotency key.
  - `X-VideoFetch-Attempt` — the attempt number (1 = first).
  - `X-VideoFetch-Timestamp` — when the attempt was sent.
  `X-VideoFetch-Event` and `X-VideoFetch-Signature` are unchanged.

Migration
- If you read the raw host field from 0.2.0, read `egress` instead — it is a label, not a hostname.
- Branch on `strategy == "direct"` vs anything else. Pin `videofetch-sdk==0.2.*` if you need the old
  response shape while you migrate.
- **Deduplicate webhooks by `X-VideoFetch-Delivery`.** Because delivery is at-least-once, persist the
  delivery id (e.g. a unique index) and skip events you have already processed. Use
  `videofetch.delivery_id(request.headers)` and `videofetch.attempt_number(request.headers)` in your
  handler, and order events by `seq` rather than arrival time.
- If you displayed `used_gb` as a per-key number, switch to `key_used_gb` for that, or keep
  `used_gb` and relabel it as account-level month usage.
- Downloads created by other keys in your account may now appear in list/detail results. If you need
  per-key filtering, record the creating key on your side.

