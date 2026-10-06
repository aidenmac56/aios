"""Internal benchmarks. Run manually (`aios eval`); results feed model routing.

Each case gives an agent a fixed input; a deterministic scorer grades the output. Scores are 0..1.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker

from aios.agents import registry
from aios.agents.schemas import ExecutiveBrief, FinanceFinding, PlanOutput, ResearchFinding, TechFinding
from aios.core.budget import BudgetGuard, Limits
from aios.core.errors import AIOSError, InvalidPlan
from aios.db.models import Evaluation
from aios.llm import calls
from aios.llm.calls import CallContext
from aios.llm.provider import ProviderRegistry
from aios.modules import planning


@dataclass
class Case:
    id: str
    prompt: str
    expect: dict


@dataclass
class Benchmark:
    agent_id: str
    name: str
    schema: type[BaseModel]
    cases: list[Case]
    scorer: Callable[[BaseModel, Case], dict[str, float]]


def _avg(scores: dict[str, float]) -> float:
    return round(sum(scores.values()) / len(scores), 4) if scores else 0.0


def score_cfo(out: FinanceFinding, case: Case) -> dict[str, float]:
    s = {"has_inputs": 1.0 if (out.finance_inputs is not None) == case.expect.get("needs_inputs", True) else 0.0,
         "basis_given": 1.0 if (out.finance_inputs and len(out.finance_inputs.basis) >= 3) or not case.expect.get("needs_inputs", True) else 0.0,
         "costs_are_estimates": 1.0 if all(c.basis for c in out.costs) else 0.0,
         "escalation": 1.0 if out.escalate == case.expect.get("escalate", out.escalate) else 0.0}
    if "max_churn_pct" in case.expect and out.finance_inputs:
        s["plausible_churn"] = 1.0 if out.finance_inputs.monthly_churn_pct <= case.expect["max_churn_pct"] else 0.0
    return s


def score_cto(out: TechFinding, case: Case) -> dict[str, float]:
    dims = {d.dimension for d in out.tech.dimensions}
    return {"all_dimensions": len(dims) / 10, "notes": 1.0 if all(len(d.note) > 10 for d in out.tech.dimensions) else 0.0,
            "build_vs_buy": 1.0 if len(out.tech.build_vs_buy) > 20 else 0.0,
            "security_considered": 1.0 if out.tech.security_concerns else 0.5}


def score_strategy(out: PlanOutput, case: Case) -> dict[str, float]:
    try:
        planning.validate_plan(out)
        valid = 1.0
    except InvalidPlan:
        valid = 0.0
    tasks = out.tasks
    return {"valid_structure": valid,
            "criteria_observable": sum(1 for t in tasks if len(t.completion_criteria) > 15) / len(tasks),
            "owners_set": sum(1 for t in tasks if t.responsible) / len(tasks),
            "within_budget": 1.0 if out.project.expected_cost_usd <= case.expect.get("max_cost_usd", 1e12) else 0.0,
            "has_dependencies": 1.0 if any(t.depends_on for t in tasks) else 0.0}


def score_ceo(out: ExecutiveBrief, case: Case) -> dict[str, float]:
    s = {"opposing_arguments": 1.0 if out.opposing_arguments else 0.0, "next_steps": 1.0 if out.next_steps else 0.0,
         "evidence": min(1.0, len(out.evidence) / 3), "uncertainty": 1.0 if len(out.uncertainty) > 20 else 0.0}
    if case.expect.get("must_require_approval"):
        s["approval_when_blocked"] = 1.0 if out.requires_approval else 0.0
    if case.expect.get("verdict_not"):
        s["respects_risk"] = 0.0 if out.verdict in case.expect["verdict_not"] else 1.0
    return s


def score_research_offline(out: ResearchFinding, case: Case) -> dict[str, float]:
    facts = [c for c in out.claims if c.is_fact]
    return {"facts_sourced": (sum(1 for c in facts if c.source_url) / len(facts)) if facts else 0.0,
            "what_would_change": 1.0 if out.what_would_change else 0.0,
            "no_invented_urls": 1.0 if all((c.source_url or "") in case.expect.get("allowed_urls", []) or not c.source_url
                                           for c in out.claims) else 0.0,
            "confidence_honest": 1.0 if out.confidence in case.expect.get("confidence_in", ["HIGH", "MEDIUM", "LOW"]) else 0.0}


BENCHMARKS: dict[str, Benchmark] = {
    "cfo": Benchmark("cfo", "cfo-v1", FinanceFinding, [
        Case("subscription-newsletter", "Evaluate the economics of a $15/month AI news newsletter for small business owners, "
             "1 founder, no paid staff, distribution via YouTube and TikTok.", {"needs_inputs": True, "max_churn_pct": 25}),
        Case("short-runway", "computed:cash_balance = $4,000.00 ; computed:net_burn_monthly = $1,500.00 ; "
             "computed:runway_months = 2.7. Review the financial state.", {"needs_inputs": False, "escalate": True}),
        Case("consulting", "Evaluate the economics of a $497 one-off AI audit plus $1,000/month automation retainers for "
             "local service businesses.", {"needs_inputs": True, "max_churn_pct": 20}),
    ], score_cfo),
    "cto": Benchmark("cto", "cto-v1", TechFinding, [
        Case("crm", "Should a one-person consultancy build its own CRM or use an off-the-shelf one?", {}),
        Case("voice-agent", "Technology choice for an AI phone receptionist for dental offices.", {}),
        Case("db", "SQLite or PostgreSQL for a single-founder internal tool with one user?", {}),
    ], score_cto),
    "strategy": Benchmark("strategy", "strategy-v1", PlanOutput, [
        Case("launch-channel", "Plan: launch a YouTube channel about AI news for business owners and book 5 consulting "
             "calls in 60 days. Budget under $300.", {"max_cost_usd": 300}),
        Case("pilot", "Plan: run a paid pilot of an AI review-reply service with 3 local gyms in 30 days. Budget $100.",
             {"max_cost_usd": 100}),
        Case("newsletter", "Plan: reach 500 newsletter subscribers in 90 days with $0 ad spend.", {"max_cost_usd": 200}),
    ], score_strategy),
    "ceo": Benchmark("ceo", "ceo-v1", ExecutiveBrief, [
        Case("blocked", "Findings: product SUPPORT (strong pain), cfo SUPPORT, risk_audit verdict BLOCK: the market size "
             "figure was invented and the CAC assumption has no basis. Synthesize: should we build it?",
             {"must_require_approval": True, "verdict_not": ["BUILD", "PROCEED"]}),
        Case("clear", "Findings: research shows 3 sourced competitors with paying customers; product: pain 4/5 weekly; "
             "cfo: payback 4 months (computed); risk PASS_WITH_CONDITIONS (test pricing first). Synthesize.", {}),
        Case("split", "Findings: cmo SUPPORT (cheap channel), cto OPPOSE (HIPAA data, 6+ months to build securely), "
             "risk REVIEW_REQUIRED. Synthesize.", {"must_require_approval": True}),
    ], score_ceo),
}


async def run_benchmark(sm: sessionmaker, providers: ProviderRegistry, agent_id: str, model: str,
                        case_ids: list[str] | None = None) -> dict:
    if agent_id not in BENCHMARKS:
        raise AIOSError(f"No benchmark for {agent_id}. Available: {', '.join(BENCHMARKS)}")
    bm = BENCHMARKS[agent_id]
    with sm() as s:
        cfg = registry.active_config(s, agent_id)
        guard = BudgetGuard(sm, Limits.load(s))
    results = []
    for case in bm.cases:
        if case_ids and case.id not in case_ids:
            continue
        ctx = CallContext(sm=sm, providers=providers, budget=guard, workflow="eval", agent_id=agent_id, tier="EVAL")
        start = time.monotonic()
        try:
            out = await calls.structured(ctx, model=model, system=cfg.system_prompt, prompt=case.prompt, schema=bm.schema,
                                         purpose="eval", max_tokens=cfg.max_tokens)
            scores = bm.scorer(out, case)
            err = None
        except AIOSError as e:
            scores, err = {"completed": 0.0}, e.message
        total = _avg(scores)
        with sm() as s:
            s.add(Evaluation(agent_id=agent_id, benchmark=bm.name, case_id=case.id, model=model,
                             config_version=cfg.version, scores=scores, score=total, passed=total >= 0.75,
                             cost_micros=ctx.spent_micros, latency_ms=int((time.monotonic() - start) * 1000), notes=err))
            s.commit()
        results.append({"case": case.id, "score": total, "scores": scores, "cost_usd": ctx.spent_micros / 1e6, "error": err})
    avg = round(sum(r["score"] for r in results) / len(results), 4) if results else 0
    return {"agent": agent_id, "model": model, "benchmark": bm.name, "avg_score": avg, "cases": results}
