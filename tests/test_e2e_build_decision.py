"""REQUIRED TEST 1: 'Analyze whether I should build X' → agents → risk → synthesis → approval → plan → persisted."""

from sqlalchemy import func, select

from aios.core import approvals
from aios.core.actor import FOUNDER
from aios.db.enums import DecisionStatus, MemoryStatus, ProjectStatus, RunStatus, TaskKind, TaskStatus
from aios.db.models import (
    AgentRun,
    Audit,
    Claim,
    Decision,
    Memory,
    ModelUsage,
    Objective,
    Project,
    ResearchReport,
    Task,
    TaskDependency,
    WorkflowRun,
)
from aios.modules import status


async def test_build_decision_end_to_end(sm, engine, provider):
    res = await engine.run("ceo", "Analyze whether I should build an AI receptionist for dental offices.")

    # 1-3. understood, classified, planned by the CEO
    assert res["status"] == RunStatus.AWAITING_APPROVAL.value, res
    assert res["intake"]["request_type"] == "OPPORTUNITY"
    planned_agents = {t["agent"] for t in res["plan"]}
    assert planned_agents == {"research", "product", "cmo", "cto", "cfo"}  # planner's 'risk' task removed by engine

    # 4-9. every specialist ran; risk audited independently
    with sm() as s:
        runs = s.execute(select(AgentRun.agent_id, AgentRun.status).where(AgentRun.workflow_run_id == res["run_id"])).all()
        agents_run = {a for a, st in runs if st == RunStatus.COMPLETED}
        assert {"ceo", "research", "product", "cmo", "cto", "cfo", "risk", "twin"} <= agents_run
        assert s.execute(select(Audit).where(Audit.workflow_run_id == res["run_id"])).scalar_one().verdict.value == "PASS_WITH_CONDITIONS"

    # dependencies respected: cfo ran after product and cmo
    assert res["agents"]["economics"]["ok"]
    with sm() as s:
        t = {r.agent_id: r for r in s.execute(select(AgentRun).where(AgentRun.workflow_run_id == res["run_id"])).scalars()}
        assert t["cfo"].started_at >= t["product"].finished_at and t["cfo"].started_at >= t["cmo"].finished_at
        assert t["product"].started_at >= t["research"].finished_at

    # CFO numbers computed by code, not by the model
    ue = res["unit_economics"]
    assert ue["kind"] == "ESTIMATE"
    assert ue["contribution_per_customer_monthly_usd"] == 240.0
    assert ue["ltv_usd"] == 6000.0 and ue["ltv_to_cac"] == 15.0

    # research persisted with source enforcement: fabricated URL and unsourced 'fact' downgraded
    with sm() as s:
        report = s.execute(select(ResearchReport)).scalar_one()
        claims = s.execute(select(Claim).where(Claim.report_id == report.id)).scalars().all()
        assert report.live_search_used
        sourced = [c for c in claims if c.source_id]
        assert len(sourced) == 1 and sourced[0].source.url.endswith("ai-adoption-small-business-2026")
        assert all(not c.is_fact for c in claims if c.source_id is None)

    # 10-11. recommendation + decision awaiting the founder
    assert res["brief"]["verdict"] == "BUILD"
    with sm() as s:
        d = s.get(Decision, res["decision_id"])
        assert d.status == DecisionStatus.PENDING_APPROVAL
        assert len(d.options) == 2

    # 12-13. founder approves; decision saved
    with sm() as s:
        out = approvals.approve(s, res["approval_id"], FOUNDER, "Go, pilot first")
        s.commit()
    assert [f["workflow"] for f in out["follow_up"]] == ["plan", "learn"]
    with sm() as s:
        d = s.get(Decision, res["decision_id"])
        assert d.status == DecisionStatus.APPROVED and d.decision_maker == "founder"

    # 14. planner creates objective, project, milestones, tasks (event caused by the approval)
    plan_res = await engine.run("plan", "", options={"decision_id": res["decision_id"]})
    assert plan_res["status"] == "COMPLETED", plan_res
    created = plan_res["created"]
    with sm() as s:
        p = s.get(Project, created["project_id"])
        assert p.status == ProjectStatus.ACTIVE and p.decision_id == res["decision_id"]
        assert s.get(Objective, created["objective_id"]).decision_id == res["decision_id"]
        tasks = s.execute(select(Task).where(Task.project_id == p.id)).scalars().all()
        assert {t.status for t in tasks} == {TaskStatus.READY, TaskStatus.PLANNED}
        assert s.execute(select(func.count()).select_from(TaskDependency)).scalar() == 1

    # learning: twin records an INFERRED preference linked to the decision (never EXPLICIT)
    learn = await engine.run("learn", "", options={"decision_id": res["decision_id"]})
    assert learn["status"] == "COMPLETED", learn
    with sm() as s:
        m = s.get(Memory, learn["memories_created"][0])
        assert m.status == MemoryStatus.INFERRED and m.created_by == "agent:twin"

    # 15-16. everything persisted, cost recorded per call
    with sm() as s:
        run = s.get(WorkflowRun, res["run_id"])
        assert run.total_cost_micros > 0
        usage = s.execute(select(func.count(), func.sum(ModelUsage.web_search_requests))
                          .where(ModelUsage.workflow_run_id == res["run_id"])).one()
        assert usage[0] >= 10 and usage[1] == 2
        assert s.execute(select(func.count()).select_from(Task).where(Task.kind == TaskKind.WORK)).scalar() >= 9

    # 17. dashboard data reflects the new project
    with sm() as s:
        st = status.company_status(s)
        assert any(pr["id"] == created["project_id"] for pr in st["projects"])
