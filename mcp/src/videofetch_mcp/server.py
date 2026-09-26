"""VideoFetch MCP server — 让任何 Agent 直接把视频/音频下到用户自己的对象存储。

════════════════════════════════════════════════════════════════════════════
设计原则 (面向 **Agent**, 不是面向人类 CLI —— 改动前先读)
════════════════════════════════════════════════════════════════════════════
1. **工具少而高**: 8 个工具覆盖全流程。一次工具调用尽量把事做完 (建单 + 有界等待 + 落盘),
   而不是把 5 个 HTTP 端点摊成 5 个工具让模型自己串 —— 模型串得越多, 失败和幻觉越多。
2. **返回值是给模型看的**: 字段做减法 (只留决策要用的), 字节/时长带人类可读形式, 并附
   `next_step`。见 `formatting.py`。
3. **有界阻塞**: 工具自己等, 但有上限 (`VIDEOFETCH_MCP_MAX_WAIT`, 默认 120s, 硬顶 600s)。
   超时**不是失败** —— 返回 `status=processing` + job_id, 让模型去轮询, 绝不把 Agent 卡死。
4. **失败要能自我纠正**: API 错误翻译成"可行动"的一句话 (含剩余额度/retry_after/下一步),
   见 `errors.py`。模型只看得见我们给它的那句话。
5. **默认安全**: `save_to` 只能在白名单目录内 (防模型往 ~/.ssh 写东西); **不接受内联存储凭据**
   (凭据进 prompt 就等于进日志)。要直传存储就用 Dashboard 建好的 st_ id (list_storage 可查)。

工具清单:
  video_info         免费元数据 + 各格式预估体积 (不消耗额度)
  download_media     建单 + 有界等待 (+ 可选落盘) ← 主力工具
  get_download       查单个任务 (轮询用; 含排队位置)
  list_downloads     列任务 (支持 status/keyword 过滤)
  cancel_download    取消/删除任务 (未完成的会停止, 不计费)
  account_usage      套餐/用量/剩余额度/并发
  list_storage       已连接的存储 (st_ id / 是否默认 / 健康状态), 只读
  redeliver_download 投递失败后用保留副本重新上传 (不重下、不重复计费)
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from typing import TYPE_CHECKING, Annotated, Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import config as cfg_mod
from . import formatting as fmt
from .errors import guard, to_tool_error

if TYPE_CHECKING:  # 只为类型标注, 运行时才 import (缺依赖时也能 import 本模块报友好错)
    from videofetch import VideoFetch

SERVER_NAME = "videofetch"
SERVER_VERSION = "0.2.0"

Format = Literal["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "mp3"]

INSTRUCTIONS = """\
VideoFetch turns a public video URL into a downloadable file — either a temporary link hosted by us,
or straight into object storage the user already connected (S3 / Cloudflare R2 / GCS / S3-compatible).

How to work with it:
1. `video_info(url)` is FREE (no quota). Use it when the user has not pinned a format, or before a
   batch, so you can state duration/size/cost up front.
2. `download_media(url, format, ...)` creates the job and waits a bounded time.
   - format: one of 144p / 240p / 360p / 480p / 720p / 1080p / 1440p / 2160p / mp3
   - start / end: download only that time window (seconds, end exclusive-ish) — this is how you make
     clips or grab a single song out of a long video, and it saves transfer.
   - save_to: have this server write the file to a local path (must live inside the configured
     output directory). Use it when the user asked for "the file on my machine".
   - destination_id: deliver straight into the user's own bucket. Omit it and the account's default
     storage connection is used (or a platform link when there is none); `list_storage()` shows the
     connected buckets and their `st_…` ids; pass "url" to force a platform link. The user connects
     buckets in the VideoFetch dashboard — never ask for or pass credentials.
3. If the result says status=queued/processing, the job is still running server-side: call
   `get_download(job_id)` again a little later. Nothing is broken, nothing was charged yet.
