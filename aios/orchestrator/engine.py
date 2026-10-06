"""The orchestration engine.

REQUEST → UNDERSTAND → RETRIEVE CONTEXT → CLASSIFY → PLAN → SELECT AGENTS → EXECUTE (DAG, parallel where
independent) → VERIFY (Risk) → SYNTHESIZE (Twin + CEO) → APPROVAL → SAVE.

Every workflow is started explicitly (CLI, API/dashboard, or an approval the founder just gave).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import sessionmaker

from aios.agents.schemas import (
    AuditReview,
    ExecutiveBrief,
    Intake,
    PlannedTask,
    PlanOutput,
    PrioritiesOutput,
    ResearchFinding,
    RiskAudit,
    TechFinding,
    TwinAlignment,
    WorkPlan,
)
from aios.core import audit, events, sysconfig
from aios.core.actor import FOUNDER, Actor
from aios.core.actor import agent as agent_actor
from aios.core.budget import BudgetGuard, Limits
from aios.core.errors import AIOSError, BudgetExceeded, InvalidPlan, NotFound, ValidationFailed
from aios.core.util import micros_to_usd, utcnow
from aios.db.enums import AuditVerdict, DecisionStatus, ImprovementStatus, MemoryCategory, MemoryStatus, Provenance, RunStatus
from aios.db.models import Audit, Decision, Memory, WorkflowRun
from aios.llm.provider import ProviderRegistry
from aios.modules import decisions, finance, improvements, memory, planning
from aios.orchestrator import context as ctxmod
from aios.orchestrator.runner import AgentResult, RunCtx, run_agent

log = logging.getLogger("aios.engine")

DECISION_TYPES = {"DECISION", "OPPORTUNITY"}


class Engine:
    def __init__(self, sm: sessionmaker, providers: ProviderRegistry | Callable[[], ProviderRegistry],
                 on_progress: Callable[[str, str], None] | None = None):
        self.sm = sm
        self._providers = providers
        self.on_progress = on_progress
        self.workflows: dict[str, Callable] = {
            "ceo": self.wf_ceo, "board": self.wf_board, "opportunity": self.wf_opportunity,
            "decision": self.wf_decision, "research": self.wf_research, "market": self.wf_market,
            "cto": self.wf_cto, "finance": self.wf_finance, "plan": self.wf_plan, "priorities": self.wf_priorities,
            "audit": self.wf_audit, "improve": self.wf_improve, "learn": self.wf_learn,
            "test": self.wf_test, "trends": self.wf_trends,
        }

    @property
    def providers(self) -> ProviderRegistry:
        if callable(self._providers) and not isinstance(self._providers, ProviderRegistry):
            self._providers = self._providers()
        return self._providers

    # ------------------------------------------------------------------ lifecycle

    def create_run(self, command: str, request: str, actor: Actor = FOUNDER, importance: str = "normal") -> str:
        if command not in self.workflows:
            raise ValidationFailed(f"Unknown command '{command}'. Known: {', '.join(sorted(self.workflows))}")
        with self.sm() as s:
            limits = Limits.load(s)
            run = WorkflowRun(command=command, request=request, actor=str(actor), status=RunStatus.PENDING,
                              importance=importance, budget_limit_micros=limits.workflow)
            s.add(run)
            s.commit()
            return run.id

    async def run(self, command: str, request: str, *, actor: Actor = FOUNDER, options: dict | None = None,
                  run_id: str | None = None) -> dict[str, Any]:
        options = options or {}
        run_id = run_id or self.create_run(command, request, actor, options.get("importance", "normal"))
        with self.sm() as s:
            run = s.get(WorkflowRun, run_id)
            run.status, run.started_at = RunStatus.RUNNING, utcnow()
            limits = Limits.load(s, options.get("budget_usd"))
            run.budget_limit_micros = limits.workflow
            events.emit(s, events.WORKFLOW_STARTED, str(actor), {"command": command}, run_id)
            audit.record(s, who=str(actor), what=f"workflow.start:{command}", why=request[:500], target_type="workflow_run",
                         target_id=run_id)
            s.commit()
        guard = BudgetGuard(self.sm, limits, run_id)
        rc = RunCtx(sm=self.sm, providers=None, guard=guard, run_id=run_id, command=command, request=request,
                    importance=options.get("importance", "normal"),
                    progress=lambda msg: self._progress(run_id, msg))
        status, result, error = RunStatus.COMPLETED, {}, None
        try:
            if self._needs_llm(command, options):
                rc.providers = self.providers
            result = await self.workflows[command](rc, request, options) or {}
            if result.get("_status"):
                status = RunStatus(result.pop("_status"))
        except BudgetExceeded as e:
            status, error = RunStatus.PARTIAL, e.message
            result = {"stopped": "budget", "budget": e.details, "completed": getattr(e, "partial", {}),
                      "remaining": getattr(e, "remaining", [])}
            with self.sm() as s:
                events.emit(s, events.BUDGET_STOP, "system", e.details, run_id)
                s.commit()
        except AIOSError as e:
            status, error = RunStatus.FAILED, e.message
            result = {"error": e.to_dict()}
        except Exception as e:  # never hide failures
            log.exception("workflow %s crashed", command)
            status, error = RunStatus.FAILED, f"{type(e).__name__}: {e}"
            result = {"error": {"code": "internal_error", "message": error}}
        result["cost_usd"] = micros_to_usd(guard.workflow_spent)
        result["research_report_ids"] = rc.research_report_ids
        with self.sm() as s:
            run = s.get(WorkflowRun, run_id)
            if run.status == RunStatus.AWAITING_APPROVAL and status == RunStatus.COMPLETED:
                status = RunStatus.AWAITING_APPROVAL
            run.status, run.result, run.error = status, json.loads(json.dumps(result, default=str)), error
            run.total_cost_micros = guard.workflow_spent
            run.finished_at = utcnow()
            events.emit(s, events.WORKFLOW_FINISHED, "system", {"command": command, "status": status.value,
                                                                "cost_usd": result["cost_usd"]}, run_id)
            audit.record(s, who=str(actor), what=f"workflow.finish:{command}", why=request[:300],
                         output={"status": status.value}, cost_micros=guard.workflow_spent, result=status.value,
                         error=error, target_type="workflow_run", target_id=run_id)
            s.commit()
        return {"run_id": run_id, "status": status.value, **result}

    def _needs_llm(self, command: str, options: dict) -> bool:
        return not (command == "finance" and options.get("no_commentary"))

    def _progress(self, run_id: str, msg: str) -> None:
        with self.sm() as s:
            run = s.get(WorkflowRun, run_id)
            run.progress = [*(run.progress or []), {"at": utcnow().isoformat(), "msg": msg}]
            s.commit()
        if self.on_progress:
            self.on_progress(run_id, msg)

    def _set_status(self, rc: RunCtx, status: RunStatus, **fields) -> None:
        with self.sm() as s:
            run = s.get(WorkflowRun, rc.run_id)
            run.status = status
            for k, v in fields.items():
                setattr(run, k, v)
            s.commit()

    def _context(self, request: str, agent_id: str | None = None) -> str:
        with self.sm() as s:
            return ctxmod.build(s, request, agent_id=agent_id)

    # ------------------------------------------------------------------ DAG execution

    def validate_plan(self, plan: WorkPlan, *, require_risk: bool) -> list[PlannedTask]:
        with self.sm() as s:
            max_tasks = int(sysconfig.get(s, "orchestrator.max_tasks_per_workflow"))
        tasks = [t for t in plan.tasks if t.agent != "risk"]  # Risk is placed by the engine, not the planner
        seen: set[tuple[str, str]] = set()
        deduped = []
        for t in tasks:
            sig = (t.agent, t.objective.strip().lower()[:120])
            if sig in seen:
                continue
            seen.add(sig)
            deduped.append(t)
        if not deduped:
            raise InvalidPlan("The plan has no specialist tasks.")
        if len(deduped) + (1 if require_risk else 0) > max_tasks:
            raise InvalidPlan(f"Plan has {len(deduped)} tasks; limit is {max_tasks}.")
        keys = [t.key for t in deduped]
        if len(set(keys)) != len(keys):
            raise InvalidPlan("Duplicate task keys in plan.")
        for t in deduped:
            t.depends_on = [d for d in t.depends_on if d in keys]  # dependencies on removed tasks are dropped
        planning.topo_order(keys, {t.key: t.depends_on for t in deduped})
        return deduped

    async def execute(self, rc: RunCtx, tasks: list[PlannedTask], context_text: str,
                      schema_for: dict[str, Any] | None = None) -> dict[str, AgentResult]:
        with self.sm() as s:
            sem = asyncio.Semaphore(int(sysconfig.get(s, "orchestrator.max_parallel")))
        by_key = {t.key: t for t in tasks}
        results: dict[str, AgentResult] = {}
        state = {t.key: "pending" for t in tasks}
        budget_error: BudgetExceeded | None = None

        async def one(t: PlannedTask) -> AgentResult:
            async with sem:
                deps = {d: results[d].output for d in t.depends_on if results.get(d) and results[d].ok}
                return await run_agent(rc, agent_id=t.agent, key=t.key, objective=t.objective,
                                       context_text=context_text, deps=deps, complexity=t.complexity,
                                       schema=(schema_for or {}).get(t.key))

        while any(v == "pending" for v in state.values()):
            for k, t in by_key.items():
                if state[k] == "pending" and any(state[d] in ("failed", "blocked") for d in t.depends_on):
                    state[k] = "blocked"
                    results[k] = AgentResult(k, t.agent, False, None, "blocked: a dependency failed")
                    rc.progress(f"{t.agent} blocked: dependency failed")
            ready = [t for k, t in by_key.items() if state[k] == "pending" and all(state[d] == "done" for d in t.depends_on)]
            if not ready:
                break
            for t in ready:
                state[t.key] = "running"
            outs = await asyncio.gather(*(one(t) for t in ready), return_exceptions=True)
            for t, out in zip(ready, outs):
                if isinstance(out, BudgetExceeded):
                    budget_error = out
                    state[t.key] = "blocked"
                    results[t.key] = AgentResult(t.key, t.agent, False, None, out.message)
                elif isinstance(out, BaseException):
                    raise out
                else:
                    results[t.key] = out
                    state[t.key] = "done" if out.ok else "failed"
            if budget_error:
                budget_error.partial = {k: r.output for k, r in results.items() if r.ok}
                budget_error.remaining = [k for k, v in state.items() if v in ("pending", "blocked")]
                raise budget_error
        return results

    # ------------------------------------------------------------------ verification + synthesis

    @staticmethod
    def disagreements(results: dict[str, AgentResult]) -> list[dict]:
        stances = {k: (r.output or {}).get("stance") for k, r in results.items() if r.ok}
        support = [k for k, v in stances.items() if v == "SUPPORT"]
        oppose = [k for k, v in stances.items() if v == "OPPOSE"]
        if support and oppose:
            return [{"topic": "overall proposal",
                     "support": [{"task": k, "conclusion": results[k].output.get("conclusion")} for k in support],
                     "oppose": [{"task": k, "conclusion": results[k].output.get("conclusion")} for k in oppose]}]
        return []

    async def verify_and_synthesize(self, rc: RunCtx, *, request: str, intake: Intake | None,
                                    results: dict[str, AgentResult], context_text: str, mode: str,
                                    decision_question: str | None) -> dict:
        ok = {k: r.output for k, r in results.items() if r.ok}
        failed = {k: r.error for k, r in results.items() if not r.ok}
        conflicts = self.disagreements(results)
        risk_res = await run_agent(
            rc, agent_id="risk", key="risk", schema=RiskAudit, context_text=context_text, deps=ok,
            floor_tier="BALANCED" if rc.importance != "high" else "DEEP",
            objective=("Audit every finding below for unsupported claims, wrong numbers (compare against computed "
                       "values), weak assumptions, and agents agreeing without evidence. Give a verdict."
                       + (f" Failed tasks: {failed}." if failed else "")))
        risk = risk_res.output if risk_res.ok else None
        if risk:
            with self.sm() as s:
                s.add(Audit(scope="workflow", target_type="workflow_run", target_id=rc.run_id,
                            verdict=AuditVerdict(risk["verdict"]), summary=risk["summary"],
                            findings=risk.get("issues", []), auditor="risk", workflow_run_id=rc.run_id))
                events.emit(s, events.AUDIT_COMPLETED, "agent:risk", {"verdict": risk["verdict"]}, rc.run_id)
                s.commit()
        twin_res = await run_agent(
            rc, agent_id="twin", key="twin", schema=TwinAlignment, complexity="low", context_text=context_text,
            deps={**ok, **({"risk": risk} if risk else {})},
            objective="State how the options in these findings fit the founder's goals and preferences. Cite memory ids "
                      "and their status. List preferences that matter here but are unknown.")
        twin = twin_res.output if twin_res.ok else None
        extra = []
        if conflicts:
            extra.append("DISAGREEMENTS DETECTED BY THE ENGINE (resolve with evidence or mark unresolved):\n"
                         + json.dumps(conflicts, default=str))
        if failed:
            extra.append("TASKS THAT FAILED (their questions are unanswered; reflect this in uncertainty):\n"
                         + json.dumps(failed))
        if mode == "opportunity":
            extra.append("This is an opportunity evaluation: fill the scorecard for all 12 dimensions and set verdict "
                         "to BUILD, INVESTIGATE, WATCH or PASS. decision_type = BUILD.")
        elif mode == "decision":
            extra.append("This is a decision analysis: list at least two real options with pros, cons, expected value "
                         "and risk, mark the recommended one, and set requires_approval = true.")
        elif mode == "analysis":
            extra.append("If no decision is needed, set verdict NO_DECISION and requires_approval = false.")
        ceo_res = await run_agent(
            rc, agent_id="ceo", key="synthesis", schema=ExecutiveBrief, context_text=context_text,
            deps={**ok, **({"risk_audit": risk} if risk else {}), **({"founder_alignment": twin} if twin else {})},
            extra="\n\n".join(extra),
            objective=(f"Synthesize the executive brief for the founder. Question: {decision_question or request}. "
                       "Conclusion first. Resolve disagreements using evidence. Include the strongest opposing "
                       "arguments, risks, costs (estimates), upside, uncertainty, one recommended action and next steps."))
        if not ceo_res.ok:
            raise AIOSError(f"CEO synthesis failed: {ceo_res.error}")
        brief = ExecutiveBrief.model_validate({k: v for k, v in ceo_res.output.items() if not k.startswith("_")})
        # Code-enforced: a Risk BLOCK or REVIEW_REQUIRED always reaches the founder.
        if risk and risk["verdict"] in ("BLOCK", "REVIEW_REQUIRED"):
            if not brief.requires_approval:
                brief.requires_approval = True
            note = f"Independent risk audit verdict: {risk['verdict']} — {risk['summary']}"
            if note not in brief.uncertainty:
                brief.uncertainty = f"{note}\n{brief.uncertainty}"
        if mode in ("decision", "opportunity") and brief.verdict != "NO_DECISION":
            brief.requires_approval = True
        out = {"brief": brief.model_dump(), "risk_audit": risk, "founder_alignment": twin,
               "agents": {k: {"agent": r.agent_id, "ok": r.ok, "summary": (r.output or {}).get("summary"),
                              "stance": (r.output or {}).get("stance"), "error": r.error, "run_id": r.run_id}
                          for k, r in results.items()},
               "disagreements": conflicts}
        # Unit economics computed by code, surfaced as-is.
        for r in results.values():
            if r.ok and r.output.get("computed_unit_economics"):
                out["unit_economics"] = r.output["computed_unit_economics"]
        if brief.requires_approval:
            with self.sm() as s:
                d, appr = decisions.create_from_brief(s, agent_actor("ceo"), brief,
                                                      question=decision_question or request,
                                                      context=(intake.intent if intake else None),
                                                      workflow_run_id=rc.run_id)
                run = s.get(WorkflowRun, rc.run_id)
                run.decision_id = d.id
                s.commit()
                out["decision_id"], out["approval_id"] = d.id, (appr.id if appr else None)
            out["_status"] = RunStatus.AWAITING_APPROVAL.value
        return out

    # ------------------------------------------------------------------ workflows

    async def intake(self, rc: RunCtx, request: str, context_text: str) -> Intake:
        res = await run_agent(rc, agent_id="ceo", key="intake", schema=Intake, complexity="low",
                              context_text=context_text,
                              objective="Understand and classify this request: the real intent, the decision being "
                                        "supported, importance, key questions and missing information.")
        if not res.ok:
            raise AIOSError(f"CEO intake failed: {res.error}")
        intake = Intake.model_validate({k: v for k, v in res.output.items() if not k.startswith("_")})
        self._set_status(rc, RunStatus.RUNNING, understanding=intake.model_dump())
        if intake.importance == "high":
            rc.importance = "high"
        return intake

    async def plan_work(self, rc: RunCtx, request: str, intake: Intake, context_text: str) -> list[PlannedTask]:
        res = await run_agent(
            rc, agent_id="ceo", key="plan", schema=WorkPlan, complexity="low", context_text=context_text,
            deps={"intake": intake.model_dump()},
            objective=("Plan the work. Choose only the specialists needed (research, product, cmo, cto, cfo, coo, "
                       "strategy, analytics). Do not include risk; the engine adds the independent audit. "
                       "Make tasks independent unless one truly needs another's output. Existing fresh research in "
                       "context should be reused, not redone."))
        if not res.ok:
            raise AIOSError(f"CEO planning failed: {res.error}")
        plan = WorkPlan.model_validate({k: v for k, v in res.output.items() if not k.startswith("_")})
        tasks = self.validate_plan(plan, require_risk=True)
        self._set_status(rc, RunStatus.RUNNING, plan=plan.model_dump())
        rc.progress("plan: " + ", ".join(f"{t.key}→{t.agent}" + (f" (after {','.join(t.depends_on)})" if t.depends_on else "")
                                         for t in tasks))
        return tasks

    async def wf_ceo(self, rc: RunCtx, request: str, options: dict) -> dict:
        context_text = self._context(request)
        intake = await self.intake(rc, request, context_text)
        if intake.request_type == "PLAN":
            return await self.wf_plan(rc, request, options)
        if intake.request_type == "AUDIT":
            return await self.wf_audit(rc, request, options)
        if intake.request_type == "FINANCE":
            return await self.wf_finance(rc, request, options)
        tasks = await self.plan_work(rc, request, intake, context_text)
        results = await self.execute(rc, tasks, context_text)
        mode = ("opportunity" if intake.request_type == "OPPORTUNITY" else
                "decision" if intake.request_type == "DECISION" else "analysis")
        out = await self.verify_and_synthesize(rc, request=request, intake=intake, results=results,
                                               context_text=context_text, mode=mode,
                                               decision_question=intake.decision_question or None)
        return {"intake": intake.model_dump(), "plan": [t.model_dump() for t in tasks], **out}

    async def wf_decision(self, rc: RunCtx, request: str, options: dict) -> dict:
        context_text = self._context(request)
        intake = await self.intake(rc, request, context_text)
        intake.request_type = "DECISION"
        tasks = await self.plan_work(rc, request, intake, context_text)
        results = await self.execute(rc, tasks, context_text)
        out = await self.verify_and_synthesize(rc, request=request, intake=intake, results=results,
                                               context_text=context_text, mode="decision",
                                               decision_question=intake.decision_question or request)
        return {"intake": intake.model_dump(), "plan": [t.model_dump() for t in tasks], **out}

    async def wf_board(self, rc: RunCtx, request: str, options: dict) -> dict:
        context_text = self._context(request)
        q = f"Board review of: {request}"
        tasks = [PlannedTask(key=a, agent=a, objective=f"From your seat as {a.upper()}, assess: {request}", complexity="medium")
                 for a in ("cfo", "cto", "cmo", "product", "coo")]
        rc.progress("board: cfo, cto, cmo, product, coo in parallel → risk → twin → ceo")
        results = await self.execute(rc, tasks, context_text)
        out = await self.verify_and_synthesize(rc, request=request, intake=None, results=results,
                                               context_text=context_text, mode="decision", decision_question=q)
        return out

    async def wf_opportunity(self, rc: RunCtx, request: str, options: dict) -> dict:
        rc.importance = "high"
        context_text = self._context(request)
        tasks = [
            PlannedTask(key="market", agent="research", complexity="high",
                        objective=f"Market research for this opportunity: {request}. Size, growth, competitors, customer "
                                  "evidence, pricing in the market, and regulation."),
            PlannedTask(key="customer", agent="product", depends_on=["market"], complexity="medium",
                        objective=f"Is there an important customer problem here? {request}"),
            PlannedTask(key="distribution", agent="cmo", depends_on=["market"], complexity="medium",
                        objective=f"How would this reach customers, at what cost to test? {request}"),
            PlannedTask(key="feasibility", agent="cto", depends_on=["market"], complexity="medium",
                        objective=f"Technical feasibility, stack, build vs buy, time to MVP: {request}"),
            PlannedTask(key="economics", agent="cfo", depends_on=["customer", "distribution"], complexity="medium",
                        objective=f"Model the economics: give finance_inputs assumptions with basis. {request}"),
        ]
        rc.progress("opportunity: research → product + cmo + cto → cfo → risk → twin → ceo")
        results = await self.execute(rc, tasks, context_text)
        return await self.verify_and_synthesize(rc, request=request, intake=None, results=results,
                                                context_text=context_text, mode="opportunity",
                                                decision_question=f"Should we build: {request}?")

    async def wf_market(self, rc: RunCtx, request: str, options: dict) -> dict:
        context_text = self._context(request)
        tasks = [
            PlannedTask(key="market", agent="research", complexity="high",
                        objective=f"Research this market: {request}. Size, growth, segments, competitors, trends, sources."),
            PlannedTask(key="growth", agent="cmo", depends_on=["market"], complexity="medium",
                        objective=f"Positioning, channels and experiments for this market: {request}"),
            PlannedTask(key="customer", agent="product", depends_on=["market"], complexity="medium",
                        objective=f"Customer problems and willingness to pay in this market: {request}"),
        ]
        results = await self.execute(rc, tasks, context_text)
        return await self.verify_and_synthesize(rc, request=request, intake=None, results=results,
                                                context_text=context_text, mode="analysis", decision_question=None)

    async def wf_research(self, rc: RunCtx, request: str, options: dict) -> dict:
        context_text = self._context(request)
        res = await run_agent(rc, agent_id="research", key="research", schema=ResearchFinding, complexity="high",
                              context_text=context_text, objective=request, reuse=not options.get("force"))
        if not res.ok:
            raise AIOSError(f"Research failed: {res.error}")
        return {"research": res.output}

    async def wf_cto(self, rc: RunCtx, request: str, options: dict) -> dict:
        context_text = self._context(request, agent_id="cto")
        deps = {}
        if options.get("research", True):
            r = await run_agent(rc, agent_id="research", key="tech_research", schema=ResearchFinding, complexity="medium",
                                context_text=context_text,
                                objective=f"Current state of the technologies, tools, models or vendors relevant to: {request}. "
                                          "Pricing, maturity, reliability, known issues. Prefer official docs and changelogs.")
            if r.ok:
                deps["tech_research"] = r.output
        res = await run_agent(rc, agent_id="cto", key="cto", schema=TechFinding, complexity="high",
                              context_text=context_text, deps=deps,
                              objective=f"Technology review: {request}. Score all 10 dimensions and check the technology "
                                        "decision history before recommending any reversal.")
        if not res.ok:
            raise AIOSError(f"CTO review failed: {res.error}")
        return {"cto": res.output}

    async def wf_finance(self, rc: RunCtx, request: str, options: dict) -> dict:
        with self.sm() as s:
            summ = finance.summary(s)
            rec = finance.reconcile(s) if summ.get("has_data") else None
        out: dict[str, Any] = {"financials": summ, "reconciliation": rec}
        if options.get("no_commentary") or rc.providers is None:
            return out
        res = await run_agent(rc, agent_id="cfo", key="cfo", complexity="medium",
                              context_text=self._context(request or "financial state"),
                              objective=("Interpret the company's financial state from the computed metrics: revenue, "
                                         "expenses, burn, runway, recurring costs, unusual spending, major vendors, AI "
                                         "operating costs. Recommend cost or cash actions. " + (request or "")))
        out["cfo"] = res.output if res.ok else {"error": res.error}
        return out

    async def wf_plan(self, rc: RunCtx, request: str, options: dict) -> dict:
        decision_id = options.get("decision_id")
        deps: dict[str, Any] = {}
        if decision_id:
            with self.sm() as s:
                d = s.get(Decision, decision_id)
                if d is None:
                    raise NotFound(f"decision {decision_id} not found")
                if d.status != DecisionStatus.APPROVED:
                    raise ValidationFailed("Plans are created only from APPROVED decisions.")
                deps["approved_decision"] = decisions.to_dict(d)
                run = s.get(WorkflowRun, d.workflow_run_id) if d.workflow_run_id else None
                if run and run.result and run.result.get("brief"):
                    deps["executive_brief"] = run.result["brief"]
                request = request or d.question
        with self.sm() as s:
            deps["current_plans"] = planning.state(s)
            deps["founder_principles"] = planning.principles(s)
        res = await run_agent(rc, agent_id="strategy", key="plan", schema=PlanOutput, complexity="medium",
                              context_text=self._context(request), deps=deps,
                              objective=("Turn this into a structured plan: one objective, one project, milestones and "
                                         f"tasks with owners, dependencies and completion criteria. {request}"))
        if not res.ok:
            raise AIOSError(f"Planning failed: {res.error}")
        plan = PlanOutput.model_validate({k: v for k, v in res.output.items() if not k.startswith("_")})
        with self.sm() as s:
            created = planning.create_from_plan(s, agent_actor("strategy"), plan, decision_id=decision_id,
                                                workflow_run_id=rc.run_id)
            s.commit()
        rc.progress(f"plan created: project {created['project_id']} ({created['status']}), {len(created['task_ids'])} tasks")
        out = {"plan": plan.model_dump(), "created": created}
        if created.get("approval_id"):
            out["_status"] = RunStatus.AWAITING_APPROVAL.value
        return out

    async def wf_priorities(self, rc: RunCtx, request: str, options: dict) -> dict:
        with self.sm() as s:
            st = planning.state(s)
        res = await run_agent(rc, agent_id="strategy", key="priorities", schema=PrioritiesOutput, complexity="medium",
                              context_text=self._context(request or "priorities"), deps={"planning_state": st},
                              objective=("What matters most right now? Rank what to do next by expected value, what to "
                                         "kill or pause, what is blocked, which decisions wait on the founder, and any "
                                         "contradictory priorities. Use the item ids given."))
        return {"state": st, "priorities": res.output if res.ok else {"error": res.error}}

    async def wf_audit(self, rc: RunCtx, request: str, options: dict) -> dict:
        with self.sm() as s:
            obs = improvements.observations(s)
            s.commit()
        rc.progress(f"audit: collected observations ({len(json.dumps(obs, default=str))} chars)")
        focus = options.get("focus") or request or "the entire AI company"
        obs_text = "MEASURED OBSERVATIONS (the only evidence you may use):\n" + json.dumps(obs, default=str)[:20000]
        tasks = [
            PlannedTask(key="operations", agent="coo", complexity="medium",
                        objective=f"Audit {focus}: workflows, agent duplication, failures, bottlenecks, task flow. "
                                  "Propose improvements only where the observations show a problem."),
            PlannedTask(key="technology", agent="cto", complexity="medium",
                        objective=f"Audit {focus}: architecture, model choice and routing, prompts, context size, "
                                  "security, database quality. Propose improvements backed by the observations."),
            PlannedTask(key="metrics", agent="analytics", complexity="low",
                        objective=f"Audit {focus}: costs by agent/model/workflow, latency, retries, evaluation scores, "
                                  "finance data quality. Propose improvements backed by the observations."),
        ]
        results = await self.execute(rc, tasks, obs_text, schema_for={k: AuditReview for k in ("operations", "technology", "metrics")})
        proposals = []
        for k, r in results.items():
            if r.ok:
                for p in r.output.get("proposals", []):
                    proposals.append({**p, "_from": r.agent_id})
        review = await run_agent(
            rc, agent_id="risk", key="review", schema=RiskAudit, context_text=obs_text,
            deps={"proposals": {"items": proposals}},
            objective="Review these improvement proposals: is each one backed by the observations, is the expected "
                      "impact plausible, is the risk understated, is the rollback real? Name proposals to drop.")
        with self.sm() as s:
            saved = improvements.save_audit(s, scope=options.get("scope", "system"), observations=obs,
                                            reviews={k: r.output for k, r in results.items() if r.ok},
                                            proposals=proposals, risk=review.output if review.ok else None,
                                            workflow_run_id=rc.run_id)
            s.commit()
        return {"observations": obs, "audit_id": saved["audit_id"], "improvements": saved["improvements"],
                "risk_review": review.output if review.ok else {"error": review.error},
                "findings": {k: (r.output or {}).get("findings") for k, r in results.items()}}

    async def wf_improve(self, rc: RunCtx, request: str, options: dict) -> dict:
        with self.sm() as s:
            candidates = improvements.measured_candidates(s)
            s.commit()
        out = await self.wf_audit(rc, request or "measurable improvements only", {**options, "scope": "improve"})
        out["measured_candidates"] = candidates
        return out

    async def wf_test(self, rc: RunCtx, request: str, options: dict) -> dict:
        """TEST → COMPARE for one improvement: benchmark the current setup and the proposed one side by side."""
        from aios.db.models import Experiment, Improvement
        from aios.modules.evaluations import run_benchmark

        imp_id = options.get("improvement_id")
        with self.sm() as s:
            imp = s.get(Improvement, imp_id) if imp_id else None
            if imp is None:
                raise NotFound(f"improvement {imp_id} not found")
            if imp.status.value not in ("PROPOSED", "TESTED"):
                raise ValidationFailed(f"improvement is {imp.status.value}; only PROPOSED or TESTED ones are tested")
            plan = improvements.test_plan_for(s, imp)
            exp = Experiment(hypothesis=imp.expected_impact, metric=imp.metric or "benchmark score and cost",
                             variant_a=plan["baseline"], variant_b=plan["candidate"], status="RUNNING",
                             improvement_id=imp.id, domain="SYSTEM")
            s.add(exp)
            imp.status = ImprovementStatus.TESTING
            s.commit()
            exp_id = exp.id
        b, c = plan["baseline"], plan["candidate"]
        rc.progress(f"test {plan['agent']}: current {b['model']} (prompt v{b['config_version']}) vs proposed "
                    f"{c['model']} (prompt v{c['config_version']}) on the {plan['agent']} benchmark")
        try:
            base = await run_benchmark(self.sm, rc.providers, plan["agent"], plan["baseline"]["model"],
                                       config_version=plan["baseline"]["config_version"], experiment_id=exp_id,
                                       guard=rc.guard, workflow_run_id=rc.run_id)
            rc.progress(f"baseline scored {base['avg_score']:.3f} (${base['total_cost_usd']:.4f})")
            cand = await run_benchmark(self.sm, rc.providers, plan["agent"], plan["candidate"]["model"],
                                       config_version=plan["candidate"]["config_version"], experiment_id=exp_id,
                                       guard=rc.guard, workflow_run_id=rc.run_id)
            rc.progress(f"candidate scored {cand['avg_score']:.3f} (${cand['total_cost_usd']:.4f})")
        except Exception:
            with self.sm() as s:  # leave the improvement testable again; the experiment records the failure
                s.get(Improvement, imp_id).status = ImprovementStatus.PROPOSED
                e = s.get(Experiment, exp_id)
                e.status, e.conclusion = "FAILED", "Test did not finish (see the workflow run error)."
                s.commit()
            raise
        with self.sm() as s:
            out = improvements.record_test(s, s.get(Improvement, imp_id), plan, base, cand, exp_id)
            s.commit()
        return {"test": out}

    async def wf_trends(self, rc: RunCtx, request: str, options: dict) -> dict:
        """Trend intelligence: live research, then the CMO judges each trend on evidence, not popularity."""
        from aios.agents.schemas import TrendReport

        topic = request or "AI, software, and small-business technology"
        context_text = self._context(topic, agent_id="cmo")
        tasks = [
            PlannedTask(key="signals", agent="research", complexity="high",
                        objective=f"Find the most important current trends in: {topic}. For each: what changed, when, "
                                  "measurable signals (adoption, spending, search, funding, regulation), and primary sources. "
                                  "Separate economic evidence from social-media buzz."),
            PlannedTask(key="trends", agent="cmo", depends_on=["signals"], complexity="medium",
                        objective=f"Evaluate the trends found for: {topic}. Judge each on signal, evidence, trajectory, "
                                  "market impact, relevance to this company, business opportunity, risks and confidence. "
                                  "Mark trends that are mostly viral discussion without economic evidence."),
        ]
        results = await self.execute(rc, tasks, context_text, schema_for={"trends": TrendReport})
        out: dict[str, Any] = {"agents": {k: {"agent": r.agent_id, "ok": r.ok, "error": r.error, "run_id": r.run_id}
                                          for k, r in results.items()}}
        if results["signals"].ok:
            out["research"] = results["signals"].output
        if not results["trends"].ok:
            raise AIOSError(f"Trend evaluation failed: {results['trends'].error}")
        report = results["trends"].output
        research_live = bool((out.get("research") or {}).get("live_search_used"))
        if not research_live:  # code-enforced: no live evidence, no high confidence
            for t in report.get("trends", []):
                if t.get("confidence") == "HIGH":
                    t["confidence"] = "MEDIUM"
            report["note"] = "Research had no live web search; confidence capped below HIGH."
        out["trends"] = report
        return out

    async def wf_learn(self, rc: RunCtx, request: str, options: dict) -> dict:
        """After the founder decides: propose INFERRED preferences, link evidence, maybe promote to CONFIRMED."""
        decision_id = options.get("decision_id")
        with self.sm() as s:
            d = s.get(Decision, decision_id) if decision_id else None
            if d is None or d.decision_maker != "founder":
                raise ValidationFailed("learn runs only on decisions the founder made.")
            ddict = decisions.to_dict(d)
            mems = memory.retrieve(s, d.question, limit=30, categories=[MemoryCategory.FOUNDER])
        res = await run_agent(
            rc, agent_id="twin", key="learn", schema=TwinAlignment, complexity="low",
            context_text="FOUNDER MEMORY:\n" + memory.format_for_prompt(mems), deps={"founder_decision": ddict},
            objective=("The founder just made this decision. Which existing memories does it support or contradict "
                       "(aligned_with / conflicts_with, by memory id)? Propose new INFERRED or HYPOTHESIS preferences "
                       "only if this decision is real evidence for them."))
        if not res.ok:
            raise AIOSError(f"Twin learning failed: {res.error}")
        tw = TwinAlignment.model_validate({k: v for k, v in res.output.items() if not k.startswith("_")})
        created, promoted = [], []
        with self.sm() as s:
            twin = agent_actor("twin")
            valid_ids = {m.id for m in s.query(Memory).filter(Memory.status != MemoryStatus.SUPERSEDED)}
            for ref in tw.aligned_with:
                if ref.memory_id in valid_ids:
                    memory.link_evidence(s, ref.memory_id, decision_id, "SUPPORTS", ref.note)
                    if memory.maybe_confirm(s, ref.memory_id):
                        promoted.append(ref.memory_id)
            for ref in tw.conflicts_with:
                if ref.memory_id in valid_ids:
                    memory.link_evidence(s, ref.memory_id, decision_id, "CONTRADICTS", ref.note)
            for inf in tw.proposed_inferences[:5]:
                m = memory.add(s, twin, category=MemoryCategory.FOUNDER, subject=inf.subject, content=inf.content,
                               status=MemoryStatus(inf.status), provenance=Provenance.AGENT_INFERENCE,
                               source_ref=f"decision:{decision_id} — {inf.evidence}",
                               confidence=0.6 if inf.status == "INFERRED" else 0.3)
                memory.link_evidence(s, m.id, decision_id, "SUPPORTS", inf.evidence)
                created.append(m.id)
            s.commit()
        return {"alignment": tw.model_dump(), "memories_created": created, "memories_promoted": promoted}
