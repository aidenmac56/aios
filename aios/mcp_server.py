"""AIOS as an MCP server: drive the company OS by chatting in the Claude app (or any MCP client).

    aios mcp --install     add AIOS to the Claude desktop app (then restart the app)
    aios mcp               run the server on stdio (what the app starts)

The chat itself runs on your Claude subscription; agent work started from it still uses the API and
the same budgets. The tools act as the founder because the founder is the one chatting, so the client
asks you before each tool call. Two things stay outside the chat on purpose:
  - approving or rejecting approvals (founder authority; use the menu bar, dashboard or `aios approve`)
  - changing system configuration (budgets, routing, allowed shortcuts)
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any


INSTRUCTIONS = (
    "AIOS is Aiden McCaffery's AI Company OS. Use these tools to see his to-do list and the system's task "
    "queue, add or check off tasks, start agent workflows (ceo, research, draft, decision, plan, multi, ...), and "
    "read results. Workflows take 1-5 minutes: start_workflow returns a run id; poll get_run until it finishes. "
    "Paid work is budget-capped. You cannot approve approvals or change configuration: tell him the command instead. "
    "Never invent numbers; report what the tools return."
)
WORKFLOWS = ["ceo", "board", "research", "market", "opportunity", "decision", "cto", "plan", "priorities", "draft",
             "trends", "multi", "finance", "audit", "improve"]


def _json(x: Any) -> str:
    return json.dumps(x, default=str, indent=1)[:60000]


def build(sm=None):
    try:
        from mcp.server.mcpserver import MCPServer as Server  # mcp >= 2
    except ImportError:  # pragma: no cover - mcp 1.x
        from mcp.server.fastmcp import FastMCP as Server

    from aios.bootstrap import init
    from aios.core.actor import FOUNDER
    from aios.modules import status, todos, workqueue

    sm = sm or init()
    server = Server(name="aios", instructions=INSTRUCTIONS)
    running: dict[str, asyncio.Task] = {}

    def engine():
        from aios.llm.provider import build_registry
        from aios.orchestrator.engine import Engine

        return Engine(sm, build_registry)

    def resolve(table: str, prefix: str) -> str:
        from aios.cli import _resolve_id

        with sm() as s:
            return _resolve_id(s, table, prefix)

    @server.tool(description="Company snapshot: projects, tasks, approvals waiting, costs, finance state.")
    def company_status() -> str:
        with sm() as s:
            return _json(status.company_status(s))

    @server.tool(description="Aiden's own to-do list (things only he can do) plus what he finished today.")
    def my_todos() -> str:
        with sm() as s:
            return _json({"open": todos.open_todos(s), "done_today": todos.recently_done(s)})

    @server.tool(description="Add a to-do to Aiden's list. priority 1 (highest) to 5.")
    def add_todo(title: str, priority: int = 2) -> str:
        with sm() as s:
            t = todos.add(s, FOUNDER, title, priority=max(1, min(5, priority)))
            s.commit()
            return f"Added {t.id[:8]}: {t.title}"

    @server.tool(description="Check off one of Aiden's to-dos (id or 8-char prefix). Only when he says it's done.")
    def complete_todo(todo_id: str) -> str:
        with sm() as s:
            t = todos.complete(s, FOUNDER, resolve("tasks", todo_id), note="checked off via chat")
            s.commit()
            return f"Done: {t.title}"

    @server.tool(description="Reopen a to-do that was checked off by mistake.")
    def reopen_todo(todo_id: str) -> str:
        with sm() as s:
            t = todos.reopen(s, FOUNDER, resolve("tasks", todo_id))
            s.commit()
            return f"Reopened: {t.title}"

    @server.tool(description="The system's own task queue (tasks assigned to agents) with status and last error.")
    def system_queue() -> str:
        with sm() as s:
            return _json(workqueue.queue(s))

    @server.tool(description="Give the system a task. agent: cmo (writing), research, cfo, cto, strategy, product, coo.")
    def add_system_task(title: str, agent: str = "cmo", priority: int = 2) -> str:
        with sm() as s:
            t = workqueue.add(s, title, agent=agent, priority=max(1, min(5, priority)))
            s.commit()
            return f"Queued {t.id[:8]} for {agent}: {t.title}"

    @server.tool(description="Run up to max_tasks ready system tasks now (paid model calls, budget-capped). "
                             "Returns immediately; check system_queue or list_runs for results.")
    async def run_system_tasks(max_tasks: int = 3) -> str:
        if "work" in running and not running["work"].done():
            return "System tasks are already running."
        running["work"] = asyncio.create_task(workqueue.run_ready(sm, engine(), max_tasks=max(1, min(5, max_tasks))))
        with sm() as s:
            n = len(workqueue.runnable(s))
        return f"Started on up to {min(n, max_tasks)} of {n} ready tasks."

    @server.tool(description="Start an AIOS workflow. command: " + ", ".join(WORKFLOWS) + ". For multi, models is an "
                             "optional comma list. Returns a run id; call get_run to see progress and the result.")
    async def start_workflow(command: str, request: str = "", models: str = "") -> str:
        from aios.config import get_settings

        if command not in WORKFLOWS:
            return f"Unknown workflow. Use one of: {', '.join(WORKFLOWS)}"
        if command != "finance" and not get_settings().has_llm_credentials:
            return "ANTHROPIC_API_KEY is missing from .env."
        eng = engine()
        opts: dict[str, Any] = {"models": models} if models else {}
        if command == "finance" and not get_settings().has_llm_credentials:
            opts["no_commentary"] = True
        run_id = eng.create_run(command, request)
        running[run_id] = asyncio.create_task(eng.run(command, request, options=opts, run_id=run_id))
        return f"Started {command}: run {run_id}. Check it with get_run."

    @server.tool(description="A run's status, progress and result (full id or prefix).")
    def get_run(run_id: str) -> str:
        from aios.db.models import WorkflowRun

        with sm() as s:
            r = s.get(WorkflowRun, resolve("workflow_runs", run_id))
            return _json({"id": r.id, "command": r.command, "status": r.status.value, "cost_usd": r.total_cost_micros / 1e6,
                          "progress": (r.progress or [])[-12:], "error": r.error, "result": r.result})

    @server.tool(description="Most recent workflow runs.")
    def list_runs(limit: int = 15) -> str:
        from sqlalchemy import select

        from aios.db.models import WorkflowRun

        with sm() as s:
            rows = s.execute(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(max(1, min(50, limit)))).scalars()
            return _json([{"id": r.id, "command": r.command, "status": r.status.value, "request": r.request[:120],
                           "cost_usd": r.total_cost_micros / 1e6, "created": r.created_at} for r in rows])

    @server.tool(description="Approvals waiting on Aiden. You can't approve them; give him the command.")
    def pending_approvals() -> str:
        from aios.menubar import pending_approvals as pa

        with sm() as s:
            rows = pa(s)
        return _json([{**a, "to_approve": f"aios approve {a['id']}", "to_reject": f"aios reject {a['id']}"} for a in rows])

    @server.tool(description="Search founder and company memory (with status and provenance).")
    def search_memory(query: str) -> str:
        from sqlalchemy import or_, select

        from aios.db.enums import MemoryStatus
        from aios.db.models import Memory

        like = f"%{query}%"
        with sm() as s:
            rows = s.execute(select(Memory).where(Memory.status != MemoryStatus.SUPERSEDED,
                                                  or_(Memory.subject.ilike(like), Memory.content.ilike(like))).limit(25)).scalars()
            return _json([{"id": m.id[:8], "subject": m.subject, "content": m.content, "status": m.status.value,
                           "provenance": m.provenance.value} for m in rows])

    @server.tool(description="AI spend by agent, model, workflow and day.")
    def costs(days: int = 30) -> str:
        with sm() as s:
            return _json(status.costs(s, max(1, min(365, days))))

    @server.tool(description="Which AI providers/models are connected (Claude, Muse, ChatGPT, local) and their cost.")
    def models() -> str:
        from aios.llm.provider import build_registry
        from aios.orchestrator import multi

        reg = build_registry(require_anthropic=False)
        with sm() as s:
            return _json({"providers": multi.providers_status(s, reg), "models": multi.catalog(s, reg)})

    return server


def claude_config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def install(path: Path | None = None) -> Path:
    """Add (or update) the 'aios' entry in the Claude desktop app's MCP config. Keeps a backup."""
    path = path or claude_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, Any] = {}
    if path.exists():
        raw = path.read_text() or "{}"
        path.with_suffix(".json.bak").write_text(raw)
        cfg = json.loads(raw)
    cfg.setdefault("mcpServers", {})["aios"] = {"command": sys.executable, "args": ["-m", "aios.mcp_server"],
                                                "env": {"AIOS_LOG_LEVEL": "WARNING"}}
    path.write_text(json.dumps(cfg, indent=2))
    return path


def main() -> None:
    import logging

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)  # stdout carries the MCP protocol
    build().run()


if __name__ == "__main__":
    main()
