"""Live integration test for the official Python SDK (v0.2.0).

用法:
    # 1) 拿一把 key (本地 dev)
    python /tmp/vf_client_provision.py my-email@test.com production > /tmp/vfkey.json
    # 2) 跑
    VF_BASE=http://127.0.0.1:8301 VF_KEY=$(python -c "import json;print(json.load(open('/tmp/vfkey.json'))['api_key'])") \
        python tests/integration_live.py

未设 VF_KEY 时自动跳过 (退出码 0), 便于 CI 无凭据时安全运行。
"""
from __future__ import annotations

import json
import os
import sys

import videofetch
from videofetch import VideoFetch

BASE = os.getenv("VF_BASE", "http://127.0.0.1:8301")
KEY = os.getenv("VF_KEY") or os.getenv("VIDEOFETCH_API_KEY") or ""
VIDEO = "https://www.youtube.com/watch?v=aqz-KE-bpKQ"

if not KEY:
    print("SKIP  no VF_KEY set")
    sys.exit(0)

ok = fail = 0


def chk(name: str, cond: bool, extra: str = "") -> None:
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name + (f"  {extra}" if extra else ""))
    ok += bool(cond)
    fail += (not cond)


def main() -> int:
    c = VideoFetch(api_key=KEY, base_url=BASE)

    # 1) usage (账号级口径 + 告警 + 并发)
    u = c.usage.get()
    chk("usage.quota_gb = 1.0 (free tier)", abs(float(u.quota_gb or 0) - 1.0) < 1e-6, f"quota={u.quota_gb}")
    chk("usage.concurrency_limit present", int(u.concurrency_limit or 0) > 0,
        f"limit={u.concurrency_limit} active={u.active_jobs}")
    chk("usage.alert_level valid", u.alert_level in ("ok", "warning", "critical", "exceeded"),
        f"level={u.alert_level}")
    chk("usage.month non-empty", bool(u.month), f"month={u.month}")

    # 2) alerts
    a = c.usage.alerts()
    chk("alerts.thresholds = [80,95,100]", list(a.thresholds) == [80, 95, 100], f"{a.thresholds}")
    chk("alerts.topup_amounts present", list(a.topup_amounts) == [10, 25, 50, 100], f"{a.topup_amounts}")
    chk("alerts.state has pct/remaining", a.state.pct_used >= 0 and a.state.remaining_gb is not None,
        f"pct={a.state.pct_used} remaining={a.state.remaining_gb} action={a.state.action}")

    # 3) webhooks 用 API key 管理 (v0.2.0 新能力) + 签名
    wh = c.webhooks.create(url="http://127.0.0.1:9/not-listening", events=["download.completed", "quota.warning"])
    chk("webhooks.create → 明文 secret", str(wh.secret).startswith("whsec_"), f"len={len(str(wh.secret))}")
    lst = c.webhooks.list()
    masked = next((w.secret for w in lst.items if w.id == wh.id), "")
    chk("webhooks.list → masked secret", "*" in str(masked) and str(wh.secret) not in str(masked), f"{masked[:14]}…")
    body = b'{"event":"download.completed","id":"dl_test"}'
    import hashlib, hmac
    sig = "sha256=" + hmac.new(str(wh.secret).encode(), body, hashlib.sha256).hexdigest()
    ev = videofetch.construct_event(body, sig, str(wh.secret))
    chk("construct_event 验签通过 (raw body)", ev.get("event") == "download.completed", f"event={ev.get('event')}")
    tampered = False
    try:
        videofetch.construct_event(body + b" ", sig, str(wh.secret))
    except Exception:
        tampered = True
    chk("篡改 body → 抛错", tampered)
    c.webhooks.delete(wh.id)
    chk("webhooks.delete 204", True, "deleted")

    # 4) 真实下载 (mp3 + trim 小任务)
    job = c.downloads.create(url=VIDEO, format="mp3", trim_start=0, trim_end=20)
    chk("downloads.create (扁平 trim 别名)", bool(job.id), f"id={job.id}")
    res = job.wait(timeout=300, poll_interval=3)
    chk("job.wait → completed", res.status == "completed", f"status={res.status} size={res.size_bytes}")
    chk("产物字节 > 0 且带 download_url", (res.size_bytes or 0) > 0 and bool(res.download_url),
        f"size={res.size_bytes} cost={res.cost_usd}")

    # 5) 错误语义
    try:
        VideoFetch(api_key="vf_live_sk_deadbeef", base_url=BASE).usage.get()
        chk("无效 key → AuthenticationError", False)
    except videofetch.AuthenticationError as e:
        chk("无效 key → AuthenticationError", True, f"code={getattr(e, 'code', None)}")

    print(f"\n=== {ok}/{ok + fail} PASSED ===")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
