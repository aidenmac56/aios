"""Append-only, hash-chained audit log of consequential actions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.config import redact
from aios.core.util import utcnow
from aios.db.models import AuditLog

GENESIS = "0" * 64


def _sanitize(value: Any) -> Any:
    if value is None:
        return None
    text = json.dumps(value, default=str)
    if len(text) > 20_000:
        text = json.dumps({"truncated": True, "preview": text[:20_000]})
    return json.loads(redact(text))


def _digest(prev_hash: str, row: dict) -> str:
    body = json.dumps(row, sort_keys=True, default=str)
    return hashlib.sha256((prev_hash + body).encode()).hexdigest()


def record(
    session: Session,
    *,
    who: str,
    what: str,
    why: str | None = None,
    input: Any = None,
    output: Any = None,
    tools_used: list[str] | None = None,
    cost_micros: int = 0,
    approval_id: str | None = None,
    result: str | None = "OK",
    error: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
) -> AuditLog:
    last = session.execute(select(AuditLog.hash).order_by(AuditLog.seq.desc()).limit(1)).scalar()
    prev_hash = last or GENESIS
    at = utcnow()
    row = {
        "at": at.isoformat(),
        "who": who,
        "what": what,
        "why": why,
        "input": _sanitize(input),
        "output": _sanitize(output),
        "tools_used": tools_used or [],
        "cost_micros": cost_micros,
        "approval_id": approval_id,
        "result": result,
        "error": redact(error) if error else None,
        "target_type": target_type,
        "target_id": target_id,
    }
    entry = AuditLog(
        at=at,
        who=who,
        what=what,
        why=why,
        input=row["input"],
        output=row["output"],
        tools_used=row["tools_used"],
        cost_micros=cost_micros,
        approval_id=approval_id,
        result=result,
        error=row["error"],
        target_type=target_type,
        target_id=target_id,
        prev_hash=prev_hash,
        hash=_digest(prev_hash, row),
    )
    session.add(entry)
    session.flush()
    return entry


def verify_chain(session: Session) -> dict:
    """Recompute every hash. Returns {"ok": bool, "entries": n, "first_bad_seq": seq|None}."""
    prev = GENESIS
    n = 0
    for e in session.execute(select(AuditLog).order_by(AuditLog.seq)).scalars():
        n += 1
        row = {
            "at": e.at.isoformat(),
            "who": e.who,
            "what": e.what,
            "why": e.why,
            "input": e.input,
            "output": e.output,
            "tools_used": e.tools_used,
            "cost_micros": e.cost_micros,
            "approval_id": e.approval_id,
            "result": e.result,
            "error": e.error,
            "target_type": e.target_type,
            "target_id": e.target_id,
        }
        if e.prev_hash != prev or e.hash != _digest(prev, row):
            return {"ok": False, "entries": n, "first_bad_seq": e.seq}
        prev = e.hash
    return {"ok": True, "entries": n, "first_bad_seq": None}
