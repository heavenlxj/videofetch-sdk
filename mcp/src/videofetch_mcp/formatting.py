"""把 SDK 对象压成**给模型看的**返回值。

三条纪律 (改动前先读):
  1. **做减法**: 只留"下一步决策要用"的字段。`Download` 有 30+ 字段, 全塞进去既烧 token 又
     让模型抓不住重点; 冷字段 (upload_date / processing_time_ms / attempt_details) 只在被问到时给。
  2. **人话 + 数字并存**: 字节/时长给出人类可读形式 (`size_human`) —— 模型复述给用户时不用心算。
  3. **附 next_step**: 工具不只要给结论, 还要告诉模型下一步该做什么 (轮询? 落盘? 让用户充值?)。
     这是 Agent 场景下最省来回的一招。
"""

from __future__ import annotations

from typing import Any, Optional

_UNITS = (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024))


def human_bytes(n: Optional[int]) -> Optional[str]:
    if n is None:
        return None
    if n < 1024:
        return f"{n} B"
    for unit, div in _UNITS:
        if n >= div:
            v = n / div
            # <100 保留 1 位 (13.7 MB 比 14 MB 有信息量); >=100 取整 (470 KB 比 469.9 KB 好读)
            return f"{v:.1f} {unit}" if v < 100 else f"{v:.0f} {unit}"
    return f"{n} B"


def human_duration(seconds: Optional[float]) -> Optional[str]:
    """秒 → `1:23` / `1:02:03` (模型与人都一眼看懂)。"""
    if seconds is None:
        return None
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _drop_empty(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None and v != [] and v != ""}


def shape_trim(trim: Any) -> Optional[dict]:
    if not trim:
        return None
    d = _drop_empty({"start": trim.start, "end": trim.end})
    return d or None


def next_step_for(job: Any, cfg: Any, saved_path: Optional[str] = None) -> str:
    """给模型的一句话行动建议。这是本文件最有价值的部分 —— 别删。"""
    st = job.status
    if st in ("queued", "processing"):
        bits = [f"Job {job.id} is still running (status={st}, progress={job.progress}%)."]
        if getattr(job, "queue_position", None):
            bits.append(f"Queue position {job.queue_position}"
                        + (f", ~{job.estimated_wait_seconds}s estimated wait"
                           if job.estimated_wait_seconds else "") + ".")
        if getattr(job, "webhook_url", None):
            bits.append("A webhook is configured — no need to poll.")
        else:
            bits.append(f"Call get_download('{job.id}') again in a few seconds "
                        "(it is not blocking anymore), or pass a larger wait_seconds next time.")
        bits.append("Nothing has been charged yet — billing only happens if it reaches completed.")
        return " ".join(bits)
    if st == "completed":
        if saved_path:
            return f"Artifact saved to {saved_path}. Nothing else to do."
        dv = getattr(job, "delivery", None)
        if dv is not None and dv.type == "storage" and dv.uri:
            return (f"Artifact delivered to your own storage ({dv.provider or job.destination_type}) at "
                    f"{dv.uri}. Nothing else to do.")
        if job.storage_key:
            return (f"Artifact delivered to your own storage ({job.destination_type}) at "
                    f"{job.storage_key}. Nothing else to do.")
        if job.download_url:
            exp = f" It expires at {job.download_url_expires_at} (UTC)." if job.download_url_expires_at else ""
            return (f"Artifact is ready.{exp} Fetch it with this download_url, or re-run with "
                    "save_to=\"<file path>\" to have this server store it for you.")
        return "Artifact is ready but no download_url was issued — retrieve the job again."
    if st == "failed":
        err, dv = getattr(job, "error", None), getattr(job, "delivery", None)
        if err is not None and err.stage == "delivery":
            fix = f" Fix: {err.hint}" if err.hint else ""
            if dv is not None and dv.redeliverable:
                until = f" before {dv.hold_expires_at} (UTC)" if dv.hold_expires_at else ""
                return (f"The video downloaded fine but could not be written to the user's storage "
                        f"({err.code}: {err.message or job.error_message}). Nothing was charged.{fix} "
                        f"Once the user has fixed it, call redeliver_download('{job.id}'){until} — "
                        "no re-download, no extra charge. Or pass destination_id=\"url\" to get a "
                        "platform link instead.")
            return (f"Delivery to the user's storage failed ({err.code}) and the held copy has expired. "
                    f"Nothing was charged.{fix} Fix the bucket, then run download_media again.")
        reason = job.error_message or job.error_code or "unknown"
        return (f"Job failed and was NOT charged. Reason: {reason} "
                "(the attempt log is in the error detail). Retrying the same URL as-is is "
                "usually not useful — check that the video is public and the format exists.")
    if st == "deleted":
        return "Job was cancelled/deleted. Nothing was charged."
    return f"Job is in state '{st}'."


