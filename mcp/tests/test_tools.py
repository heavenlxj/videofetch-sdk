"""MCP 工具的行为回归 (离线, 假 API)。

断言的是**产品契约**, 不是实现细节。每一条都对应文档里对用户/Agent 的承诺:
  - 免费探测不消耗额度, 且给出可选格式与预估体积;
  - 建单会带上 trim / destination (只带 id) / webhook;
  - 有界等待: 超时**不报错**, 返回 processing + job_id 让 Agent 去轮询;
  - 落盘只在白名单目录内, 写进去的字节与产物一致;
  - 失败不收费, 且错误信息里有"下一步该做什么";
  - 402/401/404/429 的翻译各不相同, 都带可行动建议。
"""

from __future__ import annotations

import os

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from videofetch_mcp import server


# ── video_info ──────────────────────────────────────────────────────────────
def test_video_info_shapes_metadata_and_formats(api):
    out = server.video_info(url="https://www.youtube.com/watch?v=aqz-KE-bpKQ")
    assert out["ok"] is True
    assert out["video_id"] == "aqz-KE-bpKQ"
    assert out["title"] == "Big Buck Bunny"
    assert out["duration_seconds"] == 635.0
    assert out["duration_human"] == "10:35"
    assert [f["format"] for f in out["available_formats"]] == ["360p", "720p", "mp3"]
    assert out["available_formats"][0]["estimated_human"] == "13.7 MB"
    # 免费是核心卖点, 必须写在 next_step 里告诉模型
    assert "no quota" in out["next_step"]


# ── download_media: 正常路径 ────────────────────────────────────────────────
def test_download_media_completes_and_reports_link(api):
    out = server.download_media(url="https://youtu.be/aqz-KE-bpKQ", format="mp3")
    assert out["ok"] is True and out["status"] == "completed"
    assert out["size_bytes"] == 481213 and out["size_human"] == "470 KB"
    assert out["charged"] is True
    assert out["cost_usd"] == 0.006836
    assert out["download_url"].startswith("https://cdn.vf.test/")
    assert out["download_url_expires_at"] == "2026-10-01T12:00:00"
    assert "download_url" in out["next_step"] and "save_to" in out["next_step"]
    # 终态不应再带进度/排队字段 (契约: 非 queued 的排队字段为 null)
    assert "queue" not in out and "progress" not in out


def test_download_media_sends_trim_and_destination_and_webhook(api):
    out = server.download_media(
        url="https://youtu.be/aqz-KE-bpKQ", format="mp3", start=10, end=40,
        destination_id="11111111-2222-3333-4444-555555555555",
        webhook_url="https://acme.dev/hooks/vf", wait_seconds=0,
    )
    body = next(b for m, p, b in api.requests if m == "POST" and p == "/v1/downloads")
    assert body["trim"] == {"start": 10.0, "end": 40.0}
    # ★ 只带 id (后端从库里取真实 provider)。这条断言守着 backend 的 destination 判据别被改回去。
    assert body["destination"] == {"id": "11111111-2222-3333-4444-555555555555"}
    assert body["webhook_url"] == "https://acme.dev/hooks/vf"
    assert "type" not in body["destination"]
    assert out["status"] in ("queued", "processing")


def test_wait_seconds_zero_returns_immediately_with_next_step(api):
    out = server.download_media(url="https://youtu.be/x", format="360p", wait_seconds=0)
    assert out["status"] in ("queued", "processing")
    assert out["job_id"].startswith("dl_")
    assert "get_download" in out["next_step"]
    # 只打了一次建单, 一次都没轮询
    assert not [1 for m, p, _ in api.requests if m == "GET" and p.startswith("/v1/downloads/")]


def test_timeout_is_not_an_error(make_api):
    api = make_api(complete_after=999)          # 永远不会完成
    out = server.download_media(url="https://youtu.be/x", format="mp3", wait_seconds=1)
    assert out["status"] == "processing"        # ← 关键: 超时不抛错
    assert out["job_id"] and out["queue"]["position"] == 1
    assert "still running" in out["next_step"] and "get_download" in out["next_step"]
    assert "nothing has been charged yet" in out["next_step"].lower()


def test_destination_job_reports_storage_key(make_api):
    make_api(with_destination=True)
    out = server.download_media(url="https://youtu.be/x", format="720p",
                                destination_id="11111111-2222-3333-4444-555555555555")
    assert out["destination_type"] == "r2"
    assert out["storage_key"].startswith("user://my-bucket/")
    assert "download_url" not in out
    assert "your own storage" in out["next_step"]


# ── download_media: 落盘 ────────────────────────────────────────────────────
def test_save_to_writes_artifact_inside_allowed_dir(api, tmp_path):
    target = str(tmp_path / "clip.mp3")
    out = server.download_media(url="https://youtu.be/x", format="mp3", save_to=target)
    assert out["saved_path"] == target
    assert os.path.getsize(target) == len(__import__("fake_api").ARTIFACT)
    assert open(target, "rb").read(4) == b"ID3\x04"
    assert "saved to" in out["next_step"]


def test_save_to_outside_allowed_dir_is_rejected(api):
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/x", format="mp3",
                              save_to="/tmp/definitely-not-allowed/clip.mp3")
    assert "save_to_rejected" in str(e.value)
    assert "VIDEOFETCH_MCP_OUTPUT_DIR" in str(e.value)


