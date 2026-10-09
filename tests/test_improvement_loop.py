"""TEST → COMPARE → APPROVE → IMPLEMENT → VERIFY → ROLLBACK for routing and prompt changes; trend intelligence."""

import pytest
from sqlalchemy import func, select

from aios.agents import registry
from aios.core import approvals, sysconfig
from aios.core.actor import FOUNDER
from aios.core.errors import PermissionDenied
from aios.db.enums import ImprovementStatus
from aios.db.models import Agent, Evaluation, Experiment, Improvement
from aios.llm.provider import ProviderRegistry
from aios.llm.testing import ScriptedProvider
from aios.modules import improvements
from aios.orchestrator.engine import Engine
from tests.fakes import DEFAULTS, finding, responder


def _improvement(sm, spec, title="Change"):
    with sm() as s:
        imp = Improvement(title=title, area="model_choice", problem="p", evidence=["e"], root_cause="r", change="c",
                          expected_impact="cheaper at equal quality", cost="none", risk="quality", test_plan="benchmark",
                          rollback="restore", metric="benchmark score", change_spec=spec, proposed_by="agent:analytics")
        s.add(imp)
        s.commit()
        return imp.id


async def test_routing_change_tested_then_approved(sm, engine):
    imp_id = _improvement(sm, {"type": "routing_override", "key": "routing.agent_tier_overrides",
                               "value": '{"cfo": "FAST"}'})
    res = await engine.run("test", "", options={"improvement_id": imp_id})
    assert res["status"] == "COMPLETED", res
    t = res["test"]
    assert t["verdict"] == "EQUIVALENT"
    assert t["baseline"]["model"] == "claude-sonnet-5-5" and t["candidate"]["model"] == "claude-haiku-4-5-20251001"
    with sm() as s:
        assert s.get(Improvement, imp_id).status == ImprovementStatus.TESTED
        exp = s.get(Experiment, t["experiment_id"])
        assert exp.status == "COMPLETED" and exp.results["verdict"] == "EQUIVALENT"
        assert s.execute(select(func.count()).select_from(Evaluation).where(Evaluation.experiment_id == exp.id)).scalar() == 6
        # testing alone changes nothing live
        assert sysconfig.get(s, "routing.agent_tier_overrides") == {}
        appr = improvements.request_implementation(s, FOUNDER, imp_id)
        approvals.approve(s, appr.id, FOUNDER, "ship it")
        s.commit()
        assert sysconfig.get(s, "routing.agent_tier_overrides") == {"cfo": "FAST"}


async def test_prompt_change_versioned_tested_activated_and_rolled_back(sm):
    # the candidate prompt makes the CFO drop its assumptions → worse benchmark score
    def cfo(req):
        if "ADDITIONAL GUIDANCE" in req.system:
            return finding(finance_inputs=None)
        return DEFAULTS["submit_financefinding"]()

    prov = ScriptedProvider(responder({"submit_financefinding": cfo}))
    eng = Engine(sm, ProviderRegistry(providers={"anthropic": prov}))
    imp_id = _improvement(sm, {"type": "prompt_addendum", "key": "cfo",
                               "value": "Keep answers under 100 words and skip assumptions."}, "Shorter CFO answers")
    res = await eng.run("test", "", options={"improvement_id": imp_id})
    assert res["status"] == "COMPLETED", res
    assert res["test"]["verdict"] == "WORSE"
    with sm() as s:
        assert s.get(Agent, "cfo").active_config_version == 1  # candidate exists but is not live
        assert [v["version"] for v in registry.versions(s, "cfo")] == [1, 2]
        # the founder can still choose to ship it; the version goes live and can be rolled back
        appr = improvements.request_implementation(s, FOUNDER, imp_id)
        out = approvals.approve(s, appr.id, FOUNDER, "try anyway")
        s.commit()
        assert (out["applied"]["type"], out["applied"]["old_version"], out["applied"]["new_version"]) == ("prompt", 1, 2)
        assert s.get(Agent, "cfo").active_config_version == 2
        assert "ADDITIONAL GUIDANCE" in registry.active_config(s, "cfo").system_prompt
        improvements.rollback(s, FOUNDER, imp_id, "worse")
        s.commit()
        assert s.get(Agent, "cfo").active_config_version == 1


def test_only_founder_activates_agent_versions(sm):
    with sm() as s:
        v = registry.propose_version(s, "research", system_prompt="new", config=None, reason="r",
                                     expected_improvement="e", created_by="agent:coo")
        with pytest.raises(PermissionDenied):
            registry.activate_version(s, "research", v.version, "agent:coo", None, "self-upgrade")


async def test_untestable_change_fails_clearly(sm, engine):
    imp_id = _improvement(sm, {"type": "budget", "key": "budget.daily_limit_usd", "value": "30"})
    res = await engine.run("test", "", options={"improvement_id": imp_id})
    assert res["status"] == "FAILED" and "by hand" in res["error"]["message"]


async def test_trends(sm, engine):
    res = await engine.run("trends", "AI tools for local service businesses")
    assert res["status"] == "COMPLETED", res
    names = {t["name"]: t for t in res["trends"]["trends"]}
    assert names["AI girlfriend apps"]["mostly_viral_discussion"] is True
    assert names["AI phone receptionists"]["confidence"] == "HIGH"  # live search happened


async def test_trends_without_live_search_cap_confidence(sm, engine, monkeypatch):
    from aios import config

    monkeypatch.setenv("AIOS_WEB_SEARCH", "0")
    config.get_settings.cache_clear()
    try:
        res = await engine.run("trends", "AI tools for local service businesses")
    finally:
        config.get_settings.cache_clear()
    assert all(t["confidence"] != "HIGH" for t in res["trends"]["trends"])
    assert "no live web search" in res["trends"]["note"]


async def test_draft_command_writes_content_not_projects(sm, engine):
    from aios.db.models import Project

    res = await engine.run("draft", "10 video topics for local service businesses")
    assert res["status"] == "COMPLETED", res
    assert res["draft"]["items"][1]["label"] == "Topic 1"
    with sm() as s:
        assert s.query(Project).count() == 0
