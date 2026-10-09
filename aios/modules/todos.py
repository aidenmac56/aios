"""The founder's to-do list: real-world things only he can do, outside the system.

A to-do is a PLAN task owned by the founder ("responsible_agent = founder"): tasks the planner gave him
inside projects, plus ones he adds himself (no project). Checking one off is the same completion the
rest of the system uses (planning.update_task): criteria marked met, status COMPLETED, TASK_COMPLETED
event, audit entry, and any tasks that were waiting on it become READY. `priorities`, `status` and the
agents all read that same state, so the system knows it's done.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.core.actor import Actor
from aios.core.errors import NotFound, PermissionDenied, ValidationFailed
from aios.core.util import utcnow
from aios.db.enums import TaskKind, TaskStatus
from aios.db.models import Project, Task
from aios.modules import planning

FOUNDER_OWNER = "founder"
# Open statuses worth showing. PROPOSED/APPROVAL_REQUIRED tasks belong to plans he hasn't approved yet.
SHOWN = (TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.PLANNED, TaskStatus.WAITING, TaskStatus.BLOCKED)


def _row(t: Task, project: Project | None) -> dict:
    return {"id": t.id, "title": t.title, "status": t.status.value, "priority": t.priority,
            "project": project.name if project else None, "due_date": t.due_date.isoformat() if t.due_date else None,
            "done": t.status == TaskStatus.COMPLETED, "waiting": t.status in (TaskStatus.PLANNED, TaskStatus.WAITING),
            "completion_criteria": t.completion_criteria, "description": t.description,
            "completed_at": t.completed_at.isoformat() if t.completed_at else None}


def _founder_tasks(session: Session):
    return (select(Task).where(Task.kind == TaskKind.PLAN, Task.responsible_agent == FOUNDER_OWNER))


def open_todos(session: Session) -> list[dict]:
    """Open founder to-dos, most important first (same scoring as `aios priorities`)."""
    rows = session.execute(_founder_tasks(session).where(Task.status.in_(SHOWN))).scalars().all()
    projects = {p.id: p for p in session.execute(select(Project)).scalars()}
    live = [t for t in rows if not t.project_id or projects[t.project_id].status.value in ("ACTIVE", "BLOCKED")]
    score = {x["task_id"]: x["score"] for x in planning.priority_scores(session)}
    today = date.today()

    def key(t: Task):
        overdue = 1 if t.due_date and t.due_date < today else 0
        waiting = 1 if t.status in (TaskStatus.PLANNED, TaskStatus.WAITING) else 0
        return (waiting, -overdue, -score.get(t.id, 0), t.priority, t.created_at)

    return [_row(t, projects.get(t.project_id)) for t in sorted(live, key=key)]


def recently_done(session: Session, hours: int = 24) -> list[dict]:
    since = utcnow() - timedelta(hours=hours)
    rows = session.execute(_founder_tasks(session).where(Task.status == TaskStatus.COMPLETED, Task.completed_at >= since)
                           .order_by(Task.completed_at.desc())).scalars().all()
    projects = {p.id: p for p in session.execute(select(Project)).scalars()}
    return [_row(t, projects.get(t.project_id)) for t in rows]


def add(session: Session, actor: Actor, title: str, *, priority: int = 2, due: date | None = None,
        note: str | None = None) -> Task:
    if actor.is_agent:  # the founder, or autopilot (system) handing him a real-world step
        raise PermissionDenied("Only the founder adds to his own to-do list; agents put tasks in plans.", actor=str(actor))
    title = title.strip()
    if not title:
        raise ValidationFailed("A to-do needs a title.")
    t = Task(kind=TaskKind.PLAN, title=title[:400], description=note, responsible_agent=FOUNDER_OWNER, creator=str(actor),
             priority=priority, status=TaskStatus.READY, due_date=due, completion_criteria="Founder checked it off.")
    session.add(t)
    session.flush()
    from aios.core import audit, events

    events.emit(session, events.TASK_CREATED, str(actor), {"task_id": t.id, "todo": True})
    audit.record(session, who=str(actor), what="todo.add", input={"title": t.title}, target_type="task", target_id=t.id)
    return t


def _get(session: Session, task_id: str) -> Task:
    t = session.get(Task, task_id)
    if t is None or t.responsible_agent != FOUNDER_OWNER or t.kind != TaskKind.PLAN:
        raise NotFound(f"No founder to-do {task_id}")
    return t


def complete(session: Session, actor: Actor, task_id: str, note: str | None = None) -> Task:
    if not actor.is_founder:
        raise PermissionDenied("Only the founder can check off his own to-dos.", actor=str(actor))
    t = _get(session, task_id)
    if t.status == TaskStatus.COMPLETED:
        return t
    return planning.update_task(session, actor, t.id, status=TaskStatus.COMPLETED, criteria_met=True,
                                result_note=note or "checked off by founder")


def reopen(session: Session, actor: Actor, task_id: str) -> Task:
    """Undo a check-off (a misclick). Tasks it had unlocked go back to waiting if they haven't started."""
    if not actor.is_founder:
        raise PermissionDenied("Only the founder can reopen his to-dos.", actor=str(actor))
    t = _get(session, task_id)
    if t.status != TaskStatus.COMPLETED:
        return t
    from aios.core import audit
    from aios.db.models import TaskDependency

    t.status, t.criteria_met, t.completed_at = TaskStatus.READY, False, None
    for td in session.execute(select(TaskDependency).where(TaskDependency.depends_on_id == t.id)).scalars():
        dep = session.get(Task, td.task_id)
        if dep and dep.status == TaskStatus.READY and not dep.started_at:
            dep.status = TaskStatus.PLANNED
    session.flush()
    audit.record(session, who=str(actor), what="todo.reopen", target_type="task", target_id=t.id)
    return t
