"""REQUIRED TEST 2: 'Audit the entire AI company' → measured observations → proposals with every field →
nothing changes until approved → approval applies the change → rollback restores it."""

from sqlalchemy import select

from aios.core import approvals, sysconfig
from aios.core.actor import FOUNDER
from aios.db.enums import ImprovementStatus
from aios.db.models import Audit, Improvement

REQUIRED = ("problem", "evidence", "root_cause", "change", "expected_impact", "cost", "risk", "test_plan", "rollback")


async def test_system_audit(sm, engine):
    # generate some real activity to audit
    await engine.run("ceo", "Analyze whether I should build an AI receptionist for dental offices.")
    res = await engine.run("audit", "Audit the entire AI company.")
    assert res["status"] == "COMPLETED", res

    obs = res["observations"]
    for area in ("agents", "workflows", "models", "planning", "memory", "research", "finance", "security", "prompts"):
        assert area in obs
    assert obs["agents"]["research"]["runs"] >= 1
    assert obs["security"]["audit_log_chain"]["ok"]

    with sm() as s:
        audit = s.get(Audit, res["audit_id"])
        assert audit.observations and audit.verdict is not None
        imps = s.execute(select(Improvement).where(Improvement.audit_id == audit.id)).scalars().all()
        assert len(imps) == 1  # three reviewers proposed the same change; deduplicated
        imp = imps[0]
        for f in REQUIRED:
            assert getattr(imp, f), f
        assert imp.status == ImprovementStatus.PROPOSED
        # nothing changed yet
        assert sysconfig.get(s, "routing.agent_tier_overrides") == {}

    # approval gate → applied → rollback
    from aios.modules import improvements

    with sm() as s:
        appr = improvements.request_implementation(s, FOUNDER, imp.id)
        s.commit()
    with sm() as s:
        out = approvals.approve(s, appr.id, FOUNDER, "try it")
        s.commit()
        assert out["applied"]["new"] == {"analytics": "FAST"}
        assert sysconfig.get(s, "routing.agent_tier_overrides") == {"analytics": "FAST"}
    with sm() as s:
        improvements.rollback(s, FOUNDER, imp.id, "quality dropped")
        s.commit()
        assert sysconfig.get(s, "routing.agent_tier_overrides") == {}
        assert s.get(Improvement, imp.id).status == ImprovementStatus.ROLLED_BACK
