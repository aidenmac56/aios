"""Audits and the scientific improvement loop:
OBSERVE → IDENTIFY → ROOT CAUSE → PROPOSE → DEFINE METRIC → TEST → COMPARE → APPROVE → IMPLEMENT → VERIFY → RECORD.

Observations are measured from the database. Proposals without evidence are rejected. Changes are
applied only after founder approval, with the old value kept for rollback.
"""

from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from aios.config import ROOT, get_settings
from aios.core import approvals, audit, events, sysconfig
from aios.core.actor import FOUNDER, Actor
from aios.core.errors import NotFound, ValidationFailed
from aios.core.permissions import agent_permissions
from aios.core.util import micros_to_usd, utcnow
from aios.db.enums import (
    ApprovalStatus,
    ApprovalType,
    AuditVerdict,
    ImprovementStatus,
    MemoryStatus,
    RunStatus,
    TaskKind,
    TaskStatus,
)
from aios.db.models import (
    Agent,
    AgentConfigVersion,
    AgentRun,
    Approval,
    Audit,
    Claim,
    EventRecord,
    Evaluation,
    Improvement,
    Memory,
    ModelUsage,
    ResearchReport,
    Task,
    Transaction,
    WorkflowRun,
)
from aios.modules import finance, memory
from aios.core.audit import verify_chain


