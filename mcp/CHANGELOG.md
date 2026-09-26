# Changelog

## 0.2.0 — 2026-09-26

Added
- `list_storage` (read-only): connected buckets with their `st_…` ids, which one is the default,
  and health (`status`, last error). Credentials are never returned.
- `redeliver_download(job_id, destination_id=None, wait_seconds=60)`: after a delivery failure,
  upload the held copy again (or to another destination / `"url"`) — no re-download, no extra
  charge. Bounded wait like `download_media`.
- Delivery failures are returned, not raised: the result carries `error.stage="delivery"`,
  `provider_code`, `hint`, `redeliverable` and `hold_expires_at`, and `next_step` tells the model to
  relay the fix and call `redeliver_download`.
- Completed storage jobs report `destination_id` and `storage_uri` (`s3://…`, `r2://…`, `gs://…`).
- 422 `storage_*` and 409 `not_redeliverable` are translated into actionable messages.

Changed
- `download_media(destination_id=...)` sends the id as the `destination` string shorthand and
  accepts `"url"` to force a platform link. Omitting it now uses the account's default storage.
- Requires `videofetch-sdk>=0.5.0`.

## 0.1.0 — 2026-09-24

First release.

- Six tools over stdio (and optional streamable HTTP): `video_info`, `download_media`,
  `get_download`, `list_downloads`, `cancel_download`, `account_usage`.
- `download_media` performs create + bounded wait + optional local save in one call. A wait timeout
  returns `status=processing` with the job id instead of raising — the job keeps running server-side
  and nothing has been charged.
- Every result carries a `next_step` sentence so the model knows what to do next.
- API errors are translated into actionable messages (quota → top up, auth → fix the env var,
  validation → which field, rate limit → retry-after, failed job → not charged).
- `save_to` is confined to `VIDEOFETCH_MCP_OUTPUT_DIR`; storage credentials are never accepted
  (use a dashboard-created `destination_id`).
- `--selftest` verifies key + connectivity without an MCP client.
- Requires `videofetch-sdk>=0.4.0` and `mcp>=1.27,<2`. The `mcp` cap is deliberate: 2.x renamed
  `FastMCP` to `MCPServer` (`mcp.server.mcpserver`) and changed other APIs, so an unpinned install
  imports a module that no longer exists. v2 support will come as its own verified release.
- Tests: 35 offline (in-memory API + real MCP protocol handshake + version guard) and an opt-in
  live suite.
