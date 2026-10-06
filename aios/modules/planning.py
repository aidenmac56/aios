"""Planning: vision → goals → objectives → initiatives → projects → milestones → tasks.

Validation, dependency checks, contradiction detection and priority scoring are deterministic code.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aios.agents.schemas import PlanOutput
from aios.agents.specs import SPECS
from aios.core import audit, events, sysconfig
from aios.core.actor import Actor
from aios.core.errors import InvalidPlan, NotFound, ValidationFailed
from aios.core.permissions import db_write, require
from aios.core.util import cents_to_str, utcnow
from aios.db.enums import ApprovalStatus, MemoryStatus, ProjectStatus, TaskKind, TaskStatus
from aios.db.models import (
    Approval,
    Budget,
    Decision,
    Memory,
    Milestone,
    Objective,
    Project,
    ProjectDependency,
    Task,
    TaskDependency,
)

OPEN_TASK = (TaskStatus.PROPOSED, TaskStatus.PLANNED, TaskStatus.WAITING, TaskStatus.APPROVAL_REQUIRED,
             TaskStatus.READY, TaskStatus.RUNNING, TaskStatus.BLOCKED)


def topo_order(keys: list[str], deps: dict[str, list[str]]) -> list[str]:
    """Kahn's algorithm. Raises InvalidPlan on unknown dependency or cycle."""
    for k, ds in deps.items():
        for d in ds:
            if d not in keys:
                raise InvalidPlan(f"'{k}' depends on unknown '{d}'")
            if d == k:
                raise InvalidPlan(f"'{k}' depends on itself")
    indeg = {k: 0 for k in keys}
    for k, ds in deps.items():
        indeg[k] = len(set(ds))
    ready = [k for k in keys if indeg[k] == 0]
    order = []
    rev: dict[str, list[str]] = defaultdict(list)
    for k, ds in deps.items():
        for d in set(ds):
            rev[d].append(k)
    while ready:
        k = ready.pop(0)
        order.append(k)
        for n in rev[k]:
            indeg[n] -= 1
            if indeg[n] == 0:
                ready.append(n)
    if len(order) != len(keys):
        raise InvalidPlan("dependency cycle among: " + ", ".join(k for k in keys if k not in order))
    return order


def validate_plan(plan: PlanOutput) -> list[str]:
    """Structural checks. Returns warnings; raises InvalidPlan on errors."""
    warnings = []
    mkeys = [m.key for m in plan.milestones]
    if len(set(mkeys)) != len(mkeys):
        raise InvalidPlan("duplicate milestone keys")
    tkeys = [t.key for t in plan.tasks]
    if len(set(tkeys)) != len(tkeys):
        raise InvalidPlan("duplicate task keys")
    for t in plan.tasks:
        if t.milestone_key not in mkeys:
            raise InvalidPlan(f"task '{t.key}' points to unknown milestone '{t.milestone_key}'")
        if not t.completion_criteria.strip():
            raise InvalidPlan(f"task '{t.key}' has no completion criteria")
        if t.responsible != "founder" and t.responsible not in SPECS:
            warnings.append(f"task '{t.key}' owner '{t.responsible}' is not an agent; assigned to founder")
    topo_order(tkeys, {t.key: t.depends_on for t in plan.tasks})
    task_cost = sum(t.estimated_cost_usd for t in plan.tasks)
    if task_cost > plan.project.expected_cost_usd * 1.5 + 1:
        warnings.append(f"task costs (${task_cost:,.0f}) exceed project expected cost (${plan.project.expected_cost_usd:,.0f})")
    return warnings


def principles(session: Session) -> list[dict]:
    """Founder principles from config plus active EXPLICIT/CONFIRMED memories tagged principle:<key>."""
    out = list(sysconfig.get(session, "founder.principles") or [])
    mems = session.execute(select(Memory).where(Memory.status.in_([MemoryStatus.EXPLICIT, MemoryStatus.CONFIRMED]))).scalars()
    for m in mems:
        for tag in m.tags or []:
            if tag.startswith("principle:"):
                out.append({"key": tag.split(":", 1)[1], "memory_id": m.id, "text": m.content})
    return out