4. If the file downloaded but could not be written to the bucket (`error.stage == "delivery"`), the
   file is held for 24h. Tell the user what to fix (the `hint`), then call
   `redeliver_download(job_id)` — no re-download, no extra charge.

Billing: each COMPLETED job bills max(size, 20 MiB) once, at the account's per-GB rate. Failed and
cancelled jobs are never charged. Call `account_usage()` before large batches.
Never invent a job id, and never ask the user for storage credentials.
"""

mcp: FastMCP = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS, website_url="https://www.vidfetch.dev")

# ── 客户端缓存 ───────────────────────────────────────────────────────────────
# 为什么缓存: 轮询/批量场景下每次工具调用都新建 httpx.Client 会丢掉连接复用。
# 为什么按 (key, base_url) 分桶: 同进程可能被同时指向 dev 与线上 (测试就是这么干的)。
_CLIENTS: dict[tuple[str, str], "VideoFetch"] = {}
_CLIENT_LOCK = threading.Lock()

# 测试注入口: 生产走真实 SDK; 测试把它换成"指向假 API / 桩传输"的构造器, 这样 6 个工具的行为
# (含错误翻译、落盘、有界等待) 能在**没有网络**的情况下逐个断言。
client_factory = None  # type: ignore[var-annotated]


def get_client(cfg: cfg_mod.Config) -> "VideoFetch":
    """按需构造 SDK 客户端。缺 key 时给出**可行动**的报错, 而不是裸 ValueError。"""
    if not cfg.has_key:
        raise ToolError(
            "missing_api_key: VIDEOFETCH_API_KEY is not set for this MCP server. "
            "Add it to the server's env block in your MCP client config "
            "(get a key from the VideoFetch dashboard -> API Keys; the full key is shown once at "
            "creation), then restart the MCP server."
        )
    bucket = (cfg.api_key, cfg.base_url)
    with _CLIENT_LOCK:
        client = _CLIENTS.get(bucket)
        if client is None:
            factory = client_factory
            if factory is None:
                from videofetch import VideoFetch as factory  # noqa: N813
            client = factory(api_key=cfg.api_key, base_url=cfg.base_url, timeout=cfg.http_timeout)
            _CLIENTS[bucket] = client
    return client


def reset_clients() -> None:
    """测试/热重载用: 丢掉缓存的客户端。"""
    with _CLIENT_LOCK:
        for c in _CLIENTS.values():
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass
        _CLIENTS.clear()


# ── save_to 目录白名单 ───────────────────────────────────────────────────────
def _wait_bounded(job, budget: int):
    """有界等待。超时**不是失败**: 刷新拿最新状态 (含排队位置) 后照常返回, 让模型去轮询。

    投递失败 (文件已下好, 写不进用户的桶) 也不抛: 返回带 error/hint 的结果, 模型才能让用户修桶
    然后 redeliver_download; 其余失败 (源站/网络) 交给 guard 翻译。
    """
    from videofetch import DeliveryFailedError

    if budget <= 0:
        return job.download
    try:
        return job.wait(timeout=budget)
    except DeliveryFailedError as e:
        return e.download
    except Exception as e:  # noqa: BLE001
        if getattr(e, "code", None) == "job_timeout":
            return job.refresh()
        raise


def guard_save_path(raw: Optional[str], cfg: cfg_mod.Config) -> Optional[str]:
    """把模型给的路径约束在输出目录内。

    这不是"防用户", 是"防模型": 工具参数由 LLM 填, 把写文件的能力加上白名单, 才能让
    "模型把东西写到 ~/.ssh/authorized_keys / /etc/..." 这类事故从"可能"变成"不可能"。
    """
    if raw is None or not str(raw).strip():
        return None
    p = os.path.abspath(os.path.expanduser(str(raw).strip()))
    if cfg.allow_any_path:
        return p
    root = os.path.realpath(cfg.output_dir)
    looks_like_dir = str(raw).strip().endswith(os.sep) or os.path.isdir(p)
    probe = p if looks_like_dir else os.path.dirname(p)
    probe = os.path.realpath(probe or root)
    inside = probe == root or probe.startswith(root + os.sep)
    if not inside:
        raise ToolError(
            f"save_to_rejected: '{p}' is outside the allowed output directory '{root}'. "
            "Pass a path inside that directory (or a relative filename), or ask the user to set "
            "VIDEOFETCH_MCP_OUTPUT_DIR / VIDEOFETCH_MCP_ALLOW_ANY_PATH=1 if that is really intended."
        )
    return p


# ── 工具 ─────────────────────────────────────────────────────────────────────
@mcp.tool(
    title="Inspect a video (free)",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@guard
def video_info(
    url: Annotated[str, Field(description="Public video page URL, e.g. https://www.youtube.com/watch?v=…")],
) -> dict:
    """Look up title, channel, duration and per-format size estimates. **Free — consumes no quota.**

    Call this first when the user has not chosen a format, or before a batch, so you can quote
    duration/size/cost before anything is spent. Also the cheapest way to validate a URL and get its
    video_id (useful for cache keys / file names) without downloading.
    """
    cfg = cfg_mod.load()
    info = get_client(cfg).info.lookup(url)
    return fmt.shape_info(info)


@mcp.tool(
    title="Download video or audio",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
@guard
def download_media(
    url: Annotated[str, Field(description="Public video page URL to download.")],
    format: Annotated[Format, Field(description="Target quality: 144p-2160p MP4, or mp3 for audio only.")] = "720p",
    start: Annotated[Optional[float], Field(description="Clip window start in seconds (optional). Use with end to download only a slice.")] = None,
    end: Annotated[Optional[float], Field(description="Clip window end in seconds (optional). Must be greater than start.")] = None,
    destination_id: Annotated[Optional[str], Field(description="Storage id (st_…) of a bucket the user connected in the VideoFetch dashboard — see list_storage. Omit to use the account's default storage (or a platform link if none); pass \"url\" to force a temporary platform link.")] = None,
    webhook_url: Annotated[Optional[str], Field(description="HTTPS URL to be notified at when the job finishes (avoids polling entirely).")] = None,
    save_to: Annotated[Optional[str], Field(description="Local file path (or directory) to write the artifact to once it completes. Must be inside the server's allowed output directory.")] = None,
    wait_seconds: Annotated[int, Field(description="How long this call may block waiting for the job (0 = return immediately with the job id). Capped by the server config.")] = 120,
) -> dict:
    """Download a video (or a clip, or just the audio) and return where the file ended up.

    Blocking is bounded: if the job is not finished within `wait_seconds` this returns
    `status=queued|processing` plus the `job_id` — call `get_download(job_id)` to finish it off.
    Nothing is charged unless the job reaches `completed`.

    Tips: for "make me a clip" pass start/end; for "just the audio" pass format="mp3"; for "put it in
    my bucket" pass destination_id; for "save it on my machine" pass save_to.
    If the upload to the user's bucket fails, the result has `error.stage="delivery"` and a `hint`;
    fix it with the user, then call redeliver_download.
    """
    cfg = cfg_mod.load()
    client = get_client(cfg)

    if start is not None and start < 0:
        raise ToolError("invalid_trim: start must be >= 0.")
    if end is not None and end <= 0:
        raise ToolError("invalid_trim: end must be > 0.")
    if start is not None and end is not None and end <= start:
        raise ToolError(f"invalid_trim: end ({end}) must be greater than start ({start}).")

    target = guard_save_path(save_to, cfg)
    budget = max(0, min(int(wait_seconds or 0), cfg.max_wait_seconds))

    from videofetch import TrimSpec

    trim = TrimSpec(start=start, end=end) if (start is not None or end is not None) else None
    job = client.downloads.create(
        url, format,
        trim=trim,
        # 字符串简写 "st_…" / "url": 真实 provider / 凭据由后端从库里取, 模型永远碰不到凭据
        destination=destination_id.strip() if destination_id and destination_id.strip() else None,
        webhook_url=webhook_url,
    )

    dl = _wait_bounded(job, budget)

    saved: Optional[str] = None
    if target and dl.status == "completed":
        saved = client.downloads.download_to(dl.id, target)

    return fmt.shape_download(dl, cfg=cfg, saved_path=saved)


@mcp.tool(
    title="Get one download",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@guard
def get_download(
    job_id: Annotated[str, Field(description="Job id returned by download_media, e.g. dl_ab12cd34ef.")],
    include_attempts: Annotated[bool, Field(description="Also return the per-attempt channel log (useful when a job failed).")] = False,
) -> dict:
    """Check a job's current state — poll this after `download_media` returned queued/processing.

    While the job is queued you also get `queue.position` / `estimated_wait_seconds`. On success you
    get the artifact location (`download_url` or `storage_key`); on failure you get the reason and a
    reminder that nothing was charged.
    """
    cfg = cfg_mod.load()
    dl = get_client(cfg).downloads.retrieve(job_id)
    return fmt.shape_download(dl, cfg=cfg, include_attempts=include_attempts)


@mcp.tool(
    title="List downloads",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@guard
def list_downloads(
    status: Annotated[Optional[Literal["queued", "processing", "completed", "failed", "deleted"]], Field(description="Only return jobs in this state.")] = None,
    query: Annotated[Optional[str], Field(description="Free-text match against the video title / url.")] = None,
    limit: Annotated[int, Field(description="Page size (1-100).")] = 20,
    offset: Annotated[int, Field(description="Skip this many jobs (paging).")] = 0,
) -> dict:
    """List this account's download jobs, newest first. Use it to recover a job id you lost, to check
    what is still running, or to summarise recent activity for the user.
    """
    cfg = cfg_mod.load()
    res = get_client(cfg).downloads.list(status=status, q=query,
                                         limit=max(1, min(100, int(limit or 20))),
                                         offset=max(0, int(offset or 0)))
    return fmt.shape_list(res, cfg=cfg, limit=int(limit or 20))


@mcp.tool(
    title="Cancel a download",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True),
)
@guard
def cancel_download(
    job_id: Annotated[str, Field(description="Job id to cancel/delete.")],
) -> dict:
    """Cancel a queued/running job, or delete a finished one. Cancelled work is NOT charged.

    Safe to call in any state (idempotent). Confirm with the user before cancelling a job that is
    already `processing` if they might still want the result.
    """
    cfg = cfg_mod.load()
    client = get_client(cfg)
    before = client.downloads.retrieve(job_id)
    client.downloads.cancel(job_id)
    return fmt._drop_empty({
        "ok": True,
        "job_id": job_id,
        "status_before": before.status,
        "status_after": "deleted",
        "charged": False,
        "next_step": "Cancelled — nothing was charged for this job.",
    })


@mcp.tool(
    title="Account usage & quota",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@guard
def account_usage() -> dict:
    """Plan, current-month usage, remaining quota, pay-as-you-go balance and concurrency limits.

    Quota is account-wide (every API key shares it). Call this before a large batch so you can warn
    the user if they are close to the limit instead of failing mid-run.
    """
    cfg = cfg_mod.load()
    return fmt.shape_usage(get_client(cfg).usage.get())


@mcp.tool(
    title="List connected storage",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True),
)
@guard
def list_storage() -> dict:
    """The buckets (S3 / R2 / GCS / S3-compatible) the user connected, with their `st_…` ids.

    Pass an id as `destination_id` to download_media. The default connection is used automatically
    when destination_id is omitted. A connection with status "failing" will reject uploads until the
    user fixes it in the dashboard (the last error says why). Credentials are never returned.
    """
    cfg = cfg_mod.load()
    return fmt.shape_storage_list(get_client(cfg).storage.list())


@mcp.tool(
    title="Retry delivery to storage",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
)
@guard
def redeliver_download(
    job_id: Annotated[str, Field(description="Job whose upload to storage failed (error.stage == \"delivery\").")],
    destination_id: Annotated[Optional[str], Field(description="Deliver somewhere else instead: a storage id (st_…) or \"url\" for a platform link. Omit to retry the original bucket.")] = None,
    wait_seconds: Annotated[int, Field(description="How long this call may block waiting for the upload (0 = return immediately).")] = 60,
) -> dict:
    """Upload a held file again after a delivery failure — no re-download and no extra charge.

    Only works while the job is `failed` at the delivery stage and the hold has not expired
    (`redeliverable: true`, 24h). Fix the cause first (the previous result's `hint`), or pass another
    destination_id. Blocking is bounded like download_media.
    """
    cfg = cfg_mod.load()
    client = get_client(cfg)
    dest = destination_id.strip() if destination_id and destination_id.strip() else None
    job = client.downloads.redeliver(job_id, destination=dest)
    budget = max(0, min(int(wait_seconds or 0), cfg.max_wait_seconds))
    return fmt.shape_download(_wait_bounded(job, budget), cfg=cfg)


# ── 提示模板 (MCP prompt): 让客户端一键起手 ──────────────────────────────────
@mcp.prompt(title="Download a video into my storage")
def download_prompt(url: str, format: str = "720p") -> str:
    """Guided prompt: download one video and report back with the details that matter."""
    return (
        f"Download {url} as {format} using the videofetch tools, then report back.\n\n"
        "Steps:\n"
        "1. video_info(url) to confirm the title/duration and that the format exists.\n"
        f"2. download_media(url, format=\"{format}\") — if it comes back queued/processing, keep "
        "calling get_download(job_id) until it is terminal.\n"
        "3. Summarise: title, duration, final size, where the file went (link or storage uri), and "
        "the cost. If it failed, say why and confirm nothing was charged. If only the delivery to "
        "storage failed, relay the hint and offer redeliver_download once it is fixed."
    )


# ── 入口 ─────────────────────────────────────────────────────────────────────
def selftest() -> int:
    """`videofetch-mcp --selftest`: 不接 MCP 客户端也能验证配置是否可用。"""
    import asyncio

    async def _run() -> int:
        tools = await mcp.list_tools()
        print(f"server : {SERVER_NAME} {SERVER_VERSION}")
        print(f"tools  : {len(tools)}")
        for t in tools:
            print(f"  - {t.name:18s} {t.title or ''}")
        c = cfg_mod.load()
        print(f"base   : {c.base_url}")
        print(f"key    : {'set (' + c.api_key[:12] + '…)' if c.has_key else 'MISSING'}")
        print(f"outdir : {c.output_dir}   (any path allowed: {c.allow_any_path})")
        if not c.has_key:
            print("\nNo VIDEOFETCH_API_KEY — set it and re-run to exercise the API.")
            return 2
        try:
            u = account_usage()
            print(f"\nusage  : plan={u.get('plan')} used={u.get('used_gb')}GB "
                  f"remaining={u.get('remaining_gb')}GB alert={u.get('alert_level')}")
            print("\nSELFTEST OK")
            return 0
        except ToolError as e:
            print(f"\nSELFTEST FAILED: {e}")
            return 1

    return asyncio.run(_run())


def main(argv: Optional[list[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="videofetch-mcp",
                                 description=(__doc__ or "VideoFetch MCP server").split("\n")[0])
    ap.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio",
                    help="stdio (默认, 由 MCP 客户端拉起) 或 streamable-http (自托管/远程)")
    ap.add_argument("--host", default="127.0.0.1", help="HTTP 传输的监听地址")
    ap.add_argument("--port", type=int, default=8765, help="HTTP 传输的端口")
    ap.add_argument("--selftest", action="store_true", help="不接客户端, 打印工具清单并试调一次 API")
    args = ap.parse_args(argv)

    if args.selftest:
        sys.exit(selftest())

    if args.transport == "streamable-http":
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