def observations(session: Session) -> dict:
    """Everything the auditors may cite. Pure measurement, no opinions."""
    now = utcnow()
    agents = {}
    for agent_id, runs, failed, cost, dur, retries in session.execute(
        select(AgentRun.agent_id, func.count(), func.sum(case((AgentRun.status == RunStatus.FAILED, 1), else_=0)),
               func.coalesce(func.sum(AgentRun.cost_micros), 0), func.avg(AgentRun.duration_ms),
               func.coalesce(func.sum(AgentRun.retries), 0)).group_by(AgentRun.agent_id)).all():
        agents[agent_id] = {"runs": runs, "failed": int(failed or 0),
                            "failure_rate": round((failed or 0) / runs, 3) if runs else 0,
                            "total_cost_usd": micros_to_usd(cost), "avg_cost_usd": micros_to_usd(cost // runs if runs else 0),
                            "avg_duration_s": round((dur or 0) / 1000, 1), "retries": int(retries)}
    workflows = {}
    for cmd, n, cost, partial, failed in session.execute(
        select(WorkflowRun.command, func.count(), func.coalesce(func.sum(WorkflowRun.total_cost_micros), 0),
               func.sum(case((WorkflowRun.status == RunStatus.PARTIAL, 1), else_=0)),
               func.sum(case((WorkflowRun.status == RunStatus.FAILED, 1), else_=0))).group_by(WorkflowRun.command)).all():
        workflows[cmd] = {"runs": n, "total_cost_usd": micros_to_usd(cost), "avg_cost_usd": micros_to_usd(cost // n if n else 0),
                          "budget_stops": int(partial or 0), "failed": int(failed or 0)}
    models = {}
    for model, n, inp, out, cr, cost, fails in session.execute(
        select(ModelUsage.model, func.count(), func.sum(ModelUsage.input_tokens), func.sum(ModelUsage.output_tokens),
               func.sum(ModelUsage.cache_read_tokens), func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0),
               func.sum(case((ModelUsage.success.is_(False), 1), else_=0))).group_by(ModelUsage.model)).all():
        inp, cr = int(inp or 0), int(cr or 0)
        models[model] = {"calls": n, "failed_calls": int(fails or 0), "avg_input_tokens": (inp // n) if n else 0,
                         "avg_output_tokens": int(out or 0) // n if n else 0, "cost_usd": micros_to_usd(cost),
                         "cache_read_share": round(cr / (inp + cr), 3) if (inp + cr) else 0}
    validation_retries = session.execute(select(func.count(), func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0))
                                         .where(ModelUsage.attempt > 10)).one()
    by_day = [{"day": str(d), "cost_usd": micros_to_usd(c)} for d, c in session.execute(
        select(func.date(ModelUsage.created_at), func.sum(ModelUsage.estimated_cost_micros))
        .where(ModelUsage.created_at >= now - timedelta(days=14)).group_by(func.date(ModelUsage.created_at))).all()]
    recent_failures = [{"at": e.created_at.isoformat(), "actor": e.actor, "error": (e.payload or {}).get("error")}
                       for e in session.execute(select(EventRecord).where(EventRecord.type == "AGENT_FAILED")
                                                .order_by(EventRecord.created_at.desc()).limit(15)).scalars()]
    task_counts = {s.value: n for s, n in session.execute(
        select(Task.status, func.count()).where(Task.kind == TaskKind.PLAN).group_by(Task.status)).all()}
    overdue = session.execute(select(func.count()).select_from(Task).where(
        Task.kind == TaskKind.PLAN, Task.due_date < now.date(),
        Task.status.notin_([TaskStatus.COMPLETED, TaskStatus.CANCELLED]))).scalar()
    mem_counts = {s.value: n for s, n in session.execute(select(Memory.status, func.count()).group_by(Memory.status)).all()}
    old_inferred = session.execute(select(func.count()).select_from(Memory).where(
        Memory.status == MemoryStatus.INFERRED, Memory.created_at < now - timedelta(days=90))).scalar()
    reports = session.execute(select(func.count(), func.sum(case((ResearchReport.stale.is_(True), 1), else_=0)),
                                     func.sum(case((ResearchReport.live_search_used.is_(True), 1), else_=0)))
                              .select_from(ResearchReport)).one()
    claims = session.execute(select(func.count(), func.sum(case((Claim.source_id.is_(None), 1), else_=0))).select_from(Claim)).one()
    txn_total = session.execute(select(func.count()).select_from(Transaction)).scalar() or 0
    uncategorized = session.execute(select(func.count()).select_from(Transaction).where(
        Transaction.category.like("uncategorized%"))).scalar() or 0
    active_versions = dict(session.execute(select(Agent.id, Agent.active_config_version)).all())
    evals = [{"agent": a, "model": m, "config_version": v, "active_version": active_versions.get(a) == v,
              "avg_score": round(float(s), 3), "cases": n}
             for a, m, v, s, n in session.execute(
                 select(Evaluation.agent_id, Evaluation.model, Evaluation.config_version, func.avg(Evaluation.score),
                        func.count()).group_by(Evaluation.agent_id, Evaluation.model, Evaluation.config_version)).all()]
    pending = session.execute(select(Approval).where(Approval.status == ApprovalStatus.PENDING)).scalars().all()
    prompts = {a: {"version": v, "chars": len(p)} for a, v, p in session.execute(
        select(AgentConfigVersion.agent_id, AgentConfigVersion.version, AgentConfigVersion.system_prompt)
        .join(Agent, (Agent.id == AgentConfigVersion.agent_id) & (Agent.active_config_version == AgentConfigVersion.version))).all()}
    gitignore = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    security = {
        "audit_log_chain": verify_chain(session),
        "api_token_configured": bool(get_settings().api_token),
        "llm_credentials_present": get_settings().has_llm_credentials,
        "env_file_gitignored": ".env" in gitignore.split(),
        "agent_permissions": {a: sorted(agent_permissions(a)) for a in prompts},
    }
    return {
        "measured_at": now.isoformat(),
        "agents": agents, "workflows": workflows, "models": models,
        "validation_retries": {"count": validation_retries[0], "cost_usd": micros_to_usd(validation_retries[1])},
        "ai_cost_by_day_usd": by_day, "recent_agent_failures": recent_failures,
        "planning": {"plan_tasks_by_status": task_counts, "overdue_tasks": overdue},
        "memory": {"by_status": mem_counts, "inferred_older_than_90d_unconfirmed": old_inferred,
                   "possible_conflicts": memory.conflicts(session)[:10]},
        "research": {"reports": reports[0], "stale": int(reports[1] or 0), "with_live_search": int(reports[2] or 0),
                     "claims": claims[0], "unsourced_claims": int(claims[1] or 0)},
        "finance": {"transactions": txn_total, "uncategorized": uncategorized,
                    "reconciliation": finance.reconcile(session) if txn_total else None},
        "evaluations": evals,
        "approvals": {"pending": len(pending),
                      "oldest_pending_days": max(((now - a.created_at).days for a in pending), default=0)},
        "prompts": prompts,
        "budgets": {k: sysconfig.get(session, k) for k in ("budget.task_limit_usd", "budget.workflow_limit_usd",
                                                             "budget.daily_limit_usd", "budget.agent_daily_limit_usd")},
        "routing": {"models": sysconfig.get(session, "routing.models"),
                    "overrides": sysconfig.get(session, "routing.agent_tier_overrides")},
        "security": security,
    }


def _norm(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def save_audit(session: Session, *, scope: str, observations: dict, reviews: dict, proposals: list[dict],
               risk: dict | None, workflow_run_id: str | None) -> dict:
    verdict = AuditVerdict(risk["verdict"]) if risk else None
    findings = []
    for k, r in reviews.items():
        findings.extend(f"[{k}] {f}" for f in (r.get("findings") or []))
    a = Audit(scope=scope, target_type="system", verdict=verdict,
              summary=" | ".join(r.get("summary", "") for r in reviews.values())[:4000], findings=findings,
              observations=json.loads(json.dumps(observations, default=str)), auditor="coo+cto+analytics,risk",
              workflow_run_id=workflow_run_id)
    session.add(a)
    session.flush()
    dropped = {_norm(x) for x in (risk or {}).get("unsupported_claims", [])}
    seen: set[str] = set()
    saved = []
    for p in sorted(proposals, key=lambda x: x.get("priority", 3)):
        key = _norm(p["title"])
        if key in seen or not p.get("evidence"):
            continue
        seen.add(key)
        flagged = any(key in d or d in key for d in dropped if d)
        imp = Improvement(title=p["title"], area=p["area"], problem=p["problem"], evidence=p["evidence"],
                          root_cause=p["root_cause"], change=p["change"], expected_impact=p["expected_impact"],
                          cost=p["cost"], risk=p["risk"] + (" [Risk auditor flagged this proposal]" if flagged else ""),
                          test_plan=p["test_plan"], rollback=p["rollback"], metric=p.get("metric"),
                          change_spec=p.get("change_spec"), priority_score=float(6 - p.get("priority", 3)) - (2 if flagged else 0),
                          proposed_by=f"agent:{p.get('_from', 'unknown')}", audit_id=a.id)
        session.add(imp)
        session.flush()
        events.emit(session, events.IMPROVEMENT_PROPOSED, imp.proposed_by, {"improvement_id": imp.id}, workflow_run_id)
        saved.append(to_dict(imp))
    events.emit(session, events.AUDIT_COMPLETED, "system", {"audit_id": a.id, "verdict": verdict.value if verdict else None},
                workflow_run_id)
    audit.record(session, who="system", what="audit.saved", output={"audit_id": a.id, "improvements": len(saved)},
                 target_type="audit", target_id=a.id)
    return {"audit_id": a.id, "improvements": saved}


def measured_candidates(session: Session) -> list[dict]:
    """Deterministic proposals straight from the numbers (no model call)."""
    out = []
    obs = observations(session)
    margin = float(sysconfig.get(session, "routing.equivalence_margin"))
    min_cases = int(sysconfig.get(session, "routing.min_eval_cases"))
    by_agent: dict[str, list[dict]] = {}
    for e in obs["evaluations"]:
        if e["cases"] >= min_cases and e["active_version"]:
            by_agent.setdefault(e["agent"], []).append(e)
    models = sysconfig.get(session, "routing.models")
    tier_of = {m: t for t, m in models.items()}
    from aios.llm.pricing import price_for

    for agent_id, rows in by_agent.items():
        rows.sort(key=lambda r: (price_for(r["model"]).output if price_for(r["model"]) else 99))
        best = max(rows, key=lambda r: r["avg_score"])
        cheapest_ok = next((r for r in rows if r["avg_score"] >= best["avg_score"] - margin), None)
        if cheapest_ok and cheapest_ok["model"] != best["model"] and cheapest_ok["model"] in tier_of:
            out.append(_save_candidate(session, title=f"Route {agent_id} to {cheapest_ok['model']}", area="model_choice",
                                       problem=f"{agent_id} uses a pricier model than its benchmark requires.",
                                       evidence=[f"{r['model']}: avg score {r['avg_score']} over {r['cases']} cases" for r in rows],
                                       change=f"Set routing.agent_tier_overrides[{agent_id}] = {tier_of[cheapest_ok['model']]}",
                                       spec={"type": "routing_override", "key": "routing.agent_tier_overrides",
                                             "value": json.dumps({agent_id: tier_of[cheapest_ok["model"]]})}))
    for agent_id, a in obs["agents"].items():
        if a["runs"] >= 5 and a["failure_rate"] > 0.2:
            out.append(_save_candidate(session, title=f"Reduce {agent_id} failure rate", area="agent_quality",
                                       problem=f"{agent_id} fails {a['failure_rate']:.0%} of runs.",
                                       evidence=[f"{a['failed']} of {a['runs']} runs failed"], change="Inspect recent failures; "
                                       "tighten the output schema descriptions or raise max_tokens.", spec=None))
    return out


def _save_candidate(session: Session, *, title, area, problem, evidence, change, spec) -> dict:
    existing = session.execute(select(Improvement).where(Improvement.title == title,
                                                         Improvement.status == ImprovementStatus.PROPOSED)).scalar_one_or_none()
    if existing:
        return to_dict(existing)
    imp = Improvement(title=title, area=area, problem=problem, evidence=evidence, root_cause="Measured from data.",
                      change=change, expected_impact="Lower cost or fewer failures at equal quality.",
                      cost="None to apply.", risk="Quality could drop on cases outside the benchmark.",
                      test_plan="Run the agent's benchmark on both configurations and compare scores and cost.",
                      rollback="Restore the previous configuration value (kept on the improvement).",
                      metric="benchmark score and cost per run", change_spec=spec, priority_score=3.0,
                      proposed_by="system:measured")
    session.add(imp)
    session.flush()
    events.emit(session, events.IMPROVEMENT_PROPOSED, "system", {"improvement_id": imp.id})
    return to_dict(imp)


def request_implementation(session: Session, actor: Actor, improvement_id: str) -> Approval:
    imp = session.get(Improvement, improvement_id)
    if imp is None:
        raise NotFound("improvement not found")
    if imp.status not in (ImprovementStatus.PROPOSED, ImprovementStatus.TESTED):
        raise ValidationFailed(f"improvement is {imp.status.value}")
    return approvals.request(session, action=f"Implement improvement: {imp.title}", action_type=ApprovalType.SYSTEM_CHANGE,
                             requested_by=str(actor), reason=imp.problem, expected_effect=imp.expected_impact,
                             risks=[imp.risk], handler="improvement.implement", payload={"improvement_id": imp.id})


MAX_ADDENDUM = 1500


def _addendum_text(spec: dict) -> str:
    raw = spec.get("value") or ""
    try:
        parsed = json.loads(raw)
        text = parsed if isinstance(parsed, str) else raw
    except (json.JSONDecodeError, TypeError):
        text = raw
    text = text.strip()
    if not text:
        raise ValidationFailed("prompt_addendum has no text.")
    if len(text) > MAX_ADDENDUM:
        raise ValidationFailed(f"prompt_addendum is {len(text)} characters; the limit is {MAX_ADDENDUM}.")
    return text


def ensure_candidate_version(session: Session, imp: Improvement) -> int:
    """Create (once) the inactive agent config version a prompt_addendum improvement describes."""
    from aios.agents import registry
    from aios.agents.specs import SPECS

    spec = imp.change_spec or {}
    agent_id = spec.get("key")
    if agent_id not in SPECS:
        raise ValidationFailed(f"prompt_addendum targets unknown agent '{agent_id}'.")
    existing = (imp.test_results or {}).get("candidate_version")
    if existing:
        return int(existing)
    current = registry.active_config(session, agent_id)
    text = _addendum_text(spec)
    v = registry.propose_version(
        session, agent_id,
        system_prompt=f"{current.system_prompt}\n\nADDITIONAL GUIDANCE (from improvement {imp.id[:8]}):\n{text}",
        config=None, reason=f"improvement {imp.id}: {imp.title}", expected_improvement=imp.expected_impact,
        created_by=imp.proposed_by)
    imp.test_results = {**(imp.test_results or {}), "candidate_version": v.version, "baseline_version": current.version}
    session.flush()
    return v.version


def on_approved(session: Session, approval: Approval, actor: Actor) -> dict:
    imp = session.get(Improvement, approval.payload["improvement_id"])
    imp.approval_id = approval.id
    spec = imp.change_spec
    if not spec:
        imp.status = ImprovementStatus.APPROVED
        return {"improvement_id": imp.id, "improvement_status": imp.status.value, "note": "Approved; this change is applied by a human."}
    if spec.get("type") == "prompt_addendum":
        from aios.agents import registry
        from aios.db.models import Agent as AgentRow

        agent_id = spec["key"]
        old_version = session.get(AgentRow, agent_id).active_config_version
        new_version = ensure_candidate_version(session, imp)
        registry.activate_version(session, agent_id, new_version, str(actor), approval.id,
                                  why=f"approved improvement {imp.id}: {imp.title}")
        applied = {"type": "prompt", "agent": agent_id, "old_version": old_version, "new_version": new_version,
                   "at": utcnow().isoformat()}
        imp.status = ImprovementStatus.IMPLEMENTED
        imp.test_results = {**(imp.test_results or {}), "applied": applied}
        return {"improvement_id": imp.id, "improvement_status": imp.status.value, "applied": applied}
    try:
        value = json.loads(spec["value"])
    except (json.JSONDecodeError, TypeError) as e:
        raise ValidationFailed(f"change_spec value is not valid JSON: {e}")
    key = spec["key"]
    if key not in sysconfig.DEFAULTS:
        raise ValidationFailed(f"Unknown configuration key {key}")
    old = sysconfig.get(session, key)
    new = {**old, **value} if isinstance(old, dict) and isinstance(value, dict) else value
    sysconfig.set_value(session, key, new, FOUNDER, why=f"approved improvement {imp.id}: {imp.title}")
    imp.status = ImprovementStatus.IMPLEMENTED
    imp.test_results = {**(imp.test_results or {}), "applied": {"key": key, "old": old, "new": new, "at": utcnow().isoformat()}}
    return {"improvement_id": imp.id, "improvement_status": imp.status.value, "applied": {"key": key, "old": old, "new": new}}


def on_rejected(session: Session, approval: Approval, actor: Actor) -> dict:
    imp = session.get(Improvement, approval.payload["improvement_id"])
    imp.status = ImprovementStatus.REJECTED
    return {"improvement_id": imp.id, "improvement_status": imp.status.value}


def rollback(session: Session, actor: Actor, improvement_id: str, why: str) -> dict:
    if not actor.is_founder:
        raise ValidationFailed("Only the founder can roll back an implemented change.")
    imp = session.get(Improvement, improvement_id)
    applied = (imp.test_results or {}).get("applied") if imp else None
    if not applied:
        raise ValidationFailed("Nothing applied to roll back.")
    if imp.status == ImprovementStatus.ROLLED_BACK:
        raise ValidationFailed("Already rolled back.")
    if applied.get("type") == "prompt":
        from aios.agents import registry

        registry.activate_version(session, applied["agent"], applied["old_version"], str(actor), None,
                                  why=f"rollback {imp.id}: {why}")
        imp.status = ImprovementStatus.ROLLED_BACK
        return {"improvement_id": imp.id, "restored": {"agent": applied["agent"], "version": applied["old_version"]}}
    sysconfig.set_value(session, applied["key"], applied["old"], actor, why=f"rollback {imp.id}: {why}")
    imp.status = ImprovementStatus.ROLLED_BACK
    return {"improvement_id": imp.id, "restored": {"key": applied["key"], "value": applied["old"]}}


def test_plan_for(session: Session, imp: Improvement) -> dict:
    """What an automated A/B test of this improvement compares. Raises if it cannot be tested automatically."""
    from aios.agents.specs import SPECS
    from aios.llm import router
    from aios.modules.evaluations import BENCHMARKS

    spec = imp.change_spec or {}
    kind = spec.get("type")
    if kind == "prompt_addendum":
        agent_id = spec.get("key")
        if agent_id not in BENCHMARKS:
            raise ValidationFailed(f"No benchmark for '{agent_id}' yet, so this change can only be reviewed by hand.")
        from aios.agents import registry

        cfg = registry.active_config(session, agent_id)
        model = router.choose(session, agent_id=agent_id, default_tier=cfg.tier_override or SPECS[agent_id].default_tier).model
        candidate = ensure_candidate_version(session, imp)
        return {"agent": agent_id, "baseline": {"model": model, "config_version": cfg.version},
                "candidate": {"model": model, "config_version": candidate}}
    if kind == "routing_override":
        try:
            value = json.loads(spec.get("value") or "")
        except json.JSONDecodeError as e:
            raise ValidationFailed(f"change_spec value is not valid JSON: {e}")
        if not isinstance(value, dict) or len(value) != 1:
            raise ValidationFailed("A testable routing_override changes exactly one agent, e.g. {\"cfo\": \"FAST\"}.")
        agent_id, tier = next(iter(value.items()))
        if agent_id not in BENCHMARKS:
            raise ValidationFailed(f"No benchmark for '{agent_id}' yet, so this change can only be reviewed by hand.")
        models = sysconfig.get(session, "routing.models")
        if tier not in models:
            raise ValidationFailed(f"Unknown tier '{tier}'.")
        from aios.agents import registry

        cfg = registry.active_config(session, agent_id)
        current = router.choose(session, agent_id=agent_id, default_tier=cfg.tier_override or SPECS[agent_id].default_tier)
        return {"agent": agent_id, "baseline": {"model": current.model, "config_version": cfg.version},
                "candidate": {"model": models[tier], "config_version": cfg.version}}
    raise ValidationFailed("Only routing and prompt changes have an automated benchmark test; review the test plan by hand.")


def record_test(session: Session, imp: Improvement, plan: dict, baseline: dict, candidate: dict,
                experiment_id: str) -> dict:
    """COMPARE: equal-or-better quality (within the routing margin) and the cost difference decide the verdict."""
    from aios.db.models import Experiment

    margin = float(sysconfig.get(session, "routing.equivalence_margin"))
    delta = round(candidate["avg_score"] - baseline["avg_score"], 4)
    cost_delta = round(candidate["total_cost_usd"] - baseline["total_cost_usd"], 6)
    if delta > margin:
        verdict = "BETTER"
    elif delta >= -margin:
        verdict = "EQUIVALENT"
    else:
        verdict = "WORSE"
    conclusion = (f"Candidate scored {candidate['avg_score']:.3f} vs baseline {baseline['avg_score']:.3f} "
                  f"({delta:+.3f}; margin ±{margin}) at {cost_delta:+.4f} USD for the benchmark. Verdict: {verdict}.")
    exp = session.get(Experiment, experiment_id)
    exp.results = {"baseline": baseline, "candidate": candidate, "score_delta": delta, "cost_delta_usd": cost_delta,
                   "verdict": verdict}
    exp.status = "COMPLETED"
    exp.conclusion = conclusion
    imp.status = ImprovementStatus.TESTED
    imp.test_results = {**(imp.test_results or {}), "experiment_id": exp.id, "verdict": verdict,
                        "score_delta": delta, "cost_delta_usd": cost_delta,
                        "baseline": {k: baseline[k] for k in ("model", "config_version", "avg_score", "total_cost_usd")},
                        "candidate": {k: candidate[k] for k in ("model", "config_version", "avg_score", "total_cost_usd")},
                        "tested_at": utcnow().isoformat()}
    audit.record(session, who="system", what="improvement.tested", why=imp.title, output=imp.test_results,
                 target_type="improvement", target_id=imp.id)
    return {"improvement_id": imp.id, "experiment_id": exp.id, "verdict": verdict, "conclusion": conclusion,
            "baseline": baseline, "candidate": candidate}


def verify(session: Session, actor: Actor, improvement_id: str, *, result: str, success: bool) -> dict:
    imp = session.get(Improvement, improvement_id)
    if imp is None or imp.status != ImprovementStatus.IMPLEMENTED:
        raise ValidationFailed("Only implemented improvements can be verified.")
    imp.status = ImprovementStatus.VERIFIED if success else imp.status
    imp.test_results = {**(imp.test_results or {}), "verification": {"result": result, "success": success,
                                                                     "at": utcnow().isoformat(), "by": str(actor)}}
    audit.record(session, who=str(actor), what="improvement.verify", why=result, target_type="improvement", target_id=imp.id)
    return to_dict(imp)


def to_dict(i: Improvement) -> dict:
    return {"id": i.id, "title": i.title, "area": i.area, "problem": i.problem, "evidence": i.evidence,
            "root_cause": i.root_cause, "change": i.change, "expected_impact": i.expected_impact, "cost": i.cost,
            "risk": i.risk, "test_plan": i.test_plan, "rollback": i.rollback, "metric": i.metric,
            "change_spec": i.change_spec, "status": i.status.value, "test_results": i.test_results,
            "priority_score": i.priority_score, "proposed_by": i.proposed_by, "audit_id": i.audit_id,
            "created_at": i.created_at.isoformat()}