def contradictions(session: Session, *, new_project_cost_cents: int = 0, new_project_name: str | None = None) -> list[str]:
    issues: list[str] = []
    active = session.execute(select(Project).where(Project.status.in_([ProjectStatus.ACTIVE, ProjectStatus.BLOCKED]))).scalars().all()
    committed = sum(p.expected_cost_cents or 0 for p in active) + new_project_cost_cents
    for p in principles(session):
        if p.get("key") == "preserve_cash":
            ceiling = int(float(p.get("max_total_project_cost_usd", 1000)) * 100)
            if committed > ceiling:
                names = [x.name for x in active] + ([new_project_name] if new_project_name else [])
                issues.append(
                    f"Founder principle 'preserve cash' ({p.get('text') or 'configured'}) conflicts with "
                    f"{cents_to_str(committed)} of expected project cost across {len(names)} project(s) "
                    f"(ceiling {cents_to_str(ceiling)}): {', '.join(names)}")
    today = date.today()
    budgets = session.execute(select(Budget).where(Budget.period_start <= today, Budget.period_end >= today)).scalars().all()
    if budgets:
        total_budget = sum(b.amount_cents for b in budgets)
        if committed > total_budget:
            issues.append(f"Expected project costs {cents_to_str(committed)} exceed current budgets {cents_to_str(total_budget)}.")
    for dep in session.execute(select(ProjectDependency)).scalars():
        p, d = session.get(Project, dep.project_id), session.get(Project, dep.depends_on_id)
        if p and d and p.status not in (ProjectStatus.CANCELLED, ProjectStatus.COMPLETED) and d.status == ProjectStatus.CANCELLED:
            issues.append(f"Project '{p.name}' depends on cancelled project '{d.name}'.")
    for td in session.execute(select(TaskDependency)).scalars():
        t, d = session.get(Task, td.task_id), session.get(Task, td.depends_on_id)
        if t and d and t.status in OPEN_TASK and d.status == TaskStatus.CANCELLED:
            issues.append(f"Task '{t.title}' depends on cancelled task '{d.title}'.")
    p1 = [p for p in active if p.priority == 1]
    if len(p1) > 3:
        issues.append(f"{len(p1)} active projects are all priority 1; priorities are not being made.")
    return issues