def shape_attempts(job: Any, limit: int = 5) -> list:
    out = []
    for a in (getattr(job, "attempt_details", None) or [])[:limit]:
        out.append(_drop_empty({
            "attempt_no": a.attempt_no, "strategy": a.strategy, "result": a.result,
            "error_code": a.error_code, "error_message": a.error_message,
            "latency_ms": a.latency_ms,
        }))
    return out


def shape_download(job: Any, *, cfg: Any, saved_path: Optional[str] = None,
                   include_attempts: bool = False) -> dict:
    """`Download`/`DownloadJob.download` → 紧凑结果。"""
    d = {
        "ok": job.status == "completed",
        "job_id": job.id,
        "status": job.status,
        "format": job.format,
        "title": job.title,
        "duration_seconds": job.duration_seconds,
        "duration_human": human_duration(job.duration_seconds),
        "size_bytes": job.size_bytes,
        "size_human": human_bytes(job.size_bytes),
        "trim": shape_trim(job.trim),
        "cost_usd": round(job.cost_usd, 6) if job.cost_usd else 0.0,
        # 失败不计费是产品契约, 显式告诉模型, 免得它去猜要不要提醒用户扣钱
        "charged": job.status == "completed" and bool(job.size_bytes),
        "attempts": job.attempts or None,
        "strategy": job.strategy,
        "progress": job.progress if job.status not in ("completed",) else None,
        "video_id": job.video_id,
        "thumbnail": job.thumbnail,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }
    dv = getattr(job, "delivery", None)
    if job.status == "completed":
        if dv is not None and dv.type == "storage":
            d["destination_type"] = dv.provider or job.destination_type
            d["destination_id"] = dv.destination_id
            d["storage_uri"] = dv.uri
            d["storage_key"] = job.storage_key
        elif job.storage_key:
            d["destination_type"] = job.destination_type
            d["storage_key"] = job.storage_key
        elif job.download_url:
            d["destination_type"] = "url"
            d["download_url"] = job.download_url
            d["download_url_expires_at"] = job.download_url_expires_at
    if saved_path:
        d["saved_path"] = saved_path
    if job.status == "failed":
        d["error_code"] = job.error_code
        d["error_message"] = job.error_message
        err = getattr(job, "error", None)
        if err is not None:
            d["error"] = _drop_empty({"stage": err.stage, "retryable": err.retryable,
                                      "provider_code": err.provider_code, "hint": err.hint})
        if dv is not None and dv.status == "failed":
            d["redeliverable"] = dv.redeliverable
            d["hold_expires_at"] = dv.hold_expires_at if dv.redeliverable else None
    if getattr(job, "queue_position", None) is not None:
        d["queue"] = _drop_empty({
            "position": job.queue_position, "ahead_of_you": job.ahead_of_you,
            "estimated_wait_seconds": job.estimated_wait_seconds,
        })
    if include_attempts:
        att = shape_attempts(job)
        if att:
            d["attempt_details"] = att
    d["next_step"] = next_step_for(job, cfg, saved_path=saved_path)
    return _drop_empty(d)


