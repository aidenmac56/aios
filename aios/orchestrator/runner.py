"""Runs one agent on one objective: routing, prompt assembly, validated output, task + run records."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from aios.agents import registry
from aios.agents.schemas import FinanceFinding, ResearchFinding
from aios.config import get_settings
from aios.core import audit, events, sysconfig
from aios.core.actor import agent as agent_actor
from aios.core.budget import BudgetGuard
from aios.core.errors import AIOSError, BudgetExceeded, MissingCredentials
from aios.core.util import utcnow
from aios.db.enums import RunStatus, TaskKind, TaskStatus
from aios.db.models import AgentRun, Task
from aios.llm import calls, router
from aios.llm.calls import CallContext, untrusted
from aios.llm.provider import ProviderRegistry
from aios.modules import finance, research


@dataclass
class RunCtx:
    sm: sessionmaker
    providers: ProviderRegistry
    guard: BudgetGuard
    run_id: str
    command: str
    request: str
    importance: str = "normal"
    progress: Callable[[str], None] = lambda msg: None
    research_report_ids: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    key: str
    agent_id: str
    ok: bool
    output: dict | None
    error: str | None = None
    run_id: str | None = None
    cost_micros: int = 0


def _prompt(*, objective: str, request: str, context_text: str, deps_text: str, extra: str) -> str:
    parts = [f"OBJECTIVE FOR YOU:\n{objective}", f"ORIGINAL REQUEST FROM THE FOUNDER:\n{untrusted('founder_request', request)}"]
    if context_text:
        parts.append("COMPANY CONTEXT (internal records):\n" + context_text)
    if deps_text:
        parts.append(deps_text)
    if extra:
        parts.append(extra)
    parts.append("Answer by calling the submit tool. Be specific and evidence-based. Empty lists are better than invented content.")
    return "\n\n".join(parts)


async def run_agent(rc: RunCtx, *, agent_id: str, key: str, objective: str, context_text: str = "",
                    deps: dict[str, dict] | None = None, complexity: str | None = None,
                    schema: type[BaseModel] | None = None, floor_tier: str | None = None, extra: str = "",
                    creator: str = "agent:ceo") -> AgentResult:
    from aios.orchestrator.context import dependency_block

    with rc.sm() as s:
        cfg = registry.active_config(s, agent_id)
        route = router.choose(s, agent_id=agent_id, default_tier=cfg.tier_override or cfg.spec.default_tier,
                              complexity=complexity, importance=rc.importance,
                              budget_remaining_ratio=rc.guard.remaining_ratio, floor_tier=floor_tier)
        out_schema = schema or cfg.spec.output_schema
        task = Task(kind=TaskKind.WORK, title=f"{agent_id}: {objective[:200]}", description=objective,
                    workflow_run_id=rc.run_id, responsible_agent=agent_id, creator=creator, status=TaskStatus.RUNNING,
                    started_at=utcnow(), completion_criteria=f"Output validates against {out_schema.__name__}")
        s.add(task)
        s.flush()
        run = AgentRun(workflow_run_id=rc.run_id, task_id=task.id, agent_id=agent_id, config_version=cfg.version,
                       status=RunStatus.RUNNING, objective=objective, started_at=utcnow(), model=route.model,
                       tier=route.tier, routing_reason=route.reason)
        s.add(run)
        s.commit()
        run_id, task_id = run.id, task.id
        output_retries = int(sysconfig.get(s, "orchestrator.output_retries"))
        api_retries = int(sysconfig.get(s, "orchestrator.api_retries"))
        max_searches = int(sysconfig.get(s, "research.max_searches"))

    rc.progress(f"{agent_id} started ({route.model}): {objective[:90]}")
    ctx = CallContext(sm=rc.sm, providers=rc.providers, budget=rc.guard, workflow_run_id=rc.run_id,
                      workflow=rc.command, agent_run_id=run_id, agent_id=agent_id, task_key=key, tier=route.tier,
                      output_retries=output_retries, api_retries=api_retries)
    started = time.monotonic()
    deps_text = dependency_block(deps or {})
    try:
        if agent_id == "research" and out_schema is ResearchFinding:
            output = await _research(rc, ctx, cfg, route, objective=objective, context_text=context_text,
                                     deps_text=deps_text, max_searches=max_searches)
        else:
            prompt = _prompt(objective=objective, request=rc.request, context_text=context_text, deps_text=deps_text,
                             extra=extra)
            result = await calls.structured(ctx, model=route.model, system=cfg.system_prompt, prompt=prompt,
                                            schema=out_schema, purpose="analysis", max_tokens=cfg.max_tokens)
            output = result.model_dump()
            if isinstance(result, FinanceFinding) and result.finance_inputs is not None:
                output["computed_unit_economics"] = finance.unit_economics(result.finance_inputs.model_dump())
    except BudgetExceeded as e:
        _finish(rc, run_id, task_id, RunStatus.BLOCKED, TaskStatus.BLOCKED, None, e.message, ctx, started)
        rc.progress(f"{agent_id} stopped: {e.message}")
        raise
    except MissingCredentials:
        _finish(rc, run_id, task_id, RunStatus.FAILED, TaskStatus.FAILED, None, "missing credentials", ctx, started)
        raise
    except AIOSError as e:
        _finish(rc, run_id, task_id, RunStatus.FAILED, TaskStatus.FAILED, None, e.message, ctx, started)
        with rc.sm() as s:
            events.emit(s, events.AGENT_FAILED, f"agent:{agent_id}", {"agent_run_id": run_id, "error": e.message[:500]},
                        rc.run_id)
            s.commit()
        rc.progress(f"{agent_id} failed: {e.message[:160]}")
        return AgentResult(key, agent_id, False, None, e.message, run_id, ctx.spent_micros)
    output["_agent"] = agent_id
    output["_run_id"] = run_id
    _finish(rc, run_id, task_id, RunStatus.COMPLETED, TaskStatus.COMPLETED, output, None, ctx, started)
    rc.progress(f"{agent_id} done (${ctx.spent_micros / 1e6:.3f})")
    return AgentResult(key, agent_id, True, output, None, run_id, ctx.spent_micros)


def _finish(rc: RunCtx, run_id: str, task_id: str, run_status: RunStatus, task_status: TaskStatus,
            output: dict | None, error: str | None, ctx: CallContext, started: float) -> None:
    with rc.sm() as s:
        run = s.get(AgentRun, run_id)
        run.status, run.output, run.error = run_status, output, error
        run.finished_at = utcnow()
        run.duration_ms = int((time.monotonic() - started) * 1000)
        run.cost_micros = ctx.spent_micros
        run.retries = max(0, len(ctx.calls) - (2 if run.agent_id == "research" else 1))
        task = s.get(Task, task_id)
        task.status = task_status
        task.actual_cost_micros = ctx.spent_micros
        task.error = error
        task.retry_count = run.retries
        if task_status == TaskStatus.COMPLETED:
            task.completed_at = utcnow()
            task.criteria_met = True
            task.result = {"agent_run_id": run_id}
        audit.record(s, who=f"agent:{run.agent_id}", what="agent.run", why=run.objective[:300],
                     output={"status": run_status.value, "summary": (output or {}).get("summary") or (output or {}).get("conclusion")},
                     tools_used=sorted({c["purpose"] for c in ctx.calls}), cost_micros=ctx.spent_micros,
                     result=run_status.value, error=error, target_type="agent_run", target_id=run_id)
        s.commit()


async def _research(rc: RunCtx, ctx: CallContext, cfg, route, *, objective: str, context_text: str, deps_text: str,
                    max_searches: int) -> dict[str, Any]:
    with rc.sm() as s:
        reuse = research.find_reusable(s, objective)
        if reuse is not None:
            rc.progress(f"research: reusing report {reuse.id} (fresh, same question)")
            rc.research_report_ids.append(reuse.id)
            d = research.to_dict(reuse)
            return {"reused_report_id": reuse.id, "question": reuse.question, "answer": reuse.answer,
                    "confidence": reuse.confidence.value, "claims": d["claims"], "summary": reuse.answer[:600],
                    "stance": "NEUTRAL", "live_search_used": reuse.live_search_used}
    settings = get_settings()
    search_text, results, citations, live, search_error = "", [], [], False, None
    if settings.web_search_enabled:
        sr = await calls.web_research(
            ctx, model=route.model, system=cfg.system_prompt,
            prompt=(f"Research this for the founder. Decision context and objective:\n{objective}\n\n"
                    f"Company context (internal):\n{context_text[:4000]}\n\n{deps_text[:4000]}\n\n"
                    "Search for primary and recent sources. Write findings with citations. Note where sources disagree."),
            max_searches=max_searches)
        search_text, results, citations, live, search_error = sr.text, sr.results, sr.citations, sr.live, sr.error
    else:
        search_error = "web search disabled by configuration"
    allowed: dict[str, dict] = {}
    for r in results:
        allowed[r["url"]] = {"title": r.get("title"), "page_age": r.get("page_age")}
    for c in citations:
        allowed.setdefault(c["url"], {"title": c.get("title")})
    with rc.sm() as s:
        fast = router.choose(s, agent_id="research", default_tier="FAST", complexity=None, importance="normal",
                             budget_remaining_ratio=rc.guard.remaining_ratio)
    listing = "\n".join(f"- {u} | {m.get('title') or ''} | {m.get('page_age') or 'date unknown'}" for u, m in allowed.items())
    structure_prompt = (
        f"OBJECTIVE:\n{objective}\n\n"
        f"SEARCH FINDINGS (written by the researcher from live sources):\n{untrusted('web_research', search_text or '(none)')}\n\n"
        f"URLS ACTUALLY RETRIEVED (the ONLY URLs you may cite):\n{untrusted('search_results', listing or '(none)')}\n\n"
        f"{'NO LIVE SEARCH WAS AVAILABLE: ' + search_error + '. Say so in the answer and set confidence LOW.' if not live else ''}\n"
        "Structure this into the research schema. Every factual claim must cite one of the retrieved URLs exactly; "
        "anything else is interpretation (is_fact=false, source_url=null).")
    child = ctx.child(tier=fast.tier)
    try:
        finding = await calls.structured(child, model=fast.model, system=cfg.system_prompt, prompt=structure_prompt,
                                         schema=ResearchFinding, purpose="structure", max_tokens=cfg.max_tokens)
    finally:
        ctx.spent_micros += child.spent_micros
        ctx.calls.extend(child.calls)
    with rc.sm() as s:
        report, problems = research.save(s, agent_actor("research"), finding, allowed_urls=allowed, live=live,
                                         workflow_run_id=rc.run_id)
        s.commit()
        rc.research_report_ids.append(report.id)
        out = finding.model_dump()
        out.update({"report_id": report.id, "live_search_used": live, "source_problems": problems,
                    "search_error": search_error, "confidence": report.confidence.value})
    return out


def compact(output: dict | None, limit: int = 2500) -> str:
    return json.dumps(output, default=str)[:limit] if output else "(failed)"
