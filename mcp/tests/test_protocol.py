"""MCP 协议级回归 —— 走真正的 MCP 握手 (in-memory transport), 不直接调 Python 函数。

为什么要这一层: 单测过了只说明"函数返回值对"; 真正决定 Agent 能不能用起来的是**协议层**是否
暴露了正确的工具名 / inputSchema (含 enum) / 结构化返回 / isError。工具描述的措辞也是产品的一部分
(模型就是靠它选工具的), 所以这里也断言关键句子在。
"""

from __future__ import annotations

import json

from mcp.shared.memory import create_connected_server_and_client_session

from videofetch_mcp import server

EXPECTED_TOOLS = ["video_info", "download_media", "get_download",
                  "list_downloads", "cancel_download", "account_usage"]
FORMATS = ["144p", "240p", "360p", "480p", "720p", "1080p", "1440p", "2160p", "mp3"]


async def test_lists_exactly_six_tools(api):
    async with create_connected_server_and_client_session(server.mcp) as s:
        res = await s.list_tools()
    assert [t.name for t in res.tools] == EXPECTED_TOOLS


async def test_download_tool_schema_is_agent_ready(api):
    async with create_connected_server_and_client_session(server.mcp) as s:
        tools = {t.name: t for t in (await s.list_tools()).tools}

    dl = tools["download_media"]
    props = dl.inputSchema["properties"]
    assert dl.inputSchema["required"] == ["url"]                 # 只有 url 必填 → 最容易起手
    assert props["format"]["enum"] == FORMATS                    # 枚举进 schema, 模型不会瞎编
    assert props["format"]["default"] == "720p"
    for p in ("start", "end", "destination_id", "webhook_url", "save_to", "wait_seconds"):
        assert p in props and props[p].get("description"), f"{p} 缺参数说明"

    # 工具描述要讲清"阻塞是有界的"和落盘前置条件 —— 模型据此决定要不要轮询
    assert "bounded" in dl.description.lower()
    assert "Only used when the job completes" in props["save_to"]["description"] \
        or "Must be inside" in props["save_to"]["description"]

    # 只读工具必须标记 (客户端据此做权限/确认提示)
    assert tools["video_info"].annotations.readOnlyHint is True
    assert tools["account_usage"].annotations.readOnlyHint is True
    assert tools["cancel_download"].annotations.destructiveHint is True


async def test_server_instructions_teach_the_flow(api):
    assert "20 MiB" in server.mcp.instructions            # 计费口径必须告诉模型
    assert "video_info" in server.mcp.instructions
    assert "get_download" in server.mcp.instructions
    assert "never ask the user for storage credentials" in server.mcp.instructions.lower()


async def test_call_tool_returns_json_text_payload(api):
    """契约 = **文本块永远是一段 JSON**(任何客户端都能读)。

    刻意不声明 outputSchema: 返回体的字段是动态裁剪的 (空值/无意义字段会被丢掉), 硬写一份
    TypedDict 只会引入"声明与运行时不符"的静默漂移, 收益却只是少一次 json.loads。
    """
    async with create_connected_server_and_client_session(server.mcp) as s:
        res = await s.call_tool("video_info", {"url": "https://youtu.be/aqz-KE-bpKQ"})
    assert res.isError is False
    payload = json.loads(res.content[0].text)
    assert payload["title"] == "Big Buck Bunny"
    # 文档里承诺的顶层字段 (docs: Agents & MCP -> Tool reference)
    assert {"ok", "video_id", "title", "duration_seconds", "available_formats",
            "next_step"} <= set(payload)


async def test_call_tool_end_to_end_download(api):
    async with create_connected_server_and_client_session(server.mcp) as s:
        res = await s.call_tool("download_media", {
            "url": "https://youtu.be/aqz-KE-bpKQ", "format": "mp3", "start": 0, "end": 10})
        payload = json.loads(res.content[0].text)
        assert payload["status"] == "completed"

        job = payload["job_id"]
        got = json.loads((await s.call_tool("get_download", {"job_id": job})).content[0].text)
        assert got["status"] == "completed" and got["size_bytes"] == 481213


async def test_protocol_error_is_flagged_and_readable(api):
    async with create_connected_server_and_client_session(server.mcp) as s:
        res = await s.call_tool("get_download", {"job_id": "dl_nope"})
    assert res.isError is True                            # 客户端会把它渲染成错误, 不是"成功但空"
    msg = res.content[0].text
    assert "not_found" in msg and "list_downloads" in msg


async def test_exposes_a_prompt_for_one_click_onboarding(api):
    async with create_connected_server_and_client_session(server.mcp) as s:
        prompts = await s.list_prompts()
    names = [p.name for p in prompts.prompts]
    assert "download_prompt" in names
    async with create_connected_server_and_client_session(server.mcp) as s:
        got = await s.get_prompt("download_prompt", {"url": "https://youtu.be/x", "format": "mp3"})
    text = got.messages[0].content.text
    assert "video_info" in text and "get_download" in text and "mp3" in text