def shape_info(info: Any) -> dict:
    """`VideoInfo` → 紧凑结果。格式列表按"从小到大"排, 并带上预估字节。"""
    formats = []
    for f in (getattr(info, "formats", None) or []):
        formats.append(_drop_empty({
            "format": f.quality, "estimated_bytes": f.size,
            "estimated_human": human_bytes(f.size), "container": f.container,
        }))
    return _drop_empty({
        "ok": True,
        "video_id": info.id,
        "title": info.title,
        "channel": info.channel,
        "duration_seconds": info.duration,
        "duration_human": human_duration(info.duration),
        "thumbnail": info.thumbnail,
        "upload_date": info.upload_date,
        "view_count": info.view_count,
        "available_formats": formats,
        "next_step": ("Free lookup — no quota consumed. Pick a format, then call download_media. "
                      "Note the estimate is a guide: the real size_bytes comes back once the job "
                      "completes, and billing uses max(size, 20 MiB)."),
    })


def shape_usage(u: Any) -> dict:
    return _drop_empty({
        "ok": True,
        "plan": u.plan,
        "month": u.month,
        "used_gb": round(u.used_gb, 4),
        "quota_gb": u.quota_gb,
        "remaining_gb": round(u.remaining_gb, 4) if u.remaining_gb is not None else None,
        "used_pct": round(u.used_pct, 2),
        "payg_balance_usd": round(u.payg_balance_cents / 100.0, 2),
        "payg_rate_usd_per_gb": u.payg_rate_usd_per_gb,
        "alert_level": u.alert_level,
        "alert_message": u.alert_message,
        "active_jobs": u.active_jobs,
        "concurrency_limit": u.concurrency_limit,
        "key_used_gb": round(u.key_used_gb, 4),
        "next_step": (
            "Quota is account-wide and shared by every key; billing bytes are max(size, 20 MiB) "
            "per completed job and failed jobs are never charged."
            + (" Low balance — top up or upgrade before submitting large batches."
               if u.alert_level in ("warning", "critical", "exceeded") else "")
        ),
    })


def shape_list(res: Any, *, cfg: Any, limit: int = 20) -> dict:
    items = []
    for job in (getattr(res, "items", None) or [])[:limit]:
        items.append(_drop_empty({
            "job_id": job.id, "status": job.status, "format": job.format,
            "title": job.title, "size_bytes": job.size_bytes,
            "size_human": human_bytes(job.size_bytes),
            "duration_seconds": job.duration_seconds,
            "trim": shape_trim(job.trim),
            "cost_usd": round(job.cost_usd, 6) if job.cost_usd else 0.0,
            "created_at": job.created_at,
            "error_code": job.error_code if job.status == "failed" else None,
        }))
    return _drop_empty({
        "ok": True,
        "total": getattr(res, "total", len(items)),
        "has_more": bool(getattr(res, "has_more", False)),
        "count": len(items),
        "downloads": items,
        "next_step": ("Pass offset to page further" if getattr(res, "has_more", False)
                      else "That is the whole list for this filter."),
    })


def shape_storage_list(items: Any) -> dict:
    conns = []
    for c in items or []:
        conns.append(_drop_empty({
            "destination_id": c.id, "name": c.name, "provider": c.provider, "bucket": c.bucket,
            "path_prefix": c.path_prefix, "is_default": c.is_default or None, "status": c.status,
            "last_error": (f"{c.last_error_code}: {c.last_error_message or ''}".strip(": ")
                           if c.last_error_code else None),
            "deliveries": c.deliveries_count or None,
        }))
    default = next((c["destination_id"] for c in conns if c.get("is_default")), None)
    failing = [c["destination_id"] for c in conns if c.get("status") == "failing"]
    if not conns:
        nxt = ("No storage connected. download_media will return a platform link; to deliver into a "
               "bucket the user connects one in the VideoFetch dashboard (Storage).")
    else:
        nxt = (f"Pass destination_id to download_media. "
               + (f"Omitting it uses the default {default}. " if default else
                  "No default is set, so omitting it returns a platform link. ")
               + (f"Failing: {', '.join(failing)} — uploads there will fail until the user fixes it."
                  if failing else ""))
    return _drop_empty({"ok": True, "count": len(conns), "storage": conns, "next_step": nxt.strip()})
