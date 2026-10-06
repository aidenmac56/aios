"""API smoke + behavior tests (no model calls)."""

import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AIOS_API_TOKEN", raising=False)
    from aios import config

    config.get_settings.cache_clear()
    monkeypatch.setattr(config, "ROOT", tmp_path)  # no stray .env from the repo
    import aios.api.app as appmod

    importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        yield c
    config.get_settings.cache_clear()


def test_health_and_empty_state(client):
    assert client.get("/api/health").json()["llm_credentials"] is False
    st = client.get("/api/status").json()
    assert st["projects"] == [] and st["finance"]["has_data"] is False
    agents = client.get("/api/agents").json()
    assert {a["id"] for a in agents} >= {"ceo", "cfo", "cto", "coo", "cmo", "research", "strategy", "product", "risk",
                                         "analytics", "twin"}


def test_llm_command_without_key_is_a_clear_error(client):
    r = client.post("/api/commands/ceo", json={"request": "anything"})
    assert r.status_code == 400 and r.json()["code"] == "missing_credentials"


def test_finance_import_and_summary_without_model(client):
    csv = (Path(__file__).parent / "data" / "transactions.csv").read_bytes()
    r = client.post("/api/finance/import", files={"file": ("t.csv", csv, "text/csv")}, data={"account": "Checking"})
    assert r.json()["accepted"] == 23
    s = client.get("/api/finance/summary").json()
    assert s["totals"]["revenue"]["cents"] == 450000 and s["reconciliation"]["ok"]


def test_memory_founder_writes_explicit_and_corrects(client):
    m = client.post("/api/memory", json={"subject": "goal", "content": "Book 5 calls this month"}).json()
    assert m["status"] == "EXPLICIT" and m["provenance"] == "FOUNDER"
    new = client.post(f"/api/memory/{m['id']}/correct", json={"content": "Book 10 calls this month"}).json()
    mems = client.get("/api/memory?include_superseded=true").json()["memories"]
    old = next(x for x in mems if x["id"] == m["id"])
    assert old["status"] == "SUPERSEDED" and old["superseded_by_id"] == new["id"]


def test_token_required_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite:///{tmp_path / 'api2.db'}")
    monkeypatch.setenv("AIOS_API_TOKEN", "secret-token")
    from aios import config

    config.get_settings.cache_clear()
    import aios.api.app as appmod

    importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/api/status", headers={"Authorization": "Bearer secret-token"}).status_code == 200
    config.get_settings.cache_clear()


def test_settings_change_is_audited(client):
    r = client.put("/api/settings/budget.daily_limit_usd", json={"value": 5, "why": "tighter"})
    assert r.json()["value"] == 5
    log = client.get("/api/audit-log").json()
    assert any(e["what"] == "config.set" for e in log)
    assert client.get("/api/audit-log/verify").json()["ok"]
