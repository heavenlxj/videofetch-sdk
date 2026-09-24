"""真机端到端 —— 打**真实 API**, 默认跳过。

跑法:
    VIDEOFETCH_LIVE_KEY=vf_live_sk_... python -m pytest tests/test_live.py -v
    # 可选: VIDEOFETCH_LIVE_BASE_URL=http://127.0.0.1:8301  (本地 dev)
    #      VIDEOFETCH_LIVE_URL=https://www.youtube.com/watch?v=aqz-KE-bpKQ

只断言"产品承诺"层面的东西: 免费探测不扣额度 / 下载真的产出可下载的字节 / 失败不收费。
会消耗一点真实额度 (mp3 + 5s 窗口, 按 20MB 最小计费 ≈ $0.007), 所以默认不跑。
"""

from __future__ import annotations

import os

import pytest

from videofetch_mcp import server

KEY = os.getenv("VIDEOFETCH_LIVE_KEY") or ""
URL = os.getenv("VIDEOFETCH_LIVE_URL", "https://www.youtube.com/watch?v=aqz-KE-bpKQ")
BASE = os.getenv("VIDEOFETCH_LIVE_BASE_URL") or ""

pytestmark = pytest.mark.skipif(not KEY, reason="set VIDEOFETCH_LIVE_KEY to run live tests")


@pytest.fixture(autouse=True)
def _live_env(monkeypatch):
    monkeypatch.setenv("VIDEOFETCH_API_KEY", KEY)
    monkeypatch.setenv("VIDEOFETCH_BASE_URL", BASE or "https://api.vidfetch.dev")
    server.reset_clients()
    yield
    server.reset_clients()


def test_usage_roundtrip():
    u = server.account_usage()
    assert u["ok"] is True and u["plan"]
    assert u["remaining_gb"] is not None
    before = u["used_gb"]

    # 免费探测不消耗额度 (产品承诺)
    info = server.video_info(url=URL)
    assert info["video_id"] and info["duration_seconds"] > 0
    after = server.account_usage()["used_gb"]
    assert after == before, f"video_info 竟然扣了额度: {before} → {after}"


def test_download_audio_clip_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEOFETCH_MCP_OUTPUT_DIR", str(tmp_path))
    job = server.download_media(url=URL, format="mp3", start=100, end=105, wait_seconds=180)
    try:
        assert job["status"] == "completed", job
        assert job["size_bytes"] > 0
        assert job["charged"] is True and job["cost_usd"] > 0
        # 时长为真: 5s 窗口 → 5s 左右 (不按 title 的 635s)
        assert 4.0 <= (job["duration_seconds"] or 0) <= 6.5

        saved = server.download_media(url=URL, format="mp3", start=100, end=105,
                                      wait_seconds=180, save_to=str(tmp_path / "clip.mp3"))
        path = saved.get("saved_path")
        assert path and os.path.getsize(path) > 10_000
        with open(path, "rb") as fh:
            assert fh.read(3) in (b"ID3", b"\xff\xfb", b"\xff\xf3")   # 真 mp3
    finally:
        # 不留下垃圾任务 (取消已完成的 = 删除, 不计费)
        try:
            server.cancel_download(job_id=job["job_id"])
        except Exception:  # noqa: BLE001
            pass
