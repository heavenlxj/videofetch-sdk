"""队列优先级与留存字段解析（2026-11-04，v0.6.0）。

## 背景
API 新增 6 个 Download 字段：
  · queue_priority / lane / higher_priority_ahead / queue_message  —— 队列可见性
  · file_expires_at / retention_days                              —— 留存策略

## 本测试锁定的契约
  1. 4 个队列优先级字段能正确解析
  2. queue_priority / lane 在**终态**也存在（描述账号，不是队列快照）
  3. queue_position / ahead_of_you 在终态应为 None（真正的快照字段）
  4. 留存字段能正确解析
  5. 未知字段不会让 from_dict 崩溃（向前兼容）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from videofetch.models import Download


def _queued(**over):
    base = {"id": "dl_1", "status": "queued", "url": "https://youtu.be/x", "format": "360p"}
    base.update(over)
    return Download.from_dict(base)


def _completed(**over):
    base = {"id": "dl_2", "status": "completed", "url": "https://youtu.be/x", "format": "720p"}
    base.update(over)
    return Download.from_dict(base)


def test_queue_priority_fields_parse():
    d = _queued(
        queue_position=2,
        ahead_of_you=1,
        estimated_wait_seconds=45,
        queue_priority=85,
        lane="paid",
        higher_priority_ahead=0,
        queue_message="1 job ahead · about 1 min.",
    )
    assert d.queue_priority == 85
    assert d.lane == "paid"
    assert d.higher_priority_ahead == 0
    assert d.queue_message == "1 job ahead · about 1 min."


def test_free_tier_shows_upgrade_hint():
    d = _queued(
        queue_position=5, ahead_of_you=4, estimated_wait_seconds=120,
        queue_priority=30, lane="free", higher_priority_ahead=2,
        queue_message="4 jobs ahead · about 2 min. Upgrading moves your jobs to the priority queue.",
    )
    assert d.queue_priority == 30
    assert d.lane == "free"
    assert "Upgrading" in d.queue_message


def test_priority_survives_terminal_state():
    """queue_priority / lane 是账号属性 —— 任务完成后仍然要给。"""
    d = _completed(
        queue_priority=70, lane="free",
        queue_position=None, ahead_of_you=None, estimated_wait_seconds=None,
    )
    assert d.queue_priority == 70
    assert d.lane == "free"


def test_snapshot_fields_are_none_when_not_queued():
    """queue_position 等是队列快照 —— 非 queued 必须为 None。"""
    d = _completed(queue_priority=70, lane="paid")
    assert d.queue_position is None
    assert d.ahead_of_you is None
    assert d.estimated_wait_seconds is None


def test_retention_fields_parse():
    d = _completed(file_expires_at="2026-12-01T00:00:00Z", retention_days=30)
    assert d.file_expires_at == "2026-12-01T00:00:00Z"
    assert d.retention_days == 30


def test_unknown_fields_do_not_break_parsing():
    """API 以后加字段，旧 SDK 不能崩。"""
    d = _completed(some_future_field="whatever", another=123)
    assert d.id == "dl_2"
    assert d.queue_priority is None   # 未提供 → None，不是异常
