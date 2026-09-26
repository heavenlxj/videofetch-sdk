# VideoFetch MCP server

Give any AI agent the ability to download video/audio into your own object storage.

`videofetch-mcp` is the official [Model Context Protocol](https://modelcontextprotocol.io) server for
[VideoFetch](https://www.vidfetch.dev). It exposes six tools, so a chat assistant can go from
*"grab this clip as MP3 and put it in my bucket"* to a delivered file — no HTTP client, no polling
loop, no retry code.

```jsonc
// claude_desktop_config.json  ·  .cursor/mcp.json  ·  .vscode/mcp.json
{
  "mcpServers": {
    "videofetch": {
      "command": "uvx",
      "args": ["videofetch-mcp"],
      "env": { "VIDEOFETCH_API_KEY": "vf_live_sk_your_key" }
    }
  }
}
```

Claude Code, one line:

```bash
claude mcp add videofetch --env VIDEOFETCH_API_KEY=vf_live_sk_your_key -- uvx videofetch-mcp
```

No `uv`? `pipx install videofetch-mcp` and use `"command": "videofetch-mcp", "args": []`.

## Tools

| Tool | What it does |
|---|---|
| `video_info` | **Free** metadata lookup — title, duration, per-format size estimates. No quota consumed. |
| `download_media` | Create the job, wait a bounded time, optionally save the file locally. The main entry point. |
| `get_download` | Poll one job. Reports queue position while queued, and the reason + "nothing was charged" on failure. |
| `list_downloads` | Browse the account's jobs, filtered by status or keyword. |
| `cancel_download` | Cancel a running job or delete a finished one. Idempotent, never charged. |
| `account_usage` | Plan, month-to-date usage, remaining quota, PAYG balance, concurrency limits. |
| `list_storage` | Connected buckets (S3 / R2 / GCS / S3-compatible): `st_…` id, default, health. Read-only. |
| `redeliver_download` | After a failed upload to the user's bucket, push the held copy again — no re-download, no extra charge. |

## Design notes (why it behaves the way it does)

Built for models, not for humans, which changes a few defaults:

- **Few, high-level tools.** One call creates the job, waits, and reports where the file landed —
  instead of making the model orchestrate five endpoints.
- **Bounded blocking.** `download_media` blocks at most `wait_seconds` (server cap 120s by default).
  On expiry it returns `status=processing` with the job id — **a timeout is not an error**, because
  the work is still running server-side. Nothing is charged until a job reaches `completed`.
- **Errors are instructions.** Quota, auth, validation and rate-limit failures come back as a single
  actionable sentence (`quota_exceeded … top up or upgrade, then retry`) so the agent self-corrects
  instead of hallucinating.
- **Safe by default.** `save_to` may only write inside `VIDEOFETCH_MCP_OUTPUT_DIR`, and the server
  never accepts storage credentials — connect buckets in the dashboard and pass their `st_…` id as
  `destination_id` (or omit it to use the account's default storage).
- **Delivery failures are recoverable.** If the file downloaded but the bucket rejected it, the
  result carries the storage error code and a `hint`, the file is held for 24h, and
  `redeliver_download` finishes the job once the user has fixed the bucket.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VIDEOFETCH_API_KEY` | — | **Required.** `vf_live_sk_…` from Dashboard → API Keys. |
| `VIDEOFETCH_BASE_URL` | `https://api.vidfetch.dev` | Change for self-hosted / local deployments. |
| `VIDEOFETCH_MCP_MAX_WAIT` | `120` | Hard cap on one tool call's blocking time, seconds (max 600). |
| `VIDEOFETCH_MCP_HTTP_TIMEOUT` | `30` | Per-request HTTP timeout, seconds. |
| `VIDEOFETCH_MCP_OUTPUT_DIR` | server cwd | The only directory `save_to` may write into. |
| `VIDEOFETCH_MCP_ALLOW_ANY_PATH` | `0` | `1` removes that restriction. Not recommended for agents. |

## Verify

```bash
$ VIDEOFETCH_API_KEY=vf_live_sk_your_key uvx videofetch-mcp --selftest
server : videofetch 0.1.0
tools  : 6
  - video_info         Inspect a video (free)
  - download_media     Download video or audio
  ...
usage  : plan=developer used=0.0195GB remaining=99.98GB alert=ok

SELFTEST OK
```

Self-hosting over HTTP instead of per-client stdio:

```bash
VIDEOFETCH_API_KEY=... videofetch-mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

## Development

```bash
pip install -e ".[dev]"
pytest -q                                   # 32 offline tests (fake API + MCP protocol layer)

# opt-in live end-to-end (spends a few cents of real quota)
VIDEOFETCH_LIVE_KEY=vf_live_sk_... pytest tests/test_live.py -q
```

The test suite has three layers on purpose: tool logic against an in-memory API, the real MCP
handshake (tool schemas, `isError`, prompts), and an opt-in live run against production.

MIT licensed.
