"""Read-only views: company status, costs, agent organization. No model calls."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aios.agents.specs import SPECS
from aios.core import sysconfig
from aios.core.budget import spent_today
from aios.core.permissions import agent_permissions
from aios.core.util import micros_to_usd, utcnow
from aios.db.enums import ApprovalStatus, ImprovementStatus, RunStatus
from aios.db.models import (
    Agent,
    AgentRun,
    Approval,
    Audit,
    Company,
    Decision,
    EventRecord,
    Improvement,
    ModelUsage,
    ResearchReport,
    ToolCall,
    WorkflowRun,
)
from aios.modules import finance, memory, planning


def costs(session: Session, days: int = 30) -> dict:
    since = utcnow() - timedelta(days=days)

    def grouped(col):
        rows = session.execute(select(col, func.count(), func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0),
                                      func.sum(ModelUsage.input_tokens), func.sum(ModelUsage.output_tokens))
                               .where(ModelUsage.created_at >= since).group_by(col)
                               .order_by(func.sum(ModelUsage.estimated_cost_micros).desc())).all()
        return [{"key": k or "(none)", "calls": n, "cost_usd": micros_to_usd(c), "input_tokens": int(i or 0),
                 "output_tokens": int(o or 0)} for k, n, c, i, o in rows]

    total = session.execute(select(func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0), func.count())
                            .where(ModelUsage.created_at >= since)).one()
    failed = session.execute(select(func.count()).select_from(ModelUsage).where(
        ModelUsage.created_at >= since, ModelUsage.success.is_(False))).scalar()
    retry_cost = session.execute(select(func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0)).where(
        ModelUsage.created_at >= since, ModelUsage.attempt > 1)).scalar()
    searches = session.execute(select(func.coalesce(func.sum(ToolCall.cost_micros), 0), func.count())
                               .where(ToolCall.created_at >= since, ToolCall.tool_name == "web_search")).one()
    by_day = [{"day": str(d), "cost_usd": micros_to_usd(c)} for d, c in session.execute(
        select(func.date(ModelUsage.created_at), func.sum(ModelUsage.estimated_cost_micros))
        .where(ModelUsage.created_at >= since).group_by(func.date(ModelUsage.created_at))
        .order_by(func.date(ModelUsage.created_at))).all()]
    runs = session.execute(select(WorkflowRun.command, func.count(), func.avg(WorkflowRun.total_cost_micros))
                           .where(WorkflowRun.created_at >= since).group_by(WorkflowRun.command)).all()
    return {
        "window_days": days,
        "total_usd": micros_to_usd(total[0]), "calls": total[1], "failed_calls": failed,
        "retry_cost_usd": micros_to_usd(retry_cost),
        "web_search": {"cost_usd_included": micros_to_usd(searches[0]), "calls": searches[1]},
        "today_usd": micros_to_usd(spent_today(session)),
        "daily_limit_usd": sysconfig.get(session, "budget.daily_limit_usd"),
        "by_agent": grouped(ModelUsage.agent_id), "by_model": grouped(ModelUsage.model),
        "by_workflow": grouped(ModelUsage.workflow), "by_purpose": grouped(ModelUsage.purpose),
        "by_day": by_day,
        "per_run_avg_usd": [{"command": c, "runs": n, "avg_usd": micros_to_usd(int(a or 0))} for c, n, a in runs],
        "basis": "Estimated from list prices (pricing table version stored per call). Web search cost is included in totals.",
    }


def agents_view(session: Session) -> list[dict]:
    out = []
    for spec in SPECS.values():
        row = session.get(Agent, spec.id)
        stats = session.execute(select(func.count(), func.coalesce(func.sum(AgentRun.cost_micros), 0),
                                       func.avg(AgentRun.duration_ms))
                                .where(AgentRun.agent_id == spec.id)).one()
        failed = session.execute(select(func.count()).select_from(AgentRun).where(
            AgentRun.agent_id == spec.id, AgentRun.status == RunStatus.FAILED)).scalar()
        last = session.execute(select(AgentRun).where(AgentRun.agent_id == spec.id)
                               .order_by(AgentRun.created_at.desc()).limit(1)).scalar_one_or_none()
        out.append({
            "id": spec.id, "name": spec.name, "title": spec.title, "purpose": spec.purpose,
            "responsibilities": spec.responsibilities, "authority": spec.authority,
            "permissions": sorted(agent_permissions(spec.id)), "tools": spec.tools, "inputs": spec.inputs,
            "outputs": spec.outputs, "escalation_rules": spec.escalation_rules, "default_tier": spec.default_tier,
            "performance_measures": spec.performance_measures, "enabled": row.enabled if row else True,
            "config_version": row.active_config_version if row else 1,
            "runs": stats[0], "failed": failed, "total_cost_usd": micros_to_usd(stats[1]),
            "avg_duration_s": round((stats[2] or 0) / 1000, 1),
            "last_run": ({"at": last.created_at.isoformat(), "status": last.status.value, "model": last.model}
                         if last else None),
        })
    return out


def company_status(session: Session) -> dict:
    fin = finance.summary(session)
    plan = planning.state(session)
    companies = session.execute(select(Company)).scalars().all()
    recent = session.execute(select(EventRecord).order_by(EventRecord.created_at.desc()).limit(25)).scalars().all()
    audits = session.execute(select(Audit).order_by(Audit.created_at.desc()).limit(5)).scalars().all()
    opps = session.execute(select(Decision).where(Decision.decision_type == "BUILD").order_by(Decision.created_at.desc())
                           .limit(5)).scalars().all()
    imps = session.execute(select(Improvement).where(Improvement.status.in_([ImprovementStatus.PROPOSED, ImprovementStatus.TESTED]))
                           .order_by(Improvement.priority_score.desc()).limit(5)).scalars().all()
    pending = session.execute(select(func.count()).select_from(Approval).where(Approval.status == ApprovalStatus.PENDING)).scalar()
    workflows = session.execute(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(10)).scalars().all()
    reports = session.execute(select(func.count()).select_from(ResearchReport)).scalar()
    ai_month = costs(session, 30)
    principles = planning.principles(session)
    mem = memory.retrieve(session, "goal priority principle", limit=8)
    return {
        "companies": [{"id": c.id, "name": c.name, "vision": c.vision, "mission": c.mission, "strategy": c.strategy,
                       "business_model": c.business_model, "products": c.products, "customers": c.customers}
                      for c in companies],
        "priorities": plan["top_tasks"][:5],
        "founder_focus": [memory.to_dict(m) for m in mem],
        "principles": principles,
        "projects": plan["projects"],
        "finance": {k: fin.get(k) for k in ("has_data", "note", "totals", "burn", "cash", "runway", "recurring", "ai", "period")},
        "ai_costs": {"last_30d_usd": ai_month["total_usd"], "today_usd": ai_month["today_usd"],
                     "daily_limit_usd": ai_month["daily_limit_usd"]},
        "risks": [{"audit_id": a.id, "verdict": a.verdict.value if a.verdict else None, "summary": a.summary,
                   "at": a.created_at.isoformat()} for a in audits],
        "opportunities": [{"decision_id": d.id, "question": d.question, "recommendation": d.recommendation,
                           "status": d.status.value} for d in opps],
        "decisions_needed": {"pending_approvals": pending, "items": plan["pending_approvals"][:10]},
        "contradictions": plan["contradictions"],
        "improvements": [{"id": i.id, "title": i.title, "status": i.status.value} for i in imps],
        "recent_workflows": [{"id": w.id, "command": w.command, "status": w.status.value, "request": w.request[:140],
                              "cost_usd": micros_to_usd(w.total_cost_micros), "at": w.created_at.isoformat()}
                             for w in workflows],
        "recent_activity": [{"type": e.type, "actor": e.actor, "at": e.created_at.isoformat(), "payload": e.payload}
                            for e in recent],
        "research_reports": reports,
    }
