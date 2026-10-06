"""Adapters and full-database export/import (the PostgreSQL migration path)."""

from pathlib import Path

import pytest
from sqlalchemy import func, select

from aios.bootstrap import init
from aios.core import audit
from aios.core.actor import FOUNDER
from aios.db.enums import MemoryCategory, MemoryStatus, Provenance
from aios.db.models import Memory
from aios.db.portable import export_db, import_db
from aios.integrations import CsvSource, import_from
from aios.modules import finance, memory, metrics

CSV = Path(__file__).parent / "data" / "transactions.csv"


def test_csv_adapter_goes_through_the_core_path(sm):
    with sm() as s:
        r = import_from(s, FOUNDER, CsvSource(CSV), account_name="Checking")
        s.commit()
        assert r["accepted"] == 23 and r["rejected"] == 2
        assert finance.reconcile(s)["ok"]


async def test_export_import_round_trip(sm, engine, tmp_path):
    await engine.run("ceo", "Analyze whether I should build an AI receptionist for dental offices.")
    with sm() as s:
        finance.import_csv(s, FOUNDER, text=CSV.read_text(), filename="t.csv")
        m = memory.add(s, FOUNDER, category=MemoryCategory.FOUNDER, subject="goal", content="v1",
                       status=MemoryStatus.EXPLICIT, provenance=Provenance.FOUNDER)
        memory.supersede(s, FOUNDER, m.id, new_content="v2", reason="update")  # self-referencing row
        s.commit()
        before = metrics.flows(s)
    src_url = str(sm.kw["bind"].url)
    manifest = export_db(src_url, tmp_path / "export")
    assert manifest["counts"]["audit_log"] > 10

    target = f"sqlite:///{tmp_path / 'copy.db'}"
    result = import_db(target, tmp_path / "export")
    assert result["ok"], result
    sm2 = init(target)
    with sm2() as s:
        assert metrics.flows(s) == before
        old = s.get(Memory, m.id)
        assert old.status == MemoryStatus.SUPERSEDED and old.superseded_by_id
        audit.record(s, who="founder", what="after.import")  # the chain continues after import
        s.commit()
        assert audit.verify_chain(s)["ok"]

    with pytest.raises(ValueError, match="not empty"):
        import_db(target, tmp_path / "export")
