"""The system's own to-do list: plan tasks assigned to an agent instead of the founder.

    aios work            show the queue
    aios work run        do the ready ones now (or click "Run system tasks" in the menu bar)

Each task runs as the workflow that fits it (research, draft, finance, ...), with the task's title,
description and completion criteria as the request. Nothing here runs by itself: the founder starts a
run, every run is budget-checked like any other workflow, and decisions that need him still stop for
his approval.

When a run finishes, its task is completed with the run as evidence. If the output isn't good enough,
he reopens it (`aios work reopen <id>`) and it goes back in the queue.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from aios.core import audit
from aios.core.actor import FOUNDER
from aios.core.errors import NotFound
from aios.db.enums import TaskKind, TaskStatus
from aios.db.models import Project, Task
from aios.modules import planning

QUEUED = (TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.PLANNED, TaskStatus.WAITING, TaskStatus.FAILED)

# Which workflow does an agent's task. Never `plan` or `ceo`: those create projects and would grow the queue.
BY_AGENT = {
    "research": "research", "cmo": "draft", "twin": "draft", "product": "draft", "coo": "draft",
    "cfo": "finance", "cto": "cto", "strategy": "decision", "ceo": "decision", "risk": "decision",
    "analytics": "audit",
}
BY_WORDS = [
    (r"\b(research|compare|find|look up|investigate|evaluate tools?|benchmark|survey)\b", "research"),
    (r"\b(draft|write|script|outline|email|post|copy|caption|template|topics?|newsletter|lead magnet)\b", "draft"),
    (r"\b(market|competitor|positioning|niche)\b", "market"),
    (r"\b(decide|choose|pick|pricing|price)\b", "decision"),
    (r"\b(budget|spend|cost|cash|revenue)\b", "finance"),
]


def workflow_for(task: Task) -> str:
    text = f"{task.title} {task.description or ''}".lower()
    for pattern, wf in BY_WORDS:
        if re.search(pattern, text):
            return wf
    return BY_AGENT.get(task.responsible_agent or "", "draft")


def request_for(task: Task, project: Project | None) -> str:
    parts = [task.title]
    if task.description:
        parts.append(task.description)
    if task.completion_criteria:
        parts.append(f"Done when: {task.completion_criteria}")
    if project:
        parts.append(f"(Part of project: {project.name})")
    why = (task.result or {}).get("reopened_because")
    if why:  # the founder sent the last attempt back: revise it, don't start over blind
        parts.append(f"The founder rejected the previous version. His feedback: {why}")
        prev = _previous_output(task)
        if prev:
            parts.append(f"Previous version, to revise:\n{prev}")
    return "\n".join(parts)


def _previous_output(task: Task) -> str | None:
    from sqlalchemy.orm import object_session

    from aios.db.models import WorkflowRun

    run_id = (task.result or {}).get("run_id")
    s = object_session(task)
    run = s.get(WorkflowRun, run_id) if (s and run_id) else None
    items = (((run.result or {}).get("draft") or {}).get("items") or []) if run else []
    text = "\n\n".join(f"[{i['label']}]\n{i['text']}" for i in items)
    return text[:6000] or None


def _live_projects(session: Session) -> dict[str, Project]:
    return {p.id: p for p in session.execute(select(Project)).scalars()}


def queue(session: Session) -> list[dict]:
    projects = _live_projects(session)
    rows = session.execute(select(Task).where(Task.kind == TaskKind.PLAN, Task.responsible_agent.is_not(None),
                                              Task.responsible_agent != "founder", Task.status.in_(QUEUED))
                           .order_by(Task.priority, Task.created_at)).scalars().all()
    out = []
    for t in rows:
        p = projects.get(t.project_id)
        if p is not None and p.status.value not in ("ACTIVE", "BLOCKED"):
            continue
        out.append({"id": t.id, "title": t.title, "agent": t.responsible_agent, "status": t.status.value,
                    "priority": t.priority, "workflow": workflow_for(t), "project": p.name if p else None,
                    "last_run": (t.result or {}).get("run_id"), "error": t.error})
    return out


def runnable(session: Session) -> list[dict]:
    return [q for q in queue(session) if q["status"] in ("READY", "FAILED")]


def reopen(session: Session, task_id: str, why: str) -> Task:
    t = session.get(Task, task_id)
    if t is None or t.responsible_agent in (None, "founder"):
        raise NotFound(f"No system task {task_id}")
    t.status, t.criteria_met, t.completed_at = TaskStatus.READY, False, None
    t.result = {**(t.result or {}), "reopened_because": why}
    audit.record(session, who="founder", what="work.reopen", why=why, target_type="task", target_id=t.id)
    return t


async def run_ready(sm: sessionmaker, engine, *, max_tasks: int = 3, budget_usd: float | None = None,
                    on_task=None, actor=FOUNDER, budget_for_next=None) -> list[dict[str, Any]]:
    """Run up to `max_tasks` ready system tasks, one after another. Stops at the first budget stop."""
    with sm() as s:
        todo = runnable(s)[:max_tasks]
    results = []
    for item in todo:
        if budget_for_next is not None:  # autopilot: stop when its daily cap can't cover another task
            budget_usd = budget_for_next()
            if budget_usd is None:
                break
        with sm() as s:
            t = s.get(Task, item["id"])
            if t.status not in (TaskStatus.READY, TaskStatus.FAILED):  # someone else picked it up
                continue
            planning.update_task(s, actor, t.id, status=TaskStatus.RUNNING)
            request = request_for(t, s.get(Project, t.project_id) if t.project_id else None)
            s.commit()
        if on_task:
            on_task(item)
        opts = {"budget_usd": budget_usd} if budget_usd else {}
        res = await engine.run(item["workflow"], request, options=opts, actor=actor)
        status = res["status"]
        with sm() as s:
            t = s.get(Task, item["id"])
            t.result = {**(t.result or {}), "run_id": res["run_id"], "workflow": item["workflow"], "run_status": status}
            t.evidence = [*(t.evidence or []), {"workflow_run_id": res["run_id"]}]
            t.actual_cost_micros = (t.actual_cost_micros or 0) + int(round(res.get("cost_usd", 0) * 1e6))
            if status == "COMPLETED":
                t.error = None
                planning.update_task(s, actor, t.id, status=TaskStatus.COMPLETED, criteria_met=True,
                                     result_note=f"done by the system: {item['workflow']} run {res['run_id']}")
            elif status == "AWAITING_APPROVAL":  # a decision that needs the founder: his move now
                t.error = None
                planning.update_task(s, actor, t.id, status=TaskStatus.WAITING,
                                     result_note=f"waiting on your approval {res.get('approval_id')}")
            else:
                t.error = ((res.get("error") or {}).get("message") or res.get("stopped") or status)[:500]
                planning.update_task(s, actor, t.id, status=TaskStatus.FAILED)
            s.commit()
        results.append({"task": item["title"], "workflow": item["workflow"], "status": status, "run_id": res["run_id"],
                        "cost_usd": res.get("cost_usd", 0), "approval_id": res.get("approval_id")})
        if res.get("stopped") == "budget":
            break
    return results


def add(session: Session, title: str, *, agent: str = "cmo", priority: int = 2, note: str | None = None,
        actor=FOUNDER) -> Task:
    """The founder (or autopilot) hands the system a task."""
    from aios.agents.specs import SPECS
    from aios.core.errors import ValidationFailed

    if agent not in SPECS:
        raise ValidationFailed(f"Unknown agent '{agent}'. Known: {', '.join(SPECS)}")
    if actor.is_agent:
        from aios.core.errors import PermissionDenied

        raise PermissionDenied("Agents propose tasks through plans, not the queue.", actor=str(actor))
    t = Task(kind=TaskKind.PLAN, title=title.strip()[:400], description=note, responsible_agent=agent, creator=str(actor),
             priority=priority, status=TaskStatus.READY, completion_criteria="The workflow run completed with output.")
    session.add(t)
    session.flush()
    audit.record(session, who=str(actor), what="work.add", input={"title": t.title, "agent": agent},
                 target_type="task", target_id=t.id)
    return t


def assign(session: Session, task_id: str, agent: str) -> Task:
    """Move a task between the founder's list and the system's ("founder" or an agent id)."""
    from aios.agents.specs import SPECS
    from aios.core.errors import ValidationFailed

    if agent != "founder" and agent not in SPECS:
        raise ValidationFailed(f"Unknown agent '{agent}'. Known: founder, {', '.join(SPECS)}")
    t = session.get(Task, task_id)
    if t is None or t.kind != TaskKind.PLAN:
        raise NotFound(f"No task {task_id}")
    old, t.responsible_agent = t.responsible_agent, agent
    audit.record(session, who="founder", what="task.assign", input={"from": old, "to": agent},
                 target_type="task", target_id=t.id)
    return t