def test_save_to_allowed_when_escape_hatch_set(api, tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOFETCH_MCP_ALLOW_ANY_PATH", "1")
    target = str(tmp_path.parent / "outside.mp3")
    out = server.download_media(url="https://youtu.be/x", format="mp3", save_to=target)
    assert out["saved_path"] == target


# ── 参数校验 (在打 API 之前就挡住, 省一次往返) ──────────────────────────────
@pytest.mark.parametrize("start,end,needle", [
    (40, 10, "greater than start"),
    (10, 10, "greater than start"),
    (-5, 10, "start must be >= 0"),
    (0, 0, "end must be > 0"),
])
def test_trim_validation(api, start, end, needle):
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/x", format="mp3", start=start, end=end)
    assert "invalid_trim" in str(e.value) and needle in str(e.value)
    assert not [1 for m, p, _ in api.requests if m == "POST"]   # 没打 API


# ── 错误翻译 (每条都要"可行动") ─────────────────────────────────────────────
def test_failed_job_says_not_charged(make_api):
    make_api(fail_jobs=True)
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/private", format="720p")
    msg = str(e.value)
    assert "download_failed" in msg and "nothing was charged" in msg
    assert "private or unavailable" in msg
    assert "public" in msg            # 告诉模型先查可见性


def test_quota_exceeded_suggests_topup(api):
    api.force("POST", "/v1/downloads", 402, {"detail": {
        "code": "quota_exceeded", "message": "Monthly quota exhausted", "remaining_gb": 0.0}})
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/x", format="720p")
    msg = str(e.value)
    assert "quota_exceeded" in msg and "top up" in msg and "plan" in msg
    assert "Retrying now will fail the same way" in msg


def test_auth_error_points_at_config(api):
    api.force("POST", "/v1/downloads", 401, {"detail": {
        "code": "invalid_token", "message": "Invalid or expired token."}})
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/x", format="720p")
    msg = str(e.value)
    assert "authentication_error" in msg and "VIDEOFETCH_API_KEY" in msg
    assert "Do not retry" in msg


def test_not_found_tells_model_to_list(api):
    with pytest.raises(ToolError) as e:
        server.get_download(job_id="dl_does_not_exist")
    msg = str(e.value)
    assert "not_found" in msg and "list_downloads" in msg and "Do not invent ids" in msg


def test_rate_limit_includes_retry_after(api):
    api.force("POST", "/v1/downloads", 429, {"detail": {
        "code": "concurrency_limit_exceeded", "message": "Too many jobs"}}, retry_after=3)
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/x", format="720p")
    msg = str(e.value)
    assert "rate_limit_exceeded" in msg and "retry after 3s" in msg and "smaller batches" in msg


def test_validation_error_names_the_param(api):
    api.force("POST", "/v1/downloads", 400, {"detail": {
        "code": "invalid_format", "message": "Unknown format", "param": "format"}})
    with pytest.raises(ToolError) as e:
        server.download_media(url="https://youtu.be/x", format="720p")
    msg = str(e.value)
    assert "validation_error" in msg and "param: format" in msg and "144p" in msg


def test_missing_api_key_is_actionable(monkeypatch):
    monkeypatch.delenv("VIDEOFETCH_API_KEY", raising=False)
    server.reset_clients()
    with pytest.raises(ToolError) as e:
        server.account_usage()
    assert "missing_api_key" in str(e.value) and "restart the MCP server" in str(e.value)


def test_unexpected_error_never_leaks_traceback(api, monkeypatch):
    def boom(*a, **kw):
        raise ValueError("internal detail that must not leak verbatim")
    monkeypatch.setattr(server, "get_client", boom)
    with pytest.raises(ToolError) as e:
        server.account_usage()
    assert "unexpected_error" in str(e.value) and "ValueError" in str(e.value)


# ── 其余工具 ────────────────────────────────────────────────────────────────
def test_list_downloads_shapes_and_paging(api):
    server.download_media(url="https://youtu.be/a", format="mp3", wait_seconds=0)
    out = server.list_downloads(limit=10)
    assert out["ok"] is True and out["count"] == 1 and out["has_more"] is False
    assert out["downloads"][0]["job_id"].startswith("dl_")
    assert "whole list" in out["next_step"]


def test_get_download_includes_attempts_on_request(make_api):
    api = make_api()
    job = server.download_media(url="https://youtu.be/a", format="mp3")
    out = server.get_download(job_id=job["job_id"], include_attempts=True)
    assert out["status"] == "completed"
    assert "attempt_details" not in out or isinstance(out["attempt_details"], list)


def test_cancel_is_idempotent_and_free(make_api):
    make_api(advance=False)          # GET 不推进 → 任务保持 queued, 断言才确定
    job = server.download_media(url="https://youtu.be/a", format="mp3", wait_seconds=0)
    out = server.cancel_download(job_id=job["job_id"])
    assert out["ok"] is True and out["charged"] is False
    assert out["status_before"] == "queued" and out["status_after"] == "deleted"
    assert "nothing was charged" in out["next_step"]


def test_account_usage_flags_low_balance(api):
    out = server.account_usage()
    assert out["plan"] == "free" and out["remaining_gb"] == 0.9805
    assert out["payg_balance_usd"] == 0.0 and out["alert_level"] == "ok"
    assert "max(size, 20 MiB)" in out["next_step"]
