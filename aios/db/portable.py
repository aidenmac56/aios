"""Export the whole database to JSON files and import it into a new database (e.g. SQLite → PostgreSQL).

Ids, timestamps and the audit-log hash chain are preserved. Import only runs into an empty, freshly
migrated database, and verifies row counts and the audit chain afterwards.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from enum import Enum
from pathlib import Path

from sqlalchemy import Date, DateTime, func, select, text
from sqlalchemy.engine import Engine

from aios.db import models  # noqa: F401  (registers tables)
from aios.db.base import Base, get_engine
from aios.db.migrate import upgrade

FORMAT = "aios-export-v1"


def _tables():
    return list(Base.metadata.sorted_tables)


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Enum):
        return v.value
    return v


def export_db(url: str, out_dir: str | Path) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    engine = get_engine(url)
    counts = {}
    with engine.connect() as conn:
        for t in _tables():
            rows = [{k: _plain(v) for k, v in r._mapping.items()} for r in conn.execute(t.select())]
            (out / f"{t.name}.json").write_text(json.dumps(rows, default=str))
            counts[t.name] = len(rows)
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    manifest = {"format": FORMAT, "alembic_revision": rev, "exported_at": datetime.now().isoformat(), "counts": counts}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def _convert(table, row: dict) -> dict:
    out = {}
    for col in table.columns:
        if col.name not in row:
            continue
        v = row[col.name]
        if v is not None and isinstance(col.type, DateTime):
            v = datetime.fromisoformat(v)
        elif v is not None and isinstance(col.type, Date):
            v = date.fromisoformat(v)
        out[col.name] = v
    return out


def import_db(url: str, in_dir: str | Path) -> dict:
    src = Path(in_dir)
    manifest = json.loads((src / "manifest.json").read_text())
    if manifest.get("format") != FORMAT:
        raise ValueError(f"Not an AIOS export (format {manifest.get('format')!r}).")
    upgrade(url)
    engine: Engine = get_engine(url)
    with engine.begin() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if rev != manifest["alembic_revision"]:
            raise ValueError(f"Schema mismatch: export is at {manifest['alembic_revision']}, target at {rev}. "
                             "Run the same code version on both sides.")
        for t in _tables():
            if conn.execute(select(func.count()).select_from(t)).scalar():
                raise ValueError(f"Target database is not empty (table {t.name}). Import needs a fresh database.")
        for t in _tables():
            path = src / f"{t.name}.json"
            rows = json.loads(path.read_text()) if path.exists() else []
            if not rows:
                continue
            self_refs = [fk.parent.name for fk in t.foreign_keys if fk.column.table is t]
            converted = [_convert(t, r) for r in rows]
            first_pass = [{**r, **{c: None for c in self_refs}} for r in converted]
            conn.execute(t.insert(), first_pass)
            for r in converted:  # restore self-references once every row exists
                fixes = {c: r[c] for c in self_refs if r.get(c) is not None}
                if fixes:
                    pk = list(t.primary_key.columns)[0]
                    conn.execute(t.update().where(pk == r[pk.name]).values(**fixes))
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT setval(pg_get_serial_sequence('audit_log','seq'), "
                              "COALESCE((SELECT MAX(seq) FROM audit_log), 1))"))
    counts = {}
    with engine.connect() as conn:
        for t in _tables():
            counts[t.name] = conn.execute(select(func.count()).select_from(t)).scalar()
    mismatched = {k: (v, counts.get(k)) for k, v in manifest["counts"].items() if counts.get(k) != v}
    from aios.core.audit import verify_chain
    from aios.db.base import session_factory

    with session_factory(url)() as s:
        chain = verify_chain(s)
    return {"counts": counts, "mismatched": mismatched, "audit_chain": chain,
            "ok": not mismatched and chain["ok"]}
