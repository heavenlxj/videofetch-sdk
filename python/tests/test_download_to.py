"""download_to() local-save tests against a mocked httpx transport (no network).

The client used here carries the API key as a DEFAULT header on its own
http_client, so the "no Authorization on the storage link" assertions are real:
a naive implementation that sent storage requests through the normal request()
path would leak the key and fail these tests.
"""
import asyncio
import os
from pathlib import Path

import httpx
import pytest

import videofetch
from videofetch.errors import (
    DownloadNotCompletedError,
    DownloadURLUnavailableError,
    JobFailedError,
    PermissionDeniedError,
)

API_KEY = "vf_live_sk_test"
STORAGE_PATH = "/storage/artifact.bin"
PAYLOAD = bytes(range(256)) * 41            # 10,496 bytes → several chunks


def _download_json(status="completed", **kw) -> dict:
    base = {
        "id": "dl_abc123", "status": status, "url": "https://youtu.be/x",
        "format": "720p", "progress": 100 if status == "completed" else 50,
        "title": "My Clip", "cost_usd": 0.0, "attempts": 1,
    }
    if status == "completed" and "download_url" not in kw:
        base["download_url"] = f"http://mock{STORAGE_PATH}"
    base.update(kw)
    return base


def _client(handler, max_retries: int = 0) -> videofetch.VideoFetch:
    transport = httpx.MockTransport(handler)
    return videofetch.VideoFetch(
        api_key=API_KEY, base_url="http://mock", max_retries=max_retries,
        http_client=httpx.Client(
            base_url="http://mock", headers={"Authorization": f"Bearer {API_KEY}"},
            transport=transport),
    )


def _aclient(handler, max_retries: int = 0) -> videofetch.AsyncVideoFetch:
    transport = httpx.MockTransport(handler)
    return videofetch.AsyncVideoFetch(
        api_key=API_KEY, base_url="http://mock", max_retries=max_retries,
        http_client=httpx.AsyncClient(
            base_url="http://mock", headers={"Authorization": f"Bearer {API_KEY}"},
            transport=transport),
    )


def _storage_ok(req: httpx.Request, state: dict) -> httpx.Response:
    state.setdefault("storage_calls", 0)
    state.setdefault("storage_auth", [])
    state["storage_calls"] += 1
    state["storage_auth"].append(req.headers.get("authorization"))
    return httpx.Response(200, content=PAYLOAD)


# ────────────────────────── success paths ──────────────────────────
def test_download_to_writes_bytes_and_returns_abs_path(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json())
        if req.url.path == STORAGE_PATH:
            return httpx.Response(200, content=PAYLOAD)
        return httpx.Response(404)

    c = _client(handler)
    dest = tmp_path / "explicit.mp4"
    saved = c.downloads.download_to("dl_abc123", dest)

    assert saved == os.path.abspath(str(dest))
    assert os.path.isabs(saved)
    assert Path(saved).read_bytes() == PAYLOAD


def test_default_filename_uses_sanitized_title_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json())
        return httpx.Response(200, content=PAYLOAD)

    saved = _client(handler).downloads.download_to("dl_abc123")
    assert saved == os.path.join(os.path.abspath(str(tmp_path)), "My Clip.mp4")
    assert Path(saved).read_bytes() == PAYLOAD


def test_default_filename_falls_back_to_job_id_when_title_empty(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json(title="   ...   "))
        return httpx.Response(200, content=PAYLOAD)

    saved = _client(handler).downloads.download_to("dl_abc123")
    assert os.path.basename(saved) == "dl_abc123.mp4"


def test_default_filename_sanitizes_and_truncates_title(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    messy = "  ..My/Clip*  " + ("x" * 200)      # separators + unsafe chars + length

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json(title=messy))
        return httpx.Response(200, content=PAYLOAD)

    saved = _client(handler).downloads.download_to("dl_abc123")
    stem = os.path.basename(saved)[:-len(".mp4")]
    assert stem.startswith("MyClip")
    assert "/" not in os.path.basename(saved) and "*" not in os.path.basename(saved)
    assert len(stem) <= 80


def test_mp3_format_gets_mp3_extension(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json(format="mp3"))
        return httpx.Response(200, content=PAYLOAD)

    saved = _client(handler).downloads.download_to("dl_abc123", tmp_path)
    assert saved.endswith(".mp3") and Path(saved).read_bytes() == PAYLOAD


def test_download_to_accepts_existing_directory(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json())
        return httpx.Response(200, content=PAYLOAD)

    saved = _client(handler).downloads.download_to("dl_abc123", tmp_path)
    assert saved == os.path.join(str(tmp_path), "My Clip.mp4")
    assert Path(saved).read_bytes() == PAYLOAD


def test_download_to_accepts_trailing_separator(tmp_path):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            return httpx.Response(200, json=_download_json())
        return httpx.Response(200, content=PAYLOAD)

    target = str(tmp_path) + os.sep
    saved = _client(handler).downloads.download_to("dl_abc123", target)
    assert saved == os.path.join(str(tmp_path), "My Clip.mp4")


