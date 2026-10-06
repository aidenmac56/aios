"""Model routing: the cheapest model that is good enough for the task.

Inputs: the agent's default tier, the task's complexity, workflow importance, budget remaining,
and evaluation history. Every decision carries a human-readable reason that is stored on the run.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aios.core import sysconfig
from aios.db.models import Evaluation
from aios.llm.pricing import TIER_ORDER, price_for


@dataclass
class Route:
    tier: str
    model: str
    reason: str


def _shift(tier: str, by: int) -> str:
    i = max(0, min(len(TIER_ORDER) - 1, TIER_ORDER.index(tier) + by))
    return TIER_ORDER[i]


def eval_scores(session: Session, agent_id: str, min_cases: int) -> dict[str, float]:
    """Average benchmark score per model, for the agent's ACTIVE prompt version only.

    Scores from other versions (old prompts, untested candidates) say nothing about how the live
    configuration performs, so they never steer routing.
    """
    from aios.db.models import Agent

    row = session.get(Agent, agent_id)
    version = row.active_config_version if row else 1
    rows = session.execute(
        select(Evaluation.model, func.avg(Evaluation.score), func.count())
        .where(Evaluation.agent_id == agent_id, Evaluation.config_version == version)
        .group_by(Evaluation.model)
    ).all()
    return {m: float(avg) for m, avg, n in rows if n >= min_cases}


def choose(
    session: Session,
    *,
    agent_id: str,
    default_tier: str,
    complexity: str | None = None,       # "low" | "medium" | "high"
    importance: str = "normal",          # "normal" | "high"
    budget_remaining_ratio: float = 1.0,
    floor_tier: str | None = None,       # never route below this (e.g. Risk on a BUILD decision)
) -> Route:
    models: dict[str, str] = sysconfig.get(session, "routing.models")
    overrides: dict[str, str] = sysconfig.get(session, "routing.agent_tier_overrides")
    reasons: list[str] = []

    if agent_id in overrides:
        tier = overrides[agent_id]
        reasons.append(f"founder override → {tier}")
    else:
        tier = default_tier
        reasons.append(f"agent default {tier}")
        if complexity == "low":
            tier = _shift(tier, -1)
            reasons.append(f"low complexity → {tier}")
        elif complexity == "high":
            tier = _shift(tier, +1)
            reasons.append(f"high complexity → {tier}")
        if importance == "high" and TIER_ORDER.index(tier) < TIER_ORDER.index("BALANCED"):
            tier = "BALANCED"
            reasons.append("high-importance workflow → at least BALANCED")
        threshold = float(sysconfig.get(session, "routing.downgrade_when_budget_below"))
        if budget_remaining_ratio < threshold and tier != "FAST":
            tier = _shift(tier, -1)
            reasons.append(f"budget {budget_remaining_ratio:.0%} left → {tier}")
        if floor_tier and TIER_ORDER.index(tier) < TIER_ORDER.index(floor_tier):
            tier = floor_tier
            reasons.append(f"floor {floor_tier}")

    model = models[tier]

    # Evaluation history: if a cheaper model is as good on this agent's benchmark, use it — only when the founder
    # has opted in. Otherwise eval results reach routing through improvements he tests and approves.
    margin = float(sysconfig.get(session, "routing.equivalence_margin"))
    auto = bool(sysconfig.get(session, "routing.auto_apply_eval_history"))
    scores = eval_scores(session, agent_id, int(sysconfig.get(session, "routing.min_eval_cases"))) if auto else {}
    if model in scores and agent_id not in overrides:
        chosen_price = price_for(model)
        best = model
        tier_of = {mm: t for t, mm in models.items()}
        for m, s in scores.items():
            p = price_for(m)
            if floor_tier and m in tier_of and TIER_ORDER.index(tier_of[m]) < TIER_ORDER.index(floor_tier):
                continue
            if p and chosen_price and p.output < price_for(best).output and s >= scores[model] - margin:
                best = m
        if best != model:
            reasons.append(f"eval history: {best} scored {scores[best]:.2f} vs {model} {scores[model]:.2f} → {best}")
            model = best
            tier = next((t for t, mm in models.items() if mm == best), tier)

    return Route(tier=tier, model=model, reason="; ".join(reasons))
