# Changelog

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
