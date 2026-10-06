"""Model routing, plan validation, contradiction detection, task completion rules."""

import pytest

from aios.agents.schemas import PlanOutput
from aios.core import sysconfig
from aios.core.actor import FOUNDER, agent
from aios.core.errors import InvalidPlan, ValidationFailed
from aios.db.enums import MemoryCategory, MemoryStatus, Provenance, TaskStatus
from aios.db.models import Evaluation
from aios.llm import router
from aios.llm.pricing import estimate_micros
from aios.modules import memory, planning
from tests.fakes import DEFAULTS


def test_routing_rules(sm):
    with sm() as s:
        assert router.choose(s, agent_id="analytics", default_tier="FAST").model == "claude-haiku-4-5-20251001"
        assert router.choose(s, agent_id="ceo", default_tier="DEEP").model == "claude-opus-5-5"
        assert router.choose(s, agent_id="ceo", default_tier="DEEP", complexity="low").tier == "BALANCED"
        assert router.choose(s, agent_id="analytics", default_tier="FAST", importance="high").tier == "BALANCED"
        r = router.choose(s, agent_id="cfo", default_tier="BALANCED", budget_remaining_ratio=0.1)
        assert r.tier == "FAST" and "budget" in r.reason
        assert router.choose(s, agent_id="risk", default_tier="DEEP", budget_remaining_ratio=0.1, floor_tier="DEEP").tier == "DEEP"


def test_eval_history_moves_routing_only_when_founder_opts_in(sm):
    with sm() as s:
        for i in range(3):
            s.add(Evaluation(agent_id="cfo", benchmark="cfo-v1", case_id=f"c{i}", model="claude-sonnet-5-5", scores={},
                             score=0.90, passed=True))
            s.add(Evaluation(agent_id="cfo", benchmark="cfo-v1", case_id=f"c{i}", model="claude-haiku-4-5-20251001",
                             scores={}, score=0.89, passed=True))
        s.flush()
        assert router.choose(s, agent_id="cfo", default_tier="BALANCED").model == "claude-sonnet-5-5"  # default: off
        sysconfig.set_value(s, "routing.auto_apply_eval_history", True, FOUNDER, "opt in")
        r = router.choose(s, agent_id="cfo", default_tier="BALANCED")
        assert r.model == "claude-haiku-4-5-20251001" and "eval history" in r.reason
        # a floor still wins over eval history
        assert router.choose(s, agent_id="cfo", default_tier="BALANCED", floor_tier="BALANCED").model == "claude-sonnet-5-5"


def test_pricing():
    # Opus 5.5: $4 in / $20 out per MTok; one web search = $0.01
    assert estimate_micros("claude-opus-5-5", input_tokens=1_000_000, output_tokens=0) == 4_000_000
    assert estimate_micros("claude-haiku-4-5-20251001", input_tokens=0, output_tokens=1000, web_searches=1) == 5_000 + 10_000


def _plan(**over):
    d = DEFAULTS["submit_planoutput"]()
    d.update(over)
    return PlanOutput.model_validate(d)


def test_plan_validation_rejects_cycles_and_unknown_refs():
    p = _plan()
    p.tasks[0].depends_on = ["t2"]  # t1 ↔ t2
    with pytest.raises(InvalidPlan, match="cycle"):
        planning.validate_plan(p)
    p = _plan()
    p.tasks[1].milestone_key = "nope"
    with pytest.raises(InvalidPlan, match="unknown milestone"):
        planning.validate_plan(p)


def test_preserve_cash_principle_flags_expensive_plans(sm):
    with sm() as s:
        memory.add(s, FOUNDER, category=MemoryCategory.FOUNDER, subject="cash", content="We need to preserve cash.",
                   status=MemoryStatus.EXPLICIT, provenance=Provenance.FOUNDER, tags=["principle:preserve_cash"])
        cheap = planning.create_from_plan(s, agent("strategy"), _plan())  # $300 ≤ default $1,000 ceiling
        assert cheap["status"] == "ACTIVE" and not cheap["contradictions"]
        d = DEFAULTS["submit_planoutput"]()
        d["project"]["expected_cost_usd"] = 5000
        d["project"]["name"] = "Paid ads blitz"
        pricey = planning.create_from_plan(s, agent("strategy"), PlanOutput.model_validate(d))
        assert pricey["status"] == "PROPOSED" and pricey["approval_id"]
        assert "preserve cash" in pricey["contradictions"][0]


def test_task_completion_requires_criteria_and_unblocks_dependents(sm):
    with sm() as s:
        created = planning.create_from_plan(s, agent("strategy"), _plan())
        t1, t2 = created["task_ids"]
        with pytest.raises(ValidationFailed):
            planning.update_task(s, FOUNDER, t1, status=TaskStatus.COMPLETED)
        planning.update_task(s, FOUNDER, t1, criteria_met=True, status=TaskStatus.COMPLETED)
        from aios.db.models import Task

        assert s.get(Task, t2).status == TaskStatus.READY


def test_agents_cannot_write_plans_without_permission(sm):
    from aios.core.errors import PermissionDenied

    with sm() as s, pytest.raises(PermissionDenied):
        planning.create_from_plan(s, agent("cmo"), _plan())


def test_founder_can_change_routing_config(sm):
    with sm() as s:
        sysconfig.set_value(s, "routing.agent_tier_overrides", {"ceo": "BALANCED"}, FOUNDER, "cost")
        assert router.choose(s, agent_id="ceo", default_tier="DEEP").tier == "BALANCED"
