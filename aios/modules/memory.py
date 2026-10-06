"""Founder and company memory with provenance.

Rules live here, in code:
- Agents may only write INFERRED or HYPOTHESIS. Only the founder writes EXPLICIT.
- INFERRED → CONFIRMED needs N supporting founder decisions and no contradicting ones; it is logged.
- Corrections supersede; nothing is deleted.
"""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aios.core import audit, events, sysconfig
from aios.core.actor import Actor
from aios.core.errors import NotFound, PermissionDenied, ValidationFailed
from aios.core.permissions import db_write, require
from aios.core.util import utcnow
from aios.db.enums import MemoryCategory, MemoryStatus, Provenance
from aios.db.models import Decision, Founder, Memory, MemoryEvidence

ACTIVE = (MemoryStatus.EXPLICIT, MemoryStatus.CONFIRMED, MemoryStatus.INFERRED, MemoryStatus.HYPOTHESIS)


def get_or_create_founder(session: Session, name: str = "Founder", email: str | None = None,
                          timezone: str = "UTC") -> Founder:
    f = session.execute(select(Founder).limit(1)).scalar_one_or_none()
    if f is None:
        f = Founder(name=name, email=email, timezone=timezone)
        session.add(f)
        session.flush()
    return f


def add(session: Session, actor: Actor, *, category: MemoryCategory, subject: str, content: str,
        status: MemoryStatus, provenance: Provenance, source_ref: str | None = None, confidence: float = 1.0,
        tags: list[str] | None = None) -> Memory:
    if status == MemoryStatus.SUPERSEDED:
        raise ValidationFailed("New memories cannot start SUPERSEDED.")
    if not actor.is_founder:
        require(actor, db_write("memory"), action="write memory")
        if status in (MemoryStatus.EXPLICIT, MemoryStatus.CONFIRMED):
            raise PermissionDenied("Agents may only record INFERRED or HYPOTHESIS memories.", actor=str(actor))
        if provenance == Provenance.FOUNDER:
            raise PermissionDenied("Only the founder can be the provenance FOUNDER.", actor=str(actor))
    elif status == MemoryStatus.CONFIRMED:
        raise ValidationFailed("CONFIRMED is earned through decisions; use EXPLICIT for things you state directly.")
    subject = re.sub(r"[^a-z0-9_]+", "_", subject.lower()).strip("_")[:200] or "note"
    founder = get_or_create_founder(session)
    m = Memory(founder_id=founder.id if category == MemoryCategory.FOUNDER else None, category=category,
               subject=subject, content=content.strip(), status=status, provenance=provenance, source_ref=source_ref,
               confidence=max(0.0, min(1.0, confidence)), created_by=str(actor), tags=tags or [])
    session.add(m)
    session.flush()
    audit.record(session, who=str(actor), what="memory.add", why=source_ref,
                 input={"subject": subject, "status": status.value, "provenance": provenance.value},
                 target_type="memory", target_id=m.id)
    return m


def supersede(session: Session, actor: Actor, memory_id: str, *, new_content: str, reason: str,
              new_status: MemoryStatus | None = None) -> Memory:
    """Replace a memory. The old row becomes SUPERSEDED and points at the new one."""
    old = session.get(Memory, memory_id)
    if old is None:
        raise NotFound(f"memory {memory_id} not found")
    if old.status == MemoryStatus.SUPERSEDED:
        raise ValidationFailed("Memory is already superseded.")
    if not actor.is_founder and old.status in (MemoryStatus.EXPLICIT, MemoryStatus.CONFIRMED):
        raise PermissionDenied("Agents cannot change EXPLICIT or CONFIRMED founder memory.", actor=str(actor))
    status = new_status or (MemoryStatus.EXPLICIT if actor.is_founder else old.status)
    prov = Provenance.FOUNDER if actor.is_founder else Provenance.AGENT_INFERENCE
    new = add(session, actor, category=old.category, subject=old.subject, content=new_content, status=status,
              provenance=prov, source_ref=f"correction of memory:{old.id}: {reason}", tags=old.tags)
    old.status = MemoryStatus.SUPERSEDED
    old.superseded_by_id = new.id
    audit.record(session, who=str(actor), what="memory.supersede", why=reason,
                 input={"old": old.id, "new": new.id}, target_type="memory", target_id=old.id)
    return new