def create_from_plan(session: Session, actor: Actor, plan: PlanOutput, *, decision_id: str | None = None,
                     workflow_run_id: str | None = None, company_id: str | None = None) -> dict:
    require(actor, db_write("planning"), action="create plan")
    warnings = validate_plan(plan)
    today = date.today()
    cost_cents = int(round(plan.project.expected_cost_usd * 100))
    issues = contradictions(session, new_project_cost_cents=cost_cents, new_project_name=plan.project.name)
    objective = Objective(title=plan.objective.title, metric=plan.objective.metric, target=plan.objective.target,
                          due_date=today + timedelta(days=plan.objective.due_in_days), decision_id=decision_id)
    session.add(objective)
    session.flush()
    project = Project(company_id=company_id, objective_id=objective.id, decision_id=decision_id, name=plan.project.name,
                      objective=plan.project.objective, reason=plan.project.reason,
                      expected_impact=plan.project.expected_impact, owner="founder",
                      status=ProjectStatus.PROPOSED if issues else ProjectStatus.ACTIVE,
                      priority=plan.project.priority, expected_cost_cents=cost_cents,
                      estimated_effort_hours=plan.project.estimated_effort_hours, risks=plan.project.risks,
                      success_criteria=plan.project.success_criteria)
    session.add(project)
    session.flush()
    mids = {}
    for i, m in enumerate(plan.milestones):
        ms = Milestone(project_id=project.id, title=m.title, due_date=today + timedelta(days=m.due_in_days),
                       success_criteria=m.success_criteria, order=i)
        session.add(ms)
        session.flush()
        mids[m.key] = ms.id
    tids = {}
    for t in plan.tasks:
        owner = t.responsible if (t.responsible == "founder" or t.responsible in SPECS) else "founder"
        status = TaskStatus.APPROVAL_REQUIRED if issues else (TaskStatus.PLANNED if t.depends_on else TaskStatus.READY)
        row = Task(kind=TaskKind.PLAN, title=t.title, description=t.description, project_id=project.id,
                   milestone_id=mids[t.milestone_key], workflow_run_id=workflow_run_id, objective=plan.objective.title,
                   responsible_agent=owner, creator=str(actor), priority=t.priority, status=status,
                   completion_criteria=t.completion_criteria, estimated_effort_hours=t.estimated_effort_hours,
                   estimated_cost_cents=int(round(t.estimated_cost_usd * 100)),
                   approval_state="PENDING" if issues else None)
        session.add(row)
        session.flush()
        tids[t.key] = row.id
        events.emit(session, events.TASK_CREATED, str(actor), {"task_id": row.id, "project_id": project.id}, workflow_run_id)
    for t in plan.tasks:
        for d in set(t.depends_on):
            session.add(TaskDependency(task_id=tids[t.key], depends_on_id=tids[d]))
    session.flush()
    approval_id = None
    if issues:
        from aios.core import approvals
        from aios.db.enums import ApprovalType

        appr = approvals.request(session, action=f"Activate project '{project.name}' despite: {issues[0]}",
                                 action_type=ApprovalType.PLAN, requested_by=str(actor),
                                 reason="The plan contradicts a founder principle or budget.", handler="plan.activate",
                                 payload={"project_id": project.id}, risks=issues, cost_cents=cost_cents,
                                 decision_id=decision_id, workflow_run_id=workflow_run_id)
        approval_id = appr.id
    events.emit(session, events.PROJECT_CREATED, str(actor), {"project_id": project.id, "status": project.status.value},
                workflow_run_id)
    audit.record(session, who=str(actor), what="planning.create", why=f"plan for: {plan.objective.title}",
                 output={"project_id": project.id, "tasks": len(tids), "milestones": len(mids),
                         "contradictions": issues, "warnings": warnings},
                 target_type="project", target_id=project.id)
    return {"objective_id": objective.id, "project_id": project.id, "milestone_ids": list(mids.values()),
            "task_ids": list(tids.values()), "status": project.status.value, "contradictions": issues,
            "warnings": warnings, "approval_id": approval_id}


def activate_project(session: Session, approval: Approval, actor: Actor) -> dict:
    project = session.get(Project, approval.payload["project_id"])
    if project is None:
        raise NotFound("project not found")
    project.status = ProjectStatus.ACTIVE
    for t in session.execute(select(Task).where(Task.project_id == project.id)).scalars():
        if t.status == TaskStatus.APPROVAL_REQUIRED:
            has_deps = session.execute(select(TaskDependency).where(TaskDependency.task_id == t.id)).first()
            t.status = TaskStatus.PLANNED if has_deps else TaskStatus.READY
            t.approval_state = "APPROVED"
    return {"project_id": project.id, "project_status": project.status.value}


def cancel_project_on_reject(session: Session, approval: Approval, actor: Actor) -> dict:
    project = session.get(Project, approval.payload["project_id"])
    if project is None:
        return {}
    project.status = ProjectStatus.CANCELLED
    for t in session.execute(select(Task).where(Task.project_id == project.id)).scalars():
        if t.status in OPEN_TASK:
            t.status = TaskStatus.CANCELLED
            t.approval_state = "REJECTED"
    return {"project_id": project.id, "project_status": project.status.value}


