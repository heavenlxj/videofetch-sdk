"""trim 参数宽容性 (2026-11-05 实测缺陷)。

线上实测: 客户按最直觉的写法传 dict 会直接崩

    client.downloads.create(..., trim={"start": 300, "end": 303})
    → AttributeError: 'dict' object has no attribute 'to_dict'

根因: `_build_trim` 无条件调 `trim.to_dict()`, 把内部模型 TrimSpec
     泄漏成了外部硬性要求。而 HTTP 接口本身收的就是 {"start","end"},
     文档示例也常写成 dict —— 客户没有理由知道要先构造对象。

本测试锁定: trim 必须同时接受 TrimSpec / dict / None,
非法类型给出**可读的 TypeError** 而不是下游 AttributeError。
"""
import json

import httpx
import pytest

import videofetch
from videofetch.models import TrimSpec
from videofetch.resources import _build_trim, _coerce_trim


def _client(handler) -> videofetch.VideoFetch:
    transport = httpx.MockTransport(handler)
    return videofetch.VideoFetch(
        api_key="vf_live_sk_test", base_url="http://mock",
        http_client=httpx.Client(base_url="http://mock", transport=transport),
    )


def _dl_json(status="queued", **kw) -> dict:
    base = {"id": "dl_x", "status": status, "url": "https://www.youtube.com/watch?v=x",
            "format": "360p", "progress": 0, "title": "T", "cost_usd": 0.0, "attempts": 0}
    base.update(kw)
    return base


# ── _coerce_trim 单元行为 ───────────────────────────────────────────────

def test_coerce_accepts_trim_spec():
    t = TrimSpec(start=1.0, end=2.0)
    assert _coerce_trim(t) is t


def test_coerce_accepts_plain_dict():
    """★ 这是线上崩溃的那条路径。"""
    out = _coerce_trim({"start": 300, "end": 303})
    assert isinstance(out, TrimSpec)
    assert out.start == 300.0 and out.end == 303.0


def test_coerce_accepts_dict_with_floats():
    out = _coerce_trim({"start": 300.5, "end": 303.25})
    assert out.start == 300.5 and out.end == 303.25


def test_coerce_accepts_partial_dict():
    """只给 start 也应接受（后端会按需补 end）。"""
    out = _coerce_trim({"start": 10})
    assert out.start == 10.0 and out.end is None


def test_coerce_accepts_none():
    assert _coerce_trim(None) is None


def test_coerce_rejects_bad_type_with_clear_message():
    """非法类型要给人话，不是 AttributeError。"""
    for bad in (123, "300-303", [300, 303], object()):
        with pytest.raises(TypeError) as exc:
            _coerce_trim(bad)
        msg = str(exc.value)
        assert "trim must be a TrimSpec or a dict" in msg
        assert type(bad).__name__ in msg


# ── _build_trim 组合行为 ───────────────────────────────────────────────

def test_build_trim_dict():
    assert _build_trim({"start": 10, "end": 20}, None, None) == {"start": 10.0, "end": 20.0}


def test_build_trim_spec():
    assert _build_trim(TrimSpec(start=10, end=20), None, None) == {"start": 10, "end": 20}


def test_build_trim_none():
    assert _build_trim(None, None, None) is None


def test_build_trim_flat_aliases():
    assert _build_trim(None, 10, 20) == {"start": 10, "end": 20}


def test_build_trim_dict_plus_matching_flat_ok():
    """dict 与扁平参数一致 → 允许，不报错。"""
    assert _build_trim({"start": 10, "end": 20}, 10, 20) == {"start": 10.0, "end": 20.0}


def test_build_trim_conflict_still_rejected():
    """冲突仍然要拒绝 —— 宽容不代表静默择一。"""
    with pytest.raises(ValueError):
        _build_trim({"start": 10, "end": 20}, 999, None)


def test_build_trim_only_one_flat_rejected():
    with pytest.raises(ValueError):
        _build_trim(None, 10, None)


# ── 端到端: dict 能直接进 HTTP 请求体 ────────────────────────────────

def test_create_with_dict_trim_sends_correct_body():
    """★ 线上崩溃场景的端到端复现。"""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            seen["body"] = json.loads(req.read().decode())
            return httpx.Response(202, json=_dl_json())
        return httpx.Response(200, json=_dl_json("completed"))

    c = _client(handler)
    job = c.downloads.create(
        "https://www.youtube.com/watch?v=x", format="360p",
        trim={"start": 300, "end": 303},      # ← 直觉写法，旧版直接崩
    )
    assert job.id == "dl_x"
    assert seen["body"]["trim"] == {"start": 300.0, "end": 303.0}


def test_create_with_trim_spec_still_works():
    """原有写法必须保持兼容。"""
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            seen["body"] = json.loads(req.read().decode())
            return httpx.Response(202, json=_dl_json())
        return httpx.Response(200, json=_dl_json("completed"))

    c = _client(handler)
    c.downloads.create("https://www.youtube.com/watch?v=x", format="360p",
                       trim=TrimSpec(start=300, end=303))
    assert seen["body"]["trim"] == {"start": 300, "end": 303}


def test_create_with_flat_trim_aliases():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            seen["body"] = json.loads(req.read().decode())
            return httpx.Response(202, json=_dl_json())
        return httpx.Response(200, json=_dl_json("completed"))

    c = _client(handler)
    c.downloads.create("https://www.youtube.com/watch?v=x", format="360p",
                       trim_start=300, trim_end=303)
    assert seen["body"]["trim"] == {"start": 300, "end": 303}


def test_create_without_trim_omits_field():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST":
            seen["body"] = json.loads(req.read().decode())
            return httpx.Response(202, json=_dl_json())
        return httpx.Response(200, json=_dl_json("completed"))

    c = _client(handler)
    c.downloads.create("https://www.youtube.com/watch?v=x", format="360p")
    assert "trim" not in seen["body"] or seen["body"]["trim"] is None
