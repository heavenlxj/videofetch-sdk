"""MCP server configuration.

MCP 客户端 (Claude Desktop / Cursor / Claude Code …) 通过配置文件里的 `env` 传这些值,
所以在 MCP 里**没有命令行参数** —— 一律走环境变量。

| 变量 | 默认 | 说明 |
|---|---|---|
| `VIDEOFETCH_API_KEY` | — | **必填**。`vf_live_sk_…` (Dashboard → API Keys) |
| `VIDEOFETCH_BASE_URL` | `https://api.vidfetch.dev` | 自托管 / 本地调试时改这里 |
| `VIDEOFETCH_MCP_MAX_WAIT` | `120` | 工具单次调用最多自己等多久 (秒); 硬顶 600 |
| `VIDEOFETCH_MCP_HTTP_TIMEOUT` | `30` | 单次 HTTP 超时 (秒) |
| `VIDEOFETCH_MCP_OUTPUT_DIR` | 当前工作目录 | 落盘白名单目录 (`save_to` 只能写到这里面) |
| `VIDEOFETCH_MCP_ALLOW_ANY_PATH` | `0` | `1` = 关掉白名单限制 (不建议) |

为什么 `save_to` 要限白名单: 工具会被 **LLM 决定**调用, 参数也是它填的。白名单把"模型把文件写到
`~/.ssh/authorized_keys`"这类事故从"可能"变成"不可能", 代价几乎为零。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_BASE_URL = "https://api.vidfetch.dev"
DEFAULT_MAX_WAIT = 120
HARD_MAX_WAIT = 600
DEFAULT_HTTP_TIMEOUT = 30.0


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, int(float(raw))))
    except ValueError:
        return default


def _env_float(name: str, default: float, lo: float, hi: float) -> float:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(lo, min(hi, float(raw)))
    except ValueError:
        return default


def _env_flag(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Config:
    api_key: str
    base_url: str
    max_wait_seconds: int
    http_timeout: float
    output_dir: str
    allow_any_path: bool

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)


def load() -> Config:
    """读一次环境变量。每次工具调用都重新读 —— 客户端可以中途改 env 而不重启。"""
    return Config(
        api_key=(os.getenv("VIDEOFETCH_API_KEY") or "").strip(),
        base_url=(os.getenv("VIDEOFETCH_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/"),
        max_wait_seconds=_env_int("VIDEOFETCH_MCP_MAX_WAIT", DEFAULT_MAX_WAIT, 0, HARD_MAX_WAIT),
        http_timeout=_env_float("VIDEOFETCH_MCP_HTTP_TIMEOUT", DEFAULT_HTTP_TIMEOUT, 1.0, 300.0),
        output_dir=os.path.abspath((os.getenv("VIDEOFETCH_MCP_OUTPUT_DIR") or os.getcwd()).strip()),
        allow_any_path=_env_flag("VIDEOFETCH_MCP_ALLOW_ANY_PATH"),
    )
