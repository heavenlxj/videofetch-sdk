"""共享 fixture: 把 MCP 工具的 SDK 客户端指向假 API, 并把落盘目录限制在 tmp_path。

环境隔离是刻意的: 每个用例改 env 后都要 `reset_clients()` —— MCP server 按 (key, base_url)
缓存客户端, 不重置会串场 (这类"上一用例的假 API 被下一用例用上"的假绿灯很难查)。
"""

from __future__ import annotations

import pytest

from videofetch_mcp import server

from fake_api import FakeAPI


@pytest.fixture
def api(monkeypatch, tmp_path):
    """默认假 API: 建单当次即完成, 有 download_url。"""
    return _install(monkeypatch, tmp_path, FakeAPI())


@pytest.fixture
def make_api(monkeypatch, tmp_path):
    """需要定制假 API 的用例用这个 (complete_after / fail_jobs / …)。"""
    def _make(**kw):
        return _install(monkeypatch, tmp_path, FakeAPI(**kw))
    return _make


def _install(monkeypatch, tmp_path, fake: FakeAPI) -> FakeAPI:
    monkeypatch.setenv("VIDEOFETCH_API_KEY", "vf_live_sk_test")
    monkeypatch.setenv("VIDEOFETCH_BASE_URL", "http://vf.test")
    monkeypatch.setenv("VIDEOFETCH_MCP_OUTPUT_DIR", str(tmp_path))
    monkeypatch.delenv("VIDEOFETCH_MCP_ALLOW_ANY_PATH", raising=False)
    monkeypatch.delenv("VIDEOFETCH_MCP_MAX_WAIT", raising=False)

    def factory(api_key: str, base_url: str, timeout: float):
        from videofetch import VideoFetch
        return VideoFetch(api_key=api_key, base_url=base_url, timeout=timeout,
                          http_client=fake.client(api_key=api_key, base_url=base_url))

    server.reset_clients()
    monkeypatch.setattr(server, "client_factory", factory)
    yield_after = fake
    return yield_after
