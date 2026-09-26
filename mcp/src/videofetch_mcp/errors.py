"""API/SDK 异常 → **可行动**的 MCP 工具错误。

Agent 场景下错误信息就是 prompt: 模型只能看到我们给它的那句话。所以每个错误都必须回答
"接下来怎么办" —— 重试? 换格式? 换 URL? 让用户充值? 还是这个 URL 根本就不支持?

对照表 (与后端错误码一一对应, 见公开文档 Error codes):
  401 authentication_error  →  key 缺失/无效 → 改配置
  402 quota_exceeded        →  额度用尽 → 充值/升级 (带上剩余额度与单价)
  403 permission_denied     →  这把 key 没权限
  404 not_found             →  job id 不存在 → 用 list_downloads 找
  409 conflict              →  not_redeliverable → 查状态/重下
  422 storage_*             →  存储配置被拒 → list_storage 找正确 id, 带 hint
  422 validation_error      →  参数错 → 指出哪个字段
  429 rate_limit_exceeded   →  并发/频率 → 带 Retry-After
  5xx api_error             →  服务端 → 可重试
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp.exceptions import ToolError

from videofetch import errors as vf_errors


def _detail(exc: Exception) -> str:
    """尽量从异常里挖出后端给的详情/字段名 (模型需要它来改参数)。"""
    msg = getattr(exc, "message", None)
    param = getattr(exc, "param", None)
    if isinstance(msg, str) and msg.strip():
        return f"{msg.strip()}" + (f" (param: {param})" if param else "")
    if isinstance(param, str) and param:
        return f"param: {param}"
    return ""


def to_tool_error(exc: Exception) -> ToolError:
    """把 SDK 异常翻译成给模型看的一句话。未知异常也兜住 (绝不裸抛 traceback)。"""
    if isinstance(exc, ToolError):
        return exc

    if isinstance(exc, vf_errors.AuthenticationError):
        return ToolError(
            "authentication_error: the API key was rejected. Fix VIDEOFETCH_API_KEY in this MCP "
            "server's env (Dashboard -> API Keys; the full key is shown only once at creation) "
            "and restart the server. Do not retry this call as-is."
        )
    if isinstance(exc, vf_errors.PermissionDeniedError):
        return ToolError(
            "permission_denied: this API key is not allowed to do that (or the account is "
            f"suspended). {_detail(exc)} Ask the user to check the key and account in the "
            "VideoFetch dashboard. Do not retry this call as-is."
        )
    if isinstance(exc, vf_errors.QuotaExceededError):
        rem = getattr(exc, "remaining_gb", None)
        extra = f" Remaining quota: {rem} GB." if rem is not None else ""
        return ToolError(
            f"quota_exceeded: the account has no billable quota left.{extra} "
            "Completed jobs bill max(size, 20 MiB) each; failed jobs are free. "
            "Next step: tell the user to top up pay-as-you-go credit or upgrade the plan, then "
            "retry. Retrying now will fail the same way."
        )
    if isinstance(exc, vf_errors.StorageError):
        code = getattr(exc, "code", None) or "storage_error"
        hint = getattr(exc, "hint", None)
        return ToolError(
            f"{code}: the storage destination was rejected — {_detail(exc) or 'check destination_id'}."
            + (f" Fix: {hint}." if hint else "")
            + " Call list_storage to see valid st_… ids, or omit destination_id to use the default "
              "storage (pass \"url\" for a platform link). Never ask the user for credentials."
        )
    if isinstance(exc, vf_errors.ConflictError):
        code = getattr(exc, "code", None)
        if code == "not_redeliverable":
            return ToolError(
                "not_redeliverable: this job cannot be redelivered — it did not fail at the delivery "
                "stage, or its held copy expired (24h). Check get_download; if needed run "
                "download_media again."
            )
        return ToolError(f"{code or 'conflict'}: {_detail(exc) or exc}")
    if isinstance(exc, vf_errors.ValidationError):
        return ToolError(
            f"validation_error: the request was rejected — {_detail(exc) or 'check the arguments'}. "
            "Common causes: format must be one of 144p/240p/360p/480p/720p/1080p/1440p/2160p/mp3; "
            "trim needs end > start and both >= 0; the URL must be a public video page URL."
        )
    if isinstance(exc, vf_errors.NotFoundError):
        return ToolError(
            "not_found: no such resource for this account. For a job id, list_downloads will show "
            "the ids that exist (ids look like dl_xxxxxxxxxx). Do not invent ids."
        )
    if isinstance(exc, vf_errors.RateLimitError):
        ra = getattr(exc, "retry_after", None)
        return ToolError(
            "rate_limit_exceeded: too many concurrent jobs or requests"
            + (f"; retry after {ra:g}s" if ra is not None else "")
            + ". Queue up to 50 and 5 in flight are allowed per account. "
              "Wait, then retry — or submit in smaller batches."
        )
    if isinstance(exc, vf_errors.DeliveryFailedError):
        hint = getattr(exc, "hint", None)
        return ToolError(
            f"{exc.error_code or 'delivery_failed'}: the video downloaded but could not be written to "
            f"the user's storage — nothing was charged. {exc.error_message or ''}".rstrip()
            + (f" Fix: {hint}." if hint else "")
            + (f" Then call redeliver_download('{exc.job_id}')." if exc.redeliverable else
               " The held copy expired; run download_media again after fixing it.")
        )
    if isinstance(exc, vf_errors.JobFailedError):
        msg = getattr(exc, "error_message", None) or getattr(exc, "error_code", None) or "unknown"
        return ToolError(
            f"download_failed: the job ended in 'failed' — nothing was charged. Reason: {msg}. "
            "Usual causes: the video is private/age-restricted/region-blocked, the requested "
            "format does not exist for it, or the source blocked our egress for this attempt. "
            "Retrying the identical request is unlikely to help — check the video is public and "
            "publicly embeddable first."
        )
    if isinstance(exc, vf_errors.DownloadNotCompletedError):
        return ToolError(
            "download_not_completed: the artifact is not available yet. Poll the job with "
            "get_download until status == 'completed', then retry."
        )
    if isinstance(exc, vf_errors.DownloadURLUnavailableError):
        return ToolError(
            "download_url_unavailable: this job was delivered straight to your own storage, so "
            "the platform has no download link for it (that is by design — the file never lands "
            "in our bucket). Read it from your bucket using storage_key, or re-run without "
            "destination_id to get a platform-hosted link."
        )
    if isinstance(exc, vf_errors.VideoFetchError):
        code = getattr(exc, "code", None) or "error"
        status = getattr(exc, "status_code", None)
        if code == "job_timeout":
            return ToolError(
                "job_timeout: the job is still running server-side — this is not a failure and "
                "nothing was charged. Call get_download with the job_id (or list_downloads) to "
                "pick it up; or ask the user to configure a webhook_url so no polling is needed."
            )
        if status is None:
            return ToolError(f"network_error: could not reach the VideoFetch API. {_detail(exc)} "
                             "Check connectivity/base URL, then retry.")
        return ToolError(f"{code}: {_detail(exc) or exc}" + (
            " (transient — safe to retry)" if status and status >= 500 else ""))
    # 未知异常: 兜住, 不让 traceback 直接抛给模型 (它看不懂, 而且可能带内部路径)
    return ToolError(f"unexpected_error: {type(exc).__name__}: {str(exc)[:300]}")


def guard(fn: Any) -> Any:
    """装饰器: 把任意异常翻译成 ToolError。"""
    import functools

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001 — 这里就是要兜住一切
            raise to_tool_error(e) from None

    return wrapper
