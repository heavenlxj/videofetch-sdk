"""VideoFetch MCP server package.

让任何支持 MCP 的 Agent (Claude Desktop / Claude Code / Cursor / VS Code / Windsurf …) 直接调用
VideoFetch 的下载能力, 无需用户手写 HTTP 客户端。
"""

from .server import SERVER_NAME, SERVER_VERSION, mcp

__all__ = ["mcp", "SERVER_NAME", "SERVER_VERSION", "__version__"]
__version__ = SERVER_VERSION