def link_evidence(session: Session, memory_id: str, decision_id: str, kind: str, note: str | None = None) -> None:
    if kind not in ("SUPPORTS", "CONTRADICTS"):
        raise ValidationFailed("kind must be SUPPORTS or CONTRADICTS")
    session.add(MemoryEvidence(memory_id=memory_id, decision_id=decision_id, kind=kind, note=note))
    session.flush()


def maybe_confirm(session: Session, memory_id: str) -> bool:
    """Promote INFERRED → CONFIRMED when founder decisions support it enough and none contradict it."""
    m = session.get(Memory, memory_id)
    if m is None or m.status != MemoryStatus.INFERRED:
        return False
    threshold = int(sysconfig.get(session, "memory.confirm_threshold"))
    rows = session.execute(
        select(MemoryEvidence.kind, func.count()).join(Decision, Decision.id == MemoryEvidence.decision_id)
        .where(MemoryEvidence.memory_id == memory_id, Decision.decision_maker == "founder")
        .group_by(MemoryEvidence.kind)).all()
    counts = dict(rows)
    if counts.get("CONTRADICTS", 0) == 0 and counts.get("SUPPORTS", 0) >= threshold:
        m.status = MemoryStatus.CONFIRMED
        m.last_confirmed_at = utcnow()
        events.emit(session, events.MEMORY_PROMOTED, "system", {"memory_id": m.id, "supports": counts.get("SUPPORTS", 0)})
        audit.record(session, who="system", what="memory.confirmed",
                     why=f"{counts.get('SUPPORTS', 0)} supporting founder decisions, 0 contradicting",
                     target_type="memory", target_id=m.id)
        return True
    return False


_WORD = re.compile(r"[a-z0-9]{3,}")
STOP = {"the", "and", "for", "with", "that", "this", "should", "what", "whether", "build", "into", "from", "have",
        "about", "would", "could", "will", "are", "was", "our", "your", "you", "can", "how", "why", "who"}


def _terms(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in STOP}


def retrieve(session: Session, query: str, *, limit: int = 30, categories: list[MemoryCategory] | None = None) -> list[Memory]:
    """Active memories, ranked: founder EXPLICIT/CONFIRMED first, then keyword overlap."""
    q = select(Memory).where(Memory.status.in_(ACTIVE))
    if categories:
        q = q.where(Memory.category.in_(categories))
    rows = list(session.execute(q).scalars())
    terms = _terms(query)
    status_weight = {MemoryStatus.EXPLICIT: 3.0, MemoryStatus.CONFIRMED: 2.5, MemoryStatus.INFERRED: 1.0,
                     MemoryStatus.HYPOTHESIS: 0.5}

    def score(m: Memory) -> float:
        overlap = len(terms & _terms(f"{m.subject} {m.content} {' '.join(m.tags or [])}"))
        base = status_weight[m.status]
        founder_bonus = 2.0 if m.category == MemoryCategory.FOUNDER else 0.0
        return overlap * 2 + base + founder_bonus

    rows.sort(key=score, reverse=True)
    return rows[:limit]


def format_for_prompt(memories: list[Memory]) -> str:
    if not memories:
        return "(no founder or company memory recorded yet)"
    lines = []
    for m in memories:
        lines.append(f"- [memory:{m.id} | {m.status.value} | {m.provenance.value}] {m.subject}: {m.content}")
    return "\n".join(lines)


def conflicts(session: Session) -> list[dict]:
    """Active memories that share a subject but say different things."""
    rows = session.execute(select(Memory).where(Memory.status.in_(ACTIVE))).scalars().all()
    by_subject: dict[str, list[Memory]] = {}
    for m in rows:
        by_subject.setdefault(m.subject, []).append(m)
    out = []
    for subject, ms in by_subject.items():
        if len(ms) > 1 and len({m.content.strip().lower() for m in ms}) > 1:
            out.append({"subject": subject, "memories": [{"id": m.id, "status": m.status.value, "content": m.content} for m in ms]})
    return out


def to_dict(m: Memory) -> dict:
    return {"id": m.id, "category": m.category.value, "subject": m.subject, "content": m.content,
            "status": m.status.value, "provenance": m.provenance.value, "source_ref": m.source_ref,
            "confidence": m.confidence, "created_by": m.created_by, "superseded_by_id": m.superseded_by_id,
            "tags": m.tags, "created_at": m.created_at.isoformat() if m.created_at else None,
            "last_confirmed_at": m.last_confirmed_at.isoformat() if m.last_confirmed_at else None}
