"""Internal events. Recorded for history and future automation; they never start work on their own.

`subscribe` exists so a future scheduler can listen, but only *observers* may be registered:
an observer receives a copy of the event and cannot touch the session or launch workflows.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from aios.db.models import EventRecord

log = logging.getLogger("aios.events")

TASK_CREATED = "TASK_CREATED"
TASK_COMPLETED = "TASK_COMPLETED"
RESEARCH_COMPLETED = "RESEARCH_COMPLETED"
DECISION_CREATED = "DECISION_CREATED"
DECISION_APPROVED = "DECISION_APPROVED"
DECISION_REJECTED = "DECISION_REJECTED"
EXPENSE_ADDED = "EXPENSE_ADDED"
REVENUE_ADDED = "REVENUE_ADDED"
PROJECT_CREATED = "PROJECT_CREATED"
PROJECT_BLOCKED = "PROJECT_BLOCKED"
AGENT_FAILED = "AGENT_FAILED"
AUDIT_COMPLETED = "AUDIT_COMPLETED"
IMPROVEMENT_PROPOSED = "IMPROVEMENT_PROPOSED"
WORKFLOW_STARTED = "WORKFLOW_STARTED"
WORKFLOW_FINISHED = "WORKFLOW_FINISHED"
BUDGET_STOP = "BUDGET_STOP"
MEMORY_PROMOTED = "MEMORY_PROMOTED"
APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
FINANCE_IMPORTED = "FINANCE_IMPORTED"

_observers: list[Callable[[dict], None]] = []


def subscribe(observer: Callable[[dict], None]) -> None:
    """Register a read-only observer (e.g. a log shipper). Observers get a dict copy."""
    _observers.append(observer)


def emit(session: Session, type: str, actor: str, payload: dict[str, Any] | None = None,
         workflow_run_id: str | None = None) -> EventRecord:
    ev = EventRecord(type=type, actor=actor, payload=payload or {}, workflow_run_id=workflow_run_id)
    session.add(ev)
    session.flush()
    snapshot = {"id": ev.id, "type": type, "actor": actor, "payload": dict(ev.payload),
                "workflow_run_id": workflow_run_id}
    for obs in list(_observers):
        try:
            obs(snapshot)
        except Exception:  # an observer must never break the action that emitted the event
            log.exception("event observer failed")
    return ev
