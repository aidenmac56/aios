"""Decision intelligence: question, options, recommendation, final decision, evidence, outcome."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.agents.schemas import ExecutiveBrief
from aios.core import approvals, audit, events
from aios.core.actor import Actor
from aios.core.errors import NotFound, ValidationFailed
from aios.core.permissions import db_write, require
from aios.core.util import utcnow
from aios.db.enums import ApprovalType, DecisionStatus
from aios.db.models import Approval, Decision, DecisionOption
from aios.modules.memory import _terms

BUILD_VERDICTS = {"BUILD", "PROCEED"}


def create_from_brief(session: Session, actor: Actor, brief: ExecutiveBrief, *, question: str,
                      context: str | None = None, workflow_run_id: str | None = None) -> tuple[Decision, Approval | None]:
    require(actor, db_write("decisions"), action="record decision")
    d = Decision(
        question=question, context=context, recommendation=f"{brief.verdict}: {brief.recommended_action}",
        reasoning="\n".join(brief.why), evidence=[e.model_dump() for e in brief.evidence],
        assumptions=[], confidence=brief.confidence, expected_result=brief.upside,
        status=DecisionStatus.PENDING_APPROVAL if brief.requires_approval else DecisionStatus.PROPOSED,
        reversibility=brief.reversibility, decision_type=brief.decision_type, workflow_run_id=workflow_run_id)
    session.add(d)
    session.flush()
    for o in brief.options:
        session.add(DecisionOption(decision_id=d.id, label=o.label, description=o.description, pros=o.pros, cons=o.cons,
                                   expected_value=o.expected_value, risk=o.risk, recommended=o.recommended))
    events.emit(session, events.DECISION_CREATED, str(actor), {"decision_id": d.id, "verdict": brief.verdict}, workflow_run_id)
    appr = None
    if brief.requires_approval:
        cost = sum(c.high_usd for c in brief.costs if c.recurring == "ONE_TIME") + \
            sum(c.high_usd * 12 for c in brief.costs if c.recurring == "MONTHLY") + \
            sum(c.high_usd for c in brief.costs if c.recurring == "ANNUAL")
        appr = approvals.request(
            session, action=f"Decide: {question}", action_type=ApprovalType.DECISION, requested_by=str(actor),
            reason=f"Recommendation: {brief.verdict} — {brief.recommended_action}",
            expected_effect=brief.upside, risks=[r.risk for r in brief.risks][:8],
            cost_cents=int(cost * 100) if cost else None, handler="decision.approve",
            payload={"decision_id": d.id, "verdict": brief.verdict}, decision_id=d.id, workflow_run_id=workflow_run_id)
    audit.record(session, who=str(actor), what="decision.create", why=question,
                 output={"decision_id": d.id, "verdict": brief.verdict, "requires_approval": brief.requires_approval},
                 target_type="decision", target_id=d.id)
    return d, appr


def on_approved(session: Session, approval: Approval, actor: Actor) -> dict:
    d = session.get(Decision, approval.payload["decision_id"])
    if d is None:
        raise NotFound("decision not found")
    d.status = DecisionStatus.APPROVED
    d.final_decision = approval.decision_note or d.recommendation
    d.decision_maker = "founder"
    d.decided_at = utcnow()
    events.emit(session, events.DECISION_APPROVED, str(actor), {"decision_id": d.id}, d.workflow_run_id)
    follow = [{"workflow": "learn", "decision_id": d.id}]
    verdict = (approval.payload or {}).get("verdict", "")
    if verdict in BUILD_VERDICTS or d.decision_type == "BUILD":
        follow.insert(0, {"workflow": "plan", "decision_id": d.id})
    return {"decision_id": d.id, "decision_status": d.status.value, "follow_up": follow}


def on_rejected(session: Session, approval: Approval, actor: Actor) -> dict:
    d = session.get(Decision, approval.payload["decision_id"])
    if d is None:
        raise NotFound("decision not found")
    d.status = DecisionStatus.REJECTED
    d.final_decision = f"Rejected. {approval.decision_note or ''}".strip()
    d.decision_maker = "founder"
    d.decided_at = utcnow()
    events.emit(session, events.DECISION_REJECTED, str(actor), {"decision_id": d.id}, d.workflow_run_id)
    return {"decision_id": d.id, "decision_status": d.status.value,
            "follow_up": [{"workflow": "learn", "decision_id": d.id}]}


def record_outcome(session: Session, actor: Actor, decision_id: str, *, actual_result: str, assessment: str,
                   why: str) -> Decision:
    if assessment not in ("GOOD", "MIXED", "POOR"):
        raise ValidationFailed("assessment must be GOOD, MIXED or POOR")
    require(actor, db_write("decisions"), action="record outcome")
    d = session.get(Decision, decision_id)
    if d is None:
        raise NotFound(f"decision {decision_id} not found")
    d.actual_result, d.outcome_assessment, d.outcome_why = actual_result, assessment, why
    d.outcome_recorded_at = utcnow()
    audit.record(session, who=str(actor), what="decision.outcome", why=why,
                 input={"expected": d.expected_result, "actual": actual_result, "assessment": assessment},
                 target_type="decision", target_id=d.id)
    return d


def relevant_history(session: Session, text: str, *, decision_type: str | None = None, limit: int = 6) -> list[Decision]:
    q = select(Decision).where(Decision.status.in_([DecisionStatus.APPROVED, DecisionStatus.REJECTED]))
    if decision_type:
        q = q.where(Decision.decision_type == decision_type)
    terms = _terms(text)
    rows = list(session.execute(q).scalars())
    rows.sort(key=lambda d: (len(terms & _terms(d.question + " " + (d.recommendation or ""))),
                             d.outcome_assessment is not None), reverse=True)
    return rows[:limit]


def brief_line(d: Decision) -> str:
    out = f"[decision:{d.id} | {d.status.value} | type {d.decision_type}] Q: {d.question} → {d.final_decision or d.recommendation}"
    if d.outcome_assessment:
        out += f" | expected: {d.expected_result} | actual: {d.actual_result} | outcome {d.outcome_assessment}: {d.outcome_why}"
    return out


def to_dict(d: Decision) -> dict:
    return {"id": d.id, "question": d.question, "recommendation": d.recommendation, "final_decision": d.final_decision,
            "reasoning": d.reasoning, "evidence": d.evidence, "confidence": d.confidence, "status": d.status.value,
            "decision_type": d.decision_type, "reversibility": d.reversibility, "decision_maker": d.decision_maker,
            "expected_result": d.expected_result, "actual_result": d.actual_result,
            "outcome_assessment": d.outcome_assessment, "outcome_why": d.outcome_why,
            "workflow_run_id": d.workflow_run_id, "created_at": d.created_at.isoformat(),
            "decided_at": d.decided_at.isoformat() if d.decided_at else None,
            "options": [{"label": o.label, "description": o.description, "pros": o.pros, "cons": o.cons,
                         "expected_value": o.expected_value, "risk": o.risk, "recommended": o.recommended}
                        for o in d.options]}
