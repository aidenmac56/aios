"""HTTP API for the command center. Local, single-founder. Every request acts as the founder.

Run with `aios serve` (binds 127.0.0.1 by default). Set AIOS_API_TOKEN to require a bearer token.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select

from aios.bootstrap import init
from aios.config import get_settings
from aios.core import approvals, audit, sysconfig
from aios.core.actor import FOUNDER
from aios.core.errors import AIOSError, MissingCredentials
from aios.core.util import micros_to_usd, to_cents
from aios.db.enums import ApprovalStatus, MemoryCategory, MemoryStatus, Provenance, TaskStatus
from aios.db.models import (
    AgentRun,
    Approval,
    Audit,
    AuditLog,
    Decision,
    EventRecord,
    Improvement,
    Memory,
    MetricDefinition,
    Milestone,
    Project,
    ResearchReport,
    Task,
    TaskDependency,
    Transaction,
    WorkflowRun,
)
from aios.modules import decisions, finance, improvements, memory, planning, research, status
from aios.orchestrator.engine import Engine

STATUS_CODES = {"permission_denied": 403, "not_found": 404, "missing_credentials": 400, "approval_required": 409,
                "budget_exceeded": 402}

_state: dict[str, Any] = {"tasks": set()}


@asynccontextmanager
async def lifespan(_: FastAPI):
    sm()
    yield
    for t in list(_state["tasks"]):  # user-started workflows finish their current step and are recorded as failed
        t.cancel()


app = FastAPI(title="AI Company OS", version="0.1.0", lifespan=lifespan)


def sm():
    if "sm" not in _state:
        _state["sm"] = init()
    return _state["sm"]


def engine() -> Engine:
    if "engine" not in _state:
        from aios.llm.provider import build_registry

        _state["engine"] = Engine(sm(), build_registry)
    return _state["engine"]


def auth(authorization: str | None = Header(default=None)) -> None:
    token = get_settings().api_token
    if token and authorization != f"Bearer {token}":
        raise HTTPException(401, "missing or invalid bearer token")


@app.exception_handler(AIOSError)
async def _aios_error(_: Request, exc: AIOSError):
    return JSONResponse(status_code=STATUS_CODES.get(exc.code, 400), content=exc.to_dict())


def _session():
    with sm()() as s:
        yield s


api = Depends(auth)


# ------------------------------------------------------------------ overview


@app.get("/api/health")
def health():
    s = get_settings()
    return {"ok": True, "llm_credentials": s.has_llm_credentials, "web_search": s.web_search_enabled}


@app.get("/api/status", dependencies=[api])
def get_status(s=Depends(_session)):
    return status.company_status(s)


@app.get("/api/agents", dependencies=[api])
def get_agents(s=Depends(_session)):
    return status.agents_view(s)


@app.get("/api/agents/{agent_id}", dependencies=[api])
def get_agent(agent_id: str, s=Depends(_session)):
    view = next((a for a in status.agents_view(s) if a["id"] == agent_id), None)
    if view is None:
        raise HTTPException(404, "agent not found")
    from aios.agents import registry

    runs = s.execute(select(AgentRun).where(AgentRun.agent_id == agent_id).order_by(AgentRun.created_at.desc()).limit(20)).scalars()
    versions = list(reversed(registry.versions(s, agent_id)))
    for v in versions:
        v["rollback_to"] = v.pop("rollback_to_version")
    return {**view, "versions": versions, "system_prompt": registry.active_config(s, agent_id).system_prompt,
            "recent_runs": [_run_row(r) for r in runs]}


class ActivateIn(BaseModel):
    version: int
    why: str = Field(min_length=3, max_length=500)


@app.post("/api/agents/{agent_id}/activate", dependencies=[api])
def activate_agent_version(agent_id: str, body: ActivateIn, s=Depends(_session)):
    from aios.agents import registry
    from aios.agents.specs import SPECS

    if agent_id not in SPECS:
        raise HTTPException(404, "agent not found")
    registry.activate_version(s, agent_id, body.version, "founder", None, body.why)
    s.commit()
    return {"agent_id": agent_id, "active_version": body.version}


@app.get("/api/experiments", dependencies=[api])
def list_experiments(s=Depends(_session)):
    from aios.db.models import Experiment

    return [{"id": e.id, "hypothesis": e.hypothesis, "metric": e.metric, "variant_a": e.variant_a,
             "variant_b": e.variant_b, "results": e.results, "status": e.status, "conclusion": e.conclusion,
             "improvement_id": e.improvement_id, "domain": e.domain, "created_at": e.created_at.isoformat()}
            for e in s.execute(select(Experiment).order_by(Experiment.created_at.desc()).limit(100)).scalars()]


def _run_row(r: AgentRun) -> dict:
    return {"id": r.id, "agent_id": r.agent_id, "workflow_run_id": r.workflow_run_id, "status": r.status.value,
            "objective": r.objective,
            "model": r.model, "tier": r.tier, "routing_reason": r.routing_reason, "cost_usd": micros_to_usd(r.cost_micros),
            "duration_ms": r.duration_ms, "retries": r.retries, "error": r.error,
            "summary": (r.output or {}).get("summary") or (r.output or {}).get("conclusion"),
            "started_at": r.started_at.isoformat() if r.started_at else None}


@app.get("/api/costs", dependencies=[api])
def get_costs(days: int = 30, s=Depends(_session)):
    return status.costs(s, days)


@app.get("/api/metrics", dependencies=[api])
def get_metrics(s=Depends(_session)):
    return [{"key": m.key, "name": m.name, "formula": m.formula, "unit": m.unit, "description": m.description}
            for m in s.execute(select(MetricDefinition)).scalars()]


@app.get("/api/events", dependencies=[api])
def get_events(limit: int = 50, s=Depends(_session)):
    return [{"id": e.id, "type": e.type, "actor": e.actor, "payload": e.payload, "workflow_run_id": e.workflow_run_id,
             "at": e.created_at.isoformat()}
            for e in s.execute(select(EventRecord).order_by(EventRecord.created_at.desc()).limit(min(limit, 500))).scalars()]


@app.get("/api/audit-log", dependencies=[api])
def get_audit_log(limit: int = 100, s=Depends(_session)):
    return [{"seq": e.seq, "at": e.at.isoformat(), "who": e.who, "what": e.what, "why": e.why, "result": e.result,
             "error": e.error, "cost_usd": micros_to_usd(e.cost_micros), "target_type": e.target_type,
             "target_id": e.target_id, "approval_id": e.approval_id}
            for e in s.execute(select(AuditLog).order_by(AuditLog.seq.desc()).limit(min(limit, 1000))).scalars()]


@app.get("/api/audit-log/verify", dependencies=[api])
def verify_log(s=Depends(_session)):
    return audit.verify_chain(s)


# ------------------------------------------------------------------ commands + runs


class CommandIn(BaseModel):
    request: str = Field(default="", max_length=8000)
    options: dict[str, Any] = Field(default_factory=dict)


ALLOWED_OPTIONS = {"importance", "budget_usd", "force", "decision_id", "research", "no_commentary", "focus",
                   "improvement_id"}


@app.post("/api/commands/{command}", dependencies=[api])
async def run_command(command: str, body: CommandIn):
    opts = {k: v for k, v in body.options.items() if k in ALLOWED_OPTIONS}
    eng = engine()
    if not get_settings().has_llm_credentials:
        if command != "finance":
            raise MissingCredentials("ANTHROPIC_API_KEY is not set on the server. Add it to .env and restart.")
        opts["no_commentary"] = True  # numbers still work without a model
    run_id = eng.create_run(command, body.request, FOUNDER, opts.get("importance", "normal"))
    task = asyncio.create_task(eng.run(command, body.request, options=opts, run_id=run_id))
    _state["tasks"].add(task)
    task.add_done_callback(_state["tasks"].discard)
    return {"run_id": run_id, "status": "RUNNING"}


@app.get("/api/runs", dependencies=[api])
def list_runs(limit: int = 30, s=Depends(_session)):
    return [{"id": r.id, "command": r.command, "request": r.request, "status": r.status.value,
             "cost_usd": micros_to_usd(r.total_cost_micros), "created_at": r.created_at.isoformat(),
             "finished_at": r.finished_at.isoformat() if r.finished_at else None, "decision_id": r.decision_id}
            for r in s.execute(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(min(limit, 200))).scalars()]


@app.get("/api/runs/{run_id}", dependencies=[api])
def get_run(run_id: str, s=Depends(_session)):
    r = s.get(WorkflowRun, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    runs = s.execute(select(AgentRun).where(AgentRun.workflow_run_id == run_id).order_by(AgentRun.created_at)).scalars()
    return {"id": r.id, "command": r.command, "request": r.request, "status": r.status.value, "importance": r.importance,
            "understanding": r.understanding, "plan": r.plan, "result": r.result, "progress": r.progress,
            "cost_usd": micros_to_usd(r.total_cost_micros), "budget_usd": micros_to_usd(r.budget_limit_micros),
            "error": r.error, "decision_id": r.decision_id, "created_at": r.created_at.isoformat(),
            "agent_runs": [_run_row(x) for x in runs]}


# ------------------------------------------------------------------ approvals + decisions


class NoteIn(BaseModel):
    note: str | None = None
    run_follow_up: bool = True


@app.get("/api/approvals", dependencies=[api])
def list_approvals(state: str | None = Query(default=None, alias="status"), s=Depends(_session)):
    q = select(Approval).order_by(Approval.created_at.desc()).limit(100)
    if state:
        if state not in ApprovalStatus.__members__:
            raise HTTPException(400, f"status must be one of {', '.join(ApprovalStatus.__members__)}")
        q = q.where(Approval.status == ApprovalStatus(state))
    return [_approval_row(a) for a in s.execute(q).scalars()]


@app.get("/api/approvals/{approval_id}", dependencies=[api])
def get_approval(approval_id: str, s=Depends(_session)):
    a = s.get(Approval, approval_id)
    if a is None:
        raise HTTPException(404, "approval not found")
    return _approval_row(a)


def _approval_row(a: Approval) -> dict:
    return {"id": a.id, "action": a.action, "type": a.action_type.value, "requested_by": a.requested_by,
             "reason": a.reason, "expected_effect": a.expected_effect, "risks": a.risks,
             "cost_usd": (a.cost_cents or 0) / 100 if a.cost_cents is not None else None, "status": a.status.value,
             "approver": a.approver, "decided_at": a.decided_at.isoformat() if a.decided_at else None,
             "decision_id": a.decision_id, "created_at": a.created_at.isoformat()}


@app.post("/api/approvals/{approval_id}/{action}", dependencies=[api])
async def decide(approval_id: str, action: str, body: NoteIn):
    if action not in ("approve", "reject"):
        raise HTTPException(404)
    with sm()() as s:
        fn = approvals.approve if action == "approve" else approvals.reject
        res = fn(s, approval_id, FOUNDER, body.note)
        s.commit()
    started = []
    if body.run_follow_up and get_settings().has_llm_credentials:
        eng = engine()
        for f in res.get("follow_up", []):  # caused by the approval the founder just gave
            run_id = eng.create_run(f["workflow"], "", FOUNDER)
            t = asyncio.create_task(eng.run(f["workflow"], "", options={"decision_id": f["decision_id"]}, run_id=run_id))
            _state["tasks"].add(t)
            t.add_done_callback(_state["tasks"].discard)
            started.append({"workflow": f["workflow"], "run_id": run_id})
    return {**res, "follow_up_runs": started}


@app.get("/api/decisions", dependencies=[api])
def list_decisions(s=Depends(_session)):
    return [decisions.to_dict(d) for d in s.execute(select(Decision).order_by(Decision.created_at.desc()).limit(200)).scalars()]


@app.get("/api/decisions/{decision_id}", dependencies=[api])
def get_decision(decision_id: str, s=Depends(_session)):
    d = s.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404)
    return decisions.to_dict(d)


class OutcomeIn(BaseModel):
    actual_result: str
    assessment: str
    why: str


@app.post("/api/decisions/{decision_id}/outcome", dependencies=[api])
def outcome(decision_id: str, body: OutcomeIn, s=Depends(_session)):
    d = decisions.record_outcome(s, FOUNDER, decision_id, actual_result=body.actual_result, assessment=body.assessment,
                                 why=body.why)
    s.commit()
    return decisions.to_dict(d)


# ------------------------------------------------------------------ planning


@app.get("/api/projects", dependencies=[api])
def list_projects(s=Depends(_session)):
    return planning.state(s)


@app.get("/api/projects/{project_id}", dependencies=[api])
def get_project(project_id: str, s=Depends(_session)):
    p = s.get(Project, project_id)
    if p is None:
        raise HTTPException(404)
    ms = s.execute(select(Milestone).where(Milestone.project_id == p.id).order_by(Milestone.order)).scalars().all()
    tasks = s.execute(select(Task).where(Task.project_id == p.id).order_by(Task.priority)).scalars().all()
    ids = [t.id for t in tasks]
    deps = s.execute(select(TaskDependency).where(TaskDependency.task_id.in_(ids))).scalars().all() if ids else []
    return {"id": p.id, "name": p.name, "objective": p.objective, "reason": p.reason, "expected_impact": p.expected_impact,
            "status": p.status.value, "priority": p.priority, "expected_cost_usd": (p.expected_cost_cents or 0) / 100,
            "estimated_effort_hours": p.estimated_effort_hours, "risks": p.risks, "success_criteria": p.success_criteria,
            "blockers": p.blockers, "decision_id": p.decision_id,
            "milestones": [{"id": m.id, "title": m.title, "due_date": m.due_date.isoformat() if m.due_date else None,
                            "success_criteria": m.success_criteria, "status": m.status} for m in ms],
            "tasks": [_task_row(t) for t in tasks],
            "dependencies": [{"task_id": d.task_id, "depends_on_id": d.depends_on_id} for d in deps]}


def _task_row(t: Task) -> dict:
    return {"id": t.id, "title": t.title, "description": t.description, "status": t.status.value, "priority": t.priority,
            "owner": t.responsible_agent, "milestone_id": t.milestone_id, "completion_criteria": t.completion_criteria,
            "criteria_met": t.criteria_met, "estimated_effort_hours": t.estimated_effort_hours,
            "estimated_cost_usd": (t.estimated_cost_cents or 0) / 100, "due_date": t.due_date.isoformat() if t.due_date else None}


class TaskIn(BaseModel):
    status: str | None = None
    criteria_met: bool | None = None
    note: str | None = None


@app.patch("/api/tasks/{task_id}", dependencies=[api])
def patch_task(task_id: str, body: TaskIn, s=Depends(_session)):
    t = planning.update_task(s, FOUNDER, task_id, status=TaskStatus(body.status) if body.status else None,
                             criteria_met=body.criteria_met, result_note=body.note)
    s.commit()
    return _task_row(t)


@app.get("/api/tasks", dependencies=[api])
def list_tasks(s=Depends(_session)):
    return planning.priority_scores(s)


# ------------------------------------------------------------------ research


@app.get("/api/research", dependencies=[api])
def list_research(s=Depends(_session)):
    research.refresh_staleness(s)
    s.commit()
    return [research.to_dict(r, with_claims=False)
            for r in s.execute(select(ResearchReport).order_by(ResearchReport.created_at.desc()).limit(200)).scalars()]


@app.get("/api/research/{report_id}", dependencies=[api])
def get_research(report_id: str, s=Depends(_session)):
    r = s.get(ResearchReport, report_id)
    if r is None:
        raise HTTPException(404)
    return research.to_dict(r)


# ------------------------------------------------------------------ finance


@app.get("/api/finance/summary", dependencies=[api])
def fin_summary(s=Depends(_session)):
    out = finance.summary(s)
    if out.get("has_data"):
        out["reconciliation"] = finance.reconcile(s)
    return out


@app.get("/api/finance/transactions", dependencies=[api])
def fin_transactions(limit: int = 200, category: str | None = None, s=Depends(_session)):
    q = select(Transaction).order_by(Transaction.txn_date.desc()).limit(min(limit, 2000))
    if category:
        q = q.where(Transaction.category == category)
    return [{"id": t.id, "date": t.txn_date.isoformat(), "description": t.description, "amount_cents": t.amount_cents,
             "category": t.category, "status": t.status.value, "is_revenue": t.is_revenue, "is_transfer": t.is_transfer,
             "vendor": t.vendor.name if t.vendor else None} for t in s.execute(q).scalars()]


@app.post("/api/finance/import", dependencies=[api])
async def fin_import(file: UploadFile = File(...), account: str = Form("Primary"), spend_positive: bool = Form(False)):
    raw = await file.read()
    if len(raw) > 10_000_000:
        raise HTTPException(413, "file too large (10 MB max)")
    with sm()() as s:
        r = finance.import_csv(s, FOUNDER, text=raw.decode("utf-8", errors="replace"), filename=file.filename or "upload.csv",
                               account_name=account, amounts_negative_for_spend=not spend_positive)
        s.commit()
    return r


class OpeningIn(BaseModel):
    account: str
    amount: str
    date: date


@app.post("/api/finance/opening-balance", dependencies=[api])
def opening(body: OpeningIn, s=Depends(_session)):
    acct = finance.get_or_create_account(s, body.account)
    acct.opening_balance_cents = to_cents(body.amount)
    acct.opening_balance_date = body.date
    audit.record(s, who="founder", what="finance.opening_balance", input=body.model_dump(mode="json"),
                 target_type="account", target_id=acct.id)
    s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ audits + improvements


@app.get("/api/audits", dependencies=[api])
def list_audits(s=Depends(_session)):
    return [{"id": a.id, "scope": a.scope, "verdict": a.verdict.value if a.verdict else None, "summary": a.summary,
             "findings": a.findings, "auditor": a.auditor, "workflow_run_id": a.workflow_run_id,
             "created_at": a.created_at.isoformat()}
            for a in s.execute(select(Audit).order_by(Audit.created_at.desc()).limit(100)).scalars()]


@app.get("/api/improvements", dependencies=[api])
def list_improvements(s=Depends(_session)):
    return [improvements.to_dict(i) for i in s.execute(select(Improvement).order_by(Improvement.created_at.desc()).limit(200)).scalars()]


@app.post("/api/improvements/{imp_id}/{action}", dependencies=[api])
def improvement_action(imp_id: str, action: str, body: NoteIn, s=Depends(_session)):
    if action == "request":
        a = improvements.request_implementation(s, FOUNDER, imp_id)
        s.commit()
        return {"approval_id": a.id}
    if action == "rollback":
        out = improvements.rollback(s, FOUNDER, imp_id, body.note or "rollback from dashboard")
        s.commit()
        return out
    raise HTTPException(404)


# ------------------------------------------------------------------ memory


class MemoryIn(BaseModel):
    category: str = "FOUNDER"
    subject: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=4000)
    tags: list[str] = Field(default_factory=list)


class CorrectIn(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    reason: str = "founder correction"


@app.get("/api/memory", dependencies=[api])
def list_memory(include_superseded: bool = False, s=Depends(_session)):
    q = select(Memory).order_by(Memory.category, Memory.status, Memory.subject)
    rows = [m for m in s.execute(q).scalars() if include_superseded or m.status != MemoryStatus.SUPERSEDED]
    return {"memories": [memory.to_dict(m) for m in rows], "conflicts": memory.conflicts(s)}


@app.post("/api/memory", dependencies=[api])
def add_memory(body: MemoryIn, s=Depends(_session)):
    m = memory.add(s, FOUNDER, category=MemoryCategory(body.category), subject=body.subject, content=body.content,
                   status=MemoryStatus.EXPLICIT, provenance=Provenance.FOUNDER, source_ref="founder via dashboard",
                   tags=body.tags)
    s.commit()
    return memory.to_dict(m)


@app.post("/api/memory/{memory_id}/correct", dependencies=[api])
def correct_memory(memory_id: str, body: CorrectIn, s=Depends(_session)):
    m = memory.supersede(s, FOUNDER, memory_id, new_content=body.content, reason=body.reason)
    s.commit()
    return memory.to_dict(m)


# ------------------------------------------------------------------ settings


@app.get("/api/settings", dependencies=[api])
def get_settings_view(s=Depends(_session)):
    st = get_settings()
    return {"config": sysconfig.all_config(s), "llm_credentials": st.has_llm_credentials,
            "web_search": st.web_search_enabled, "database": st.database_url.split("://")[0],
            "api_token_required": bool(st.api_token)}


class ConfigIn(BaseModel):
    value: Any
    why: str = "changed from dashboard"


@app.put("/api/settings/{key}", dependencies=[api])
def put_setting(key: str, body: ConfigIn, s=Depends(_session)):
    if key not in sysconfig.DEFAULTS:
        raise HTTPException(404, "unknown setting")
    sysconfig.set_value(s, key, body.value, FOUNDER, body.why)
    s.commit()
    return {"key": key, "value": sysconfig.get(s, key)}


# ------------------------------------------------------------------ dashboard (static)

WEB = Path(__file__).resolve().parent.parent / "web_dist"
if WEB.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        return FileResponse(WEB / "index.html")
