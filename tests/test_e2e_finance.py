"""REQUIRED TEST 3: import transactions → validate, categorize, compute, reconcile; AI costs separate."""

from datetime import date
from pathlib import Path

from aios.core.actor import FOUNDER, agent
from aios.core.errors import PermissionDenied
from aios.db.models import Account
from aios.modules import finance, metrics

CSV = (Path(__file__).parent / "data" / "transactions.csv").read_text()
TODAY = date(2026, 10, 5)


def test_import_and_metrics(sm):
    with sm() as s:
        r = finance.import_csv(s, FOUNDER, text=CSV, filename="transactions.csv", account_name="Checking")
        s.commit()
    assert r["accepted"] == 23 and r["rejected"] == 2 and r["duplicates"] == 0
    assert {e["line"] for e in r["errors"]} == {25, 26}

    with sm() as s:
        f = metrics.flows(s)
        assert f == {"revenue": 4500_00, "other_inflows": 15_00, "expenses": 1154_00, "net_cash_flow": 3361_00}
        b = metrics.burn(s, today=TODAY)
        assert b["months"] == ["2026-07", "2026-08", "2026-09"]
        assert b["gross_burn_monthly"] == 368_00
        assert b["net_burn_monthly"] == -241100 // 3  # cash-flow positive
        assert metrics.cash_balance(s)["cash_balance"] is None  # unknown until the founder gives an opening balance
        acct = s.query(Account).one()
        acct.opening_balance_cents, acct.opening_balance_date = 2000_00, date(2026, 5, 31)
        s.commit()
    with sm() as s:
        assert metrics.cash_balance(s)["cash_balance"] == 2000_00 + 3361_00 - 500_00  # transfer leaves the account
        rw = metrics.runway(s, today=TODAY)
        assert rw["runway_months"] is None and "Not burning" in rw["note"]
        summ = finance.summary(s, today=TODAY)
        assert summ["ai"]["vendor_spend_bank"]["cents"] == 204_00  # Anthropic + OpenAI + ElevenLabs
        assert summ["recurring"]["monthly_cents"] == 72_00
        assert {i["name"] for i in summ["recurring"]["items"]} == {"Anthropic Api", "Openai Chatgpt Plus", "Notion Labs", "Elevenlabs"}
        assert summ["anomalies"][0]["description"] == "Facebook Ads campaign"
        assert summ["major_vendors"][0]["vendor"] == "Facebook Ads Campaign"
        assert summ["not_actual"]["cents"] == -10_00  # PENDING excluded everywhere
        assert finance.reconcile(s)["ok"]


def test_reimport_is_idempotent_but_keeps_real_repeats(sm):
    with sm() as s:
        finance.import_csv(s, FOUNDER, text=CSV, filename="a.csv")
        again = finance.import_csv(s, FOUNDER, text=CSV, filename="a.csv")
        s.commit()
        assert again["accepted"] == 0 and again["duplicates"] == 23
        coffee = [c for c in finance.by_category(s) if c["category"] == "uncategorized"]
        assert coffee[0]["count"] == 2  # two identical coffees on the same day are both real


def test_agents_cannot_import_or_move_money(sm):
    with sm() as s:
        try:
            finance.import_csv(s, agent("cmo"), text=CSV, filename="x.csv")
            raise AssertionError("cmo should not write finance records")
        except PermissionDenied:
            pass


async def test_finance_workflow_cfo_interprets_computed_numbers(sm, engine, provider):
    with sm() as s:
        finance.import_csv(s, FOUNDER, text=CSV, filename="t.csv")
        s.commit()
    res = await engine.run("finance", "How are we doing?")
    assert res["status"] == "COMPLETED", res
    assert res["reconciliation"]["ok"]
    assert res["cfo"]["summary"]
    prompt = provider.requests[-1].messages[0]["content"]
    assert "computed:revenue = $4,500.00" in prompt  # the CFO receives code-computed values, labeled
    # the system's own AI cost is tracked separately from bank data
    with sm() as s:
        assert finance.summary(s)["ai"]["system_operating_cost"]["calls"] >= 1


def test_unit_economics_math():
    ue = finance.unit_economics({"price_per_customer_monthly_usd": 100, "gross_margin_pct": 50, "cac_usd": 150,
                                 "monthly_churn_pct": 5, "fixed_costs_monthly_usd": 500, "startup_costs_usd": 0,
                                 "new_customers_per_month": 5})
    assert ue["contribution_per_customer_monthly_usd"] == 50
    assert ue["ltv_usd"] == 1000 and ue["ltv_to_cac"] == 6.67
    assert ue["cac_payback_months"] == 3.0 and ue["breakeven_customers"] == 10
    # customers: 5 → 9.75 → 14.26; contribution covers $500 fixed costs in month 3
    assert ue["months_to_operating_breakeven"] == 3
