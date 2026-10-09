"""AIOS MCP server: tools work against the real database; founder-authority actions are not exposed."""

import json

import pytest

pytest.importorskip("mcp")

from aios import mcp_server  # noqa: E402


def _text(res) -> str:
    content = res[0] if isinstance(res, tuple) else res
    if hasattr(content, "content"):
        content = content.content
    return "".join(getattr(c, "text", "") for c in content)


async def test_tools_and_todo_round_trip(sm):
    server = mcp_server.build(sm)
    names = {t.name for t in await server.list_tools()}
    assert {"my_todos", "add_todo", "complete_todo", "start_workflow", "get_run", "system_queue", "pending_approvals"} <= names
    assert not any(n.startswith(("approve", "reject", "set_config")) for n in names)  # founder-only stays out of chat
    added = _text(await server.call_tool("add_todo", {"title": "Record voice clip", "priority": 1}))
    tid = added.split()[1].rstrip(":")
    assert "Record voice clip" in [t["title"] for t in json.loads(_text(await server.call_tool("my_todos", {})))["open"]]
    assert "Done" in _text(await server.call_tool("complete_todo", {"todo_id": tid}))
    body = json.loads(_text(await server.call_tool("my_todos", {})))
    assert body["open"] == [] and body["done_today"][0]["title"] == "Record voice clip"


async def test_unknown_workflow_is_refused(sm):
    server = mcp_server.build(sm)
    assert "Unknown workflow" in _text(await server.call_tool("start_workflow", {"command": "rm -rf", "request": "x"}))


def test_install_merges_with_existing_claude_config(tmp_path):
    cfg = tmp_path / "claude_desktop_config.json"
    cfg.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    mcp_server.install(cfg)
    data = json.loads(cfg.read_text())
    assert data["theme"] == "dark" and "other" in data["mcpServers"]
    assert data["mcpServers"]["aios"]["args"] == ["-m", "aios.mcp_server"]
    assert (tmp_path / "claude_desktop_config.json.bak").exists()
