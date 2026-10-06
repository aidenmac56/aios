"""Load a founder-reviewed seed file. Idempotent: existing identical memories are skipped."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.core import audit
from aios.core.actor import FOUNDER
from aios.db.enums import DecisionStatus, MemoryCategory, MemoryStatus, Provenance
from aios.db.models import Company, Decision, Memory
from aios.modules import memory


def load_seed(session: Session, path: Path) -> int:
    data = json.loads(Path(path).read_text())
    n = 0
    f = data.get("founder") or {}
    founder = memory.get_or_create_founder(session, f.get("name", "Founder"), f.get("email"), f.get("timezone", "UTC"))
    founder.name = f.get("name", founder.name)
    founder.timezone = f.get("timezone", founder.timezone)
    c = data.get("company")
    if c and not session.execute(select(Company).where(Company.name == c["name"])).first():
        session.add(Company(**{k: c.get(k) for k in ("name", "vision", "mission", "strategy", "business_model",
                                                     "products", "customers")}))
        n += 1
    for m in data.get("memories", []):
        exists = session.execute(select(Memory.id).where(Memory.subject == m["subject"],
                                                         Memory.content == m["content"])).first()
        if exists:
            continue
        memory.add(session, FOUNDER, category=MemoryCategory(m["category"]), subject=m["subject"], content=m["content"],
                   status=MemoryStatus(m["status"]), provenance=Provenance(m.get("provenance", "FOUNDER")),
                   source_ref=m.get("source_ref"), tags=m.get("tags", []),
                   confidence=1.0 if m["status"] == "EXPLICIT" else 0.5)
        n += 1
    for d in data.get("decisions", []):
        if session.execute(select(Decision.id).where(Decision.question == d["question"])).first():
            continue
        session.add(Decision(question=d["question"], recommendation=d["recommendation"], reasoning=d.get("reasoning"),
                             decision_type=d.get("decision_type", "GENERAL"), decision_maker=d.get("maker"),
                             status=DecisionStatus.PROPOSED,
                             context="Made on the founder's behalf when he asked Claude to decide where to start. "
                                     "Not yet confirmed by him."))
        n += 1
    session.flush()
    audit.record(session, who="founder", what="seed.load", why=str(path), output={"records": n})
    return n