def update_task(session: Session, actor: Actor, task_id: str, *, status: TaskStatus | None = None,
                criteria_met: bool | None = None, result_note: str | None = None) -> Task:
    """Completion requires criteria_met; dependents become READY when their dependencies are done."""
    require(actor, db_write("planning"), action="update task")
    t = session.get(Task, task_id)
    if t is None:
        raise NotFound(f"task {task_id} not found")
    if criteria_met is not None:
        t.criteria_met = criteria_met
    if status == TaskStatus.COMPLETED:
        if t.kind == TaskKind.PLAN and not t.criteria_met:
            raise ValidationFailed("A task is completed only when its completion criteria are met. Set criteria_met first.",
                                   completion_criteria=t.completion_criteria)
        t.completed_at = utcnow()
    if status == TaskStatus.RUNNING and not t.started_at:
        t.started_at = utcnow()
    if status:
        t.status = status
    if result_note:
        t.result = {**(t.result or {}), "note": result_note}
    session.flush()
    if status == TaskStatus.COMPLETED:
        events.emit(session, events.TASK_COMPLETED, str(actor), {"task_id": t.id})
        for td in session.execute(select(TaskDependency).where(TaskDependency.depends_on_id == t.id)).scalars():
            dep = session.get(Task, td.task_id)
            others = session.execute(select(Task.status).join(TaskDependency, TaskDependency.depends_on_id == Task.id)
                                     .where(TaskDependency.task_id == dep.id)).scalars().all()
            if dep.status in (TaskStatus.PLANNED, TaskStatus.WAITING) and all(s == TaskStatus.COMPLETED for s in others):
                dep.status = TaskStatus.READY
    if status == TaskStatus.BLOCKED and t.project_id:
        events.emit(session, events.PROJECT_BLOCKED, str(actor), {"task_id": t.id, "project_id": t.project_id})
    audit.record(session, who=str(actor), what="task.update",
                 input={"status": status.value if status else None, "criteria_met": criteria_met},
                 target_type="task", target_id=t.id)
    return t


def priority_scores(session: Session) -> list[dict]:
    """Deterministic ranking of open plan tasks: priority, unlocks, due date, readiness."""
    tasks = session.execute(select(Task).where(Task.kind == TaskKind.PLAN, Task.status.in_(OPEN_TASK))).scalars().all()
    unlocks = dict(session.execute(select(TaskDependency.depends_on_id, func.count()).group_by(TaskDependency.depends_on_id)).all())
    today = date.today()
    out = []
    for t in tasks:
        score = (6 - t.priority) * 10 + unlocks.get(t.id, 0) * 5
        if t.status == TaskStatus.READY:
            score += 8
        if t.status in (TaskStatus.BLOCKED, TaskStatus.APPROVAL_REQUIRED):
            score -= 15
        if t.due_date:
            days = (t.due_date - today).days
            score += max(0, 14 - days)
        project = session.get(Project, t.project_id) if t.project_id else None
        if project and project.status not in (ProjectStatus.ACTIVE,):
            score -= 20
        out.append({"task_id": t.id, "title": t.title, "status": t.status.value, "priority": t.priority,
                    "project": project.name if project else None, "unlocks": unlocks.get(t.id, 0), "score": score,
                    "owner": t.responsible_agent})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def state(session: Session) -> dict:
    projects = session.execute(select(Project).order_by(Project.priority, Project.created_at.desc())).scalars().all()
    out_projects = []
    for p in projects:
        counts = dict(session.execute(select(Task.status, func.count()).where(Task.project_id == p.id).group_by(Task.status)).all())
        total = sum(counts.values())
        done = counts.get(TaskStatus.COMPLETED, 0)
        out_projects.append({"id": p.id, "name": p.name, "status": p.status.value, "priority": p.priority,
                             "expected_cost": cents_to_str(p.expected_cost_cents), "tasks_total": total, "tasks_done": done,
                             "progress_pct": round(done / total * 100) if total else 0, "decision_id": p.decision_id,
                             "blocked_tasks": counts.get(TaskStatus.BLOCKED, 0)})
    pending = session.execute(select(Approval).where(Approval.status == ApprovalStatus.PENDING)
                              .order_by(Approval.created_at.desc())).scalars().all()
    decisions = session.execute(select(Decision).where(Decision.status == "PENDING_APPROVAL")).scalars().all()
    return {"projects": out_projects,
            "pending_approvals": [{"id": a.id, "action": a.action, "type": a.action_type.value, "requested_by": a.requested_by}
                                  for a in pending],
            "decisions_waiting": [{"id": d.id, "question": d.question} for d in decisions],
            "top_tasks": priority_scores(session)[:10],
            "contradictions": contradictions(session)}