# ────────────────────────── precondition errors ──────────────────────────
def test_not_completed_raises_typed_error_with_status():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_download_json("processing", progress=42))

    c = _client(handler)
    with pytest.raises(DownloadNotCompletedError) as exc:
        c.downloads.download_to("dl_abc123")
    e = exc.value
    assert isinstance(e, videofetch.VideoFetchError)
    assert e.status == "processing" and e.job_id == "dl_abc123"
    assert "processing" in e.message and "completed" in e.message


def test_failed_job_raises_job_failed_error():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_download_json(
            "failed", error_code="download_failed", error_message="blocked"))

    c = _client(handler)
    with pytest.raises(JobFailedError) as exc:
        c.downloads.download_to("dl_abc123")
    assert exc.value.error_code == "download_failed"
    assert exc.value.failed_not_charged is True


def test_completed_without_download_url_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_download_json(
            download_url=None, destination_type="s3"))

    c = _client(handler)
    with pytest.raises(DownloadURLUnavailableError) as exc:
        c.downloads.download_to("dl_abc123")
    assert exc.value.code == "download_url_unavailable"


def test_no_job_request_is_made_when_path_is_default_and_not_completed(tmp_path):
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_download_json("queued"))

    c = _client(handler)
    with pytest.raises(DownloadNotCompletedError):
        c.downloads.download_to("dl_abc123", tmp_path / "x.mp4")
    assert calls["n"] == 1          # fetched the job once, never touched storage


# ────────────────────────── 403 → re-sign → retry ──────────────────────────
def test_403_refetches_job_then_retries_without_api_key(tmp_path):
    state = {"job_calls": 0, "job_auth": []}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            state["job_calls"] += 1
            state["job_auth"].append(req.headers.get("authorization"))
            sig = "fresh" if state["job_calls"] > 1 else "stale"
            return httpx.Response(200, json=_download_json(
                download_url=f"http://mock{STORAGE_PATH}?sig={sig}"))
        if req.url.path == STORAGE_PATH:
            if req.url.params.get("sig") == "stale":
                state.setdefault("storage_auth", []).append(req.headers.get("authorization"))
                state["storage_calls"] = state.get("storage_calls", 0) + 1
                return httpx.Response(403, text="link expired")
            return _storage_ok(req, state)
        return httpx.Response(404)

    c = _client(handler)
    saved = c.downloads.download_to("dl_abc123", tmp_path / "retry.mp4")

    assert Path(saved).read_bytes() == PAYLOAD
    assert state["job_calls"] == 2              # re-fetched so the server re-signs
    assert state["storage_calls"] == 2          # stale 403, then the retry
    # The API key goes to the API but NEVER to the self-authorizing storage link.
    assert state["job_auth"] == [f"Bearer {API_KEY}"] * 2
    assert state["storage_auth"] == [None, None]


def test_403_twice_raises_permission_denied_after_one_retry(tmp_path):
    state = {"job_calls": 0, "storage_calls": 0, "storage_auth": []}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            state["job_calls"] += 1
            return httpx.Response(200, json=_download_json())
        if req.url.path == STORAGE_PATH:
            state["storage_calls"] += 1
            state["storage_auth"].append(req.headers.get("authorization"))
            return httpx.Response(403, text="link expired")
        return httpx.Response(404)

    c = _client(handler)
    with pytest.raises(PermissionDeniedError) as exc:
        c.downloads.download_to("dl_abc123", tmp_path / "nope.mp4")
    assert exc.value.status_code == 403
    assert state["job_calls"] == 2 and state["storage_calls"] == 2
    assert state["storage_auth"] == [None, None]
    assert not (tmp_path / "nope.mp4").exists()


# ────────────────────────── async parity ──────────────────────────
def test_async_download_to_writes_and_retries_on_403(tmp_path):
    state = {"job_calls": 0, "storage_calls": 0, "storage_auth": []}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/v1/downloads/dl_abc123":
            state["job_calls"] += 1
            sig = "fresh" if state["job_calls"] > 1 else "stale"
            return httpx.Response(200, json=_download_json(
                download_url=f"http://mock{STORAGE_PATH}?sig={sig}"))
        if req.url.path == STORAGE_PATH:
            state["storage_calls"] += 1
            state["storage_auth"].append(req.headers.get("authorization"))
            if req.url.params.get("sig") == "stale":
                return httpx.Response(403, text="link expired")
            return httpx.Response(200, content=PAYLOAD)
        return httpx.Response(404)

    async def run():
        c = _aclient(handler)
        try:
            return await asyncio.wait_for(
                c.downloads.download_to("dl_abc123", tmp_path / "async.mp4"), timeout=5)
        finally:
            await c.close()

    saved = asyncio.run(run())
    assert Path(saved).read_bytes() == PAYLOAD
    assert state["job_calls"] == 2 and state["storage_calls"] == 2
    assert state["storage_auth"] == [None, None]


def test_async_download_to_not_completed_raises():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_download_json("queued"))

    async def run():
        c = _aclient(handler)
        try:
            await asyncio.wait_for(c.downloads.download_to("dl_abc123"), timeout=5)
        finally:
            await c.close()

    with pytest.raises(DownloadNotCompletedError) as exc:
        asyncio.run(run())
    assert exc.value.status == "queued"
