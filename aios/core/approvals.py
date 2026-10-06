"""Approval gates. Only the founder can approve or reject.

An approval's payload names a handler (static code, registered at startup). Approving runs that
handler once, inside the same transaction, and may return a `follow_up` the caller can run (for
example: build the project plan for an approved decision). Nothing listens in the background.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from aios.core import audit, events
from aios.core.actor import Actor
from aios.core.errors import NotFound, PermissionDenied, ValidationFailed
from aios.core.util import utcnow
from aios.db.enums import ApprovalStatus, ApprovalType
from aios.db.models import Approval

Handler = Callable[[Session, Approval, Actor], dict[str, Any]]
_approve_handlers: dict[str, Handler] = {}
_reject_handlers: dict[str, Handler] = {}


def register(kind: str, on_approve: Handler, on_reject: Handler | None = None) -> None:
    _approve_handlers[kind] = on_approve
    if on_reject:
        _reject_handlers[kind] = on_reject


def request(
    session: Session,
    *,
    action: str,
    action_type: ApprovalType,
    requested_by: str,
    reason: str,
    handler: str | None = None,
    payload: dict[str, Any] | None = None,
    expected_effect: str | None = None,
    risks: list[str] | None = None,
    cost_cents: int | None = None,
    decision_id: str | None = None,
    workflow_run_id: str | None = None,
) -> Approval:
    if handler and handler not in _approve_handlers:
        raise ValidationFailed(f"Unknown approval handler '{handler}'")
    appr = Approval(
        action=action,
        action_type=action_type,
        requested_by=requested_by,
        reason=reason,
        expected_effect=expected_effect,
        risks=risks or [],
        cost_cents=cost_cents,
        payload={"handler": handler, **(payload or {})},
        decision_id=decision_id,
        workflow_run_id=workflow_run_id,
    )
    session.add(appr)
    session.flush()
    events.emit(session, events.APPROVAL_REQUESTED, requested_by,
                {"approval_id": appr.id, "action": action, "type": action_type.value}, workflow_run_id)
    audit.record(session, who=requested_by, what="approval.requested", why=reason,
                 input={"action": action, "type": action_type.value, "cost_cents": cost_cents},
                 target_type="approval", target_id=appr.id)
    return appr


def _load_pending(session: Session, approval_id: str, actor: Actor) -> Approval:
    if not actor.is_founder:
        raise PermissionDenied("Only the founder can decide approvals.", actor=str(actor))
    appr = session.get(Approval, approval_id)
    if appr is None:
        raise NotFound(f"approval {approval_id} not found")
    if appr.status != ApprovalStatus.PENDING:
        raise ValidationFailed(f"approval {approval_id} is already {appr.status.value}")
    return appr


def approve(session: Session, approval_id: str, actor: Actor, note: str | None = None) -> dict[str, Any]:
    appr = _load_pending(session, approval_id, actor)
    appr.status = ApprovalStatus.APPROVED
    appr.approver = str(actor)
    appr.decided_at = utcnow()
    appr.decision_note = note
    result: dict[str, Any] = {}
    kind = (appr.payload or {}).get("handler")
    if kind:
        result = _approve_handlers[kind](session, appr, actor) or {}
    audit.record(session, who=str(actor), what="approval.approved", why=note, approval_id=appr.id,
                 input={"action": appr.action}, output=result, target_type="approval", target_id=appr.id)
    return {"approval_id": appr.id, "status": appr.status.value, **result}


def reject(session: Session, approval_id: str, actor: Actor, note: str | None = None) -> dict[str, Any]:
    appr = _load_pending(session, approval_id, actor)
    appr.status = ApprovalStatus.REJECTED
    appr.approver = str(actor)
    appr.decided_at = utcnow()
    appr.decision_note = note
    result: dict[str, Any] = {}
    kind = (appr.payload or {}).get("handler")
    if kind and kind in _reject_handlers:
        result = _reject_handlers[kind](session, appr, actor) or {}
    audit.record(session, who=str(actor), what="approval.rejected", why=note, approval_id=appr.id,
                 input={"action": appr.action}, output=result, target_type="approval", target_id=appr.id)
    return {"approval_id": appr.id, "status": appr.status.value, **result}
