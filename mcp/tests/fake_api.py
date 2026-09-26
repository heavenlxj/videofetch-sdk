"""内存版 VideoFetch API —— 覆盖 MCP 工具会打到的每个端点。

为什么不用真 API 做单测: 单测要断言的是**我们的工具逻辑**(参数校验/有界等待/落盘/错误翻译),
不是后端。假 API 让每个分支都能被稳定构造 (超时、失败、402、404…), 且毫秒级、无网络。
真机验证另有 `test_live.py` (需要真 key, 默认跳过)。
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

ARTIFACT = b"ID3\x04" + b"\x00" * 4096          # 假 mp3 字节 (只校验"写进去的是同一串")
DOWNLOAD_URL = "https://cdn.vf.test/art/dl_test01.mp3"


class FakeAPI:
    def __init__(self, *, complete_after: int = 1, fail_jobs: bool = False,
                 no_download_url: bool = False, with_destination: bool = False,
                 advance: bool = True, delivery_fails: bool = False):
        # advance=False: GET 只观察不推进 (真 API 里状态靠 worker 推进, 读取不该有副作用)
        self.advance = advance
        self.complete_after = complete_after      # 第 N 次 GET 后变终态
        self.fail_jobs = fail_jobs
        self.no_download_url = no_download_url
        self.with_destination = with_destination
        self.delivery_fails = delivery_fails      # 首轮投递失败 (保留文件), redeliver 后成功
        self.storage = [
            {"id": "st_default0000001", "name": "Prod R2", "provider": "r2", "bucket": "my-bucket",
             "path_prefix": "youtube/{video_id}/", "is_default": True, "status": "active",
             "deliveries_count": 12, "created_at": "2026-09-01T00:00:00"},
            {"id": "st_failing0000002", "name": "Old S3", "provider": "s3", "bucket": "old",
             "path_prefix": "youtube/", "is_default": False, "status": "failing", "deliveries_count": 0,
             "last_error": {"code": "storage_permission_denied", "message": "Access denied"},
             "created_at": "2026-09-01T00:00:00"},
        ]
        self.jobs: dict[str, dict] = {}
        self.polls: dict[str, int] = {}
        self.requests: list[tuple[str, str, Optional[dict]]] = []
        self.overrides: dict[str, httpx.Response] = {}   # "POST /v1/downloads" → 强制错误
        self._seq = 0

    # ── 组装 ────────────────────────────────────────────────────────────────
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def client(self, **kw: Any) -> httpx.Client:
        """给 SDK 用的 httpx.Client: base_url + 鉴权头 + 假传输。"""
        return httpx.Client(
            base_url=kw.get("base_url", "http://vf.test"),
            headers={"Authorization": f"Bearer {kw.get('api_key', 'test')}",
                     "Content-Type": "application/json"},
            transport=self.transport(),
        )

    def force(self, method: str, path: str, status: int, body: Any,
              retry_after: Optional[int] = None) -> None:
        """注入一个固定错误响应 (用于 401/402/404/429 分支)。"""
        headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
        self.overrides[f"{method} {path}"] = httpx.Response(status, json=body, headers=headers)

    # ── 端点 ────────────────────────────────────────────────────────────────
    def _handle(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        body = None
        if request.content:
            try:
                body = json.loads(request.content)
            except Exception:  # noqa: BLE001
                body = None
        self.requests.append((method, path, body))

        if path.startswith("/art/"):
            return httpx.Response(200, content=ARTIFACT)

        forced = self.overrides.get(f"{method} {path}")
        if forced is not None:
            return forced

        if method == "POST" and path == "/v1/info":
            return httpx.Response(200, json={
                "id": "aqz-KE-bpKQ", "url": (body or {}).get("url", ""),
                "title": "Big Buck Bunny", "duration": 635.0,
                "thumbnail": "https://i.ytimg.com/vi/aqz-KE-bpKQ/hqdefault.jpg",
                "channel": "Blender", "upload_date": "20080430", "view_count": 1234567,
                "formats": [
                    {"quality": "360p", "size": 14410000, "container": "MP4"},
                    {"quality": "720p", "size": 41000000, "container": "MP4"},
                    {"quality": "mp3", "size": 11097429, "container": "MP3", "note": "audio only"},
                ],
            })

        if method == "POST" and path == "/v1/downloads":
            self._seq += 1
            jid = f"dl_test{self._seq:02d}"
            self.jobs[jid] = {
                "id": jid, "status": "queued", "url": (body or {}).get("url", ""),
                "format": (body or {}).get("format", "720p"), "progress": 0,
                "title": "Big Buck Bunny", "video_id": "aqz-KE-bpKQ",
                "thumbnail": "https://i.ytimg.com/vi/aqz-KE-bpKQ/hqdefault.jpg",
                "duration_seconds": 30.0 if (body or {}).get("trim") else 635.0,
                "trim": (body or {}).get("trim"), "cost_usd": 0.0, "attempts": 0,
                "queue_position": 1, "ahead_of_you": 0, "estimated_wait_seconds": 3,
                "created_at": "2026-09-24T12:00:00",
            }
            return httpx.Response(202, json=self.jobs[jid])

        if method == "GET" and path == "/v1/storage":
            return httpx.Response(200, json={"items": self.storage})

        if method == "POST" and path.startswith("/v1/downloads/") and path.endswith("/redeliver"):
            jid = path.split("/")[3]
            job = self.jobs.get(jid)
            if job is None or not (job.get("delivery") or {}).get("redeliverable"):
                return httpx.Response(409, json={"detail": {"code": "not_redeliverable",
                                                            "message": "Nothing to redeliver."}})
            self.delivery_fails = False
            job.update(status="queued", error_code=None, error_message=None, error=None,
                       delivery=None, redelivered_to=(body or {}).get("destination"))
            self.polls[jid] = 0
            return httpx.Response(202, json=job)

        if method == "GET" and path.startswith("/v1/downloads/"):
            jid = path.rsplit("/", 1)[-1]
            job = self.jobs.get(jid)
            if job is None:
                return httpx.Response(404, json={"detail": {"code": "not_found",
                                                            "message": "Download not found."}})
            self.polls[jid] = self.polls.get(jid, 0) + 1
            self._advance(job, self.polls[jid])
            return httpx.Response(200, json=job)

        if method == "GET" and path == "/v1/downloads":
            items = [self._advance(j, self.polls.get(j["id"], 0) + 1) for j in self.jobs.values()]
            return httpx.Response(200, json={"items": items, "total": len(items), "has_more": False})

        if method == "DELETE" and path.startswith("/v1/downloads/"):
            self.jobs.pop(path.rsplit("/", 1)[-1], None)
            return httpx.Response(204)

        if method == "GET" and path == "/v1/usage":
            return httpx.Response(200, json={
                "key_id": "key_test", "plan": "free", "quota_gb": 1.0,
                "used_bytes": 20971520, "used_gb": 0.0195, "remaining_gb": 0.9805,
                "key_used_bytes": 20971520, "key_used_gb": 0.0195,
                "payg_balance_cents": 0, "payg_rate_usd_per_gb": 0.35,
                "account_used_bytes_month": 20971520, "account_used_gb_month": 0.0195,
                "used_pct": 1.95, "month": "2026-09", "active_jobs": 0,
                "concurrency_limit": 5, "alert_level": "ok", "alert_message": "",
            })

        return httpx.Response(404, json={"detail": {"code": "no_route", "message": f"{method} {path}"}})

    def _advance(self, job: dict, seen: int) -> dict:
        if job["status"] in ("completed", "failed", "deleted"):
            return job
        if not self.advance:
            return job
        if seen < self.complete_after:
            job["status"] = "processing"
            job["progress"] = 40
            return job
        if self.fail_jobs:
            job.update(status="failed", error_code="download_failed", progress=100,
                       error_message="YouTube video is private or unavailable.")
            return job
        if self.delivery_fails:
            job.update(status="failed", progress=100, error_code="storage_permission_denied",
                       error_message="The credentials cannot write to this bucket.",
                       error={"code": "storage_permission_denied", "stage": "delivery",
                              "retryable": False, "provider_code": "AccessDenied",
                              "hint": "Grant s3:PutObject on the bucket/prefix."},
                       delivery={"type": "storage", "status": "failed",
                                 "destination_id": "st_default0000001", "provider": "r2",
                                 "bucket": "my-bucket", "redeliverable": True,
                                 "hold_expires_at": "2026-09-25T12:00:00"})
            return job
        job.update(status="completed", progress=100, size_bytes=481213,
                   cost_usd=0.006836, attempts=1, strategy="decodo_isp",
                   completed_at="2026-09-24T12:00:18",
                   processing_time_ms=18000)
        if self.with_destination or "redelivered_to" in job:
            key = "youtube/aqz-KE-bpKQ/dl_test.mp3"
            job.update(destination_type="r2", destination_id="st_default0000001",
                       storage_key=f"user://my-bucket/{key}",
                       delivery={"type": "storage", "status": "delivered",
                                 "destination_id": "st_default0000001", "provider": "r2",
                                 "bucket": "my-bucket", "key": key, "uri": f"r2://my-bucket/{key}"})
        elif not self.no_download_url:
            job.update(destination_type="url", download_url=DOWNLOAD_URL,
                       download_url_expires_at="2026-10-01T12:00:00")
        # 终态不再带排队字段 (契约: 非 queued 必须为 null)
        for k in ("queue_position", "ahead_of_you", "estimated_wait_seconds"):
            job.pop(k, None)
        return job
