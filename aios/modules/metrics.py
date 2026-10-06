"""The metric registry: one definition per metric. Every component computes metrics through here.

Values are integer cents unless the unit says otherwise. Only ACTUAL transactions count toward
actual metrics; FORECAST/ESTIMATE values live in `forecasts` and are never summed with actuals.
Transfers between the founder's own accounts are excluded from revenue and expenses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from aios.db.enums import TxnStatus
from aios.db.models import Account, MetricDefinition, ModelUsage, Transaction


@dataclass(frozen=True)
class Metric:
    key: str
    name: str
    formula: str
    unit: str
    description: str


REGISTRY: dict[str, Metric] = {m.key: m for m in [
    Metric("revenue", "Revenue", "SUM(amount) WHERE status=ACTUAL AND is_revenue AND NOT is_transfer AND amount>0",
           "cents", "Money earned from customers in the period."),
    Metric("other_inflows", "Other inflows", "SUM(amount) WHERE status=ACTUAL AND NOT is_revenue AND NOT is_transfer AND amount>0",
           "cents", "Refunds, reimbursements and other non-revenue money in."),
    Metric("expenses", "Expenses", "-SUM(amount) WHERE status=ACTUAL AND NOT is_transfer AND amount<0",
           "cents", "All money out except transfers between own accounts, as a positive number."),
    Metric("net_cash_flow", "Net cash flow", "revenue + other_inflows - expenses", "cents",
           "Change in cash from operations in the period."),
    Metric("gross_burn_monthly", "Gross burn (monthly)", "AVG over last N complete months of expenses", "cents",
           "Average monthly spend."),
    Metric("net_burn_monthly", "Net burn (monthly)", "AVG over last N complete months of (expenses - revenue - other_inflows)",
           "cents", "Average monthly cash lost. Zero or negative means cash-flow positive."),
    Metric("cash_balance", "Cash balance", "SUM(account.opening_balance) + SUM(ACTUAL amount since opening date)", "cents",
           "Known only when every account has a founder-provided opening balance."),
    Metric("runway_months", "Runway", "cash_balance / net_burn_monthly (only when net burn > 0)", "months",
           "Months until cash runs out at the current net burn."),
    Metric("gross_margin_pct", "Gross margin", "(revenue - cogs) / revenue * 100, cogs = expenses in finance.cogs_categories",
           "percent", "Undefined until COGS categories are configured and there is revenue."),
    Metric("recurring_costs_monthly", "Recurring costs (monthly)", "SUM(monthly-equivalent amount) of active detected or founder subscriptions",
           "cents", "Costs that repeat every month."),
    Metric("ai_operating_cost", "AI operating cost (system)", "SUM(model_usage.estimated_cost) in period", "micro_usd",
           "What running this AI company cost in model and tool usage. Estimated from list prices."),
    Metric("ai_vendor_spend", "AI vendor spend (bank)", "expenses WHERE category='ai_tools'", "cents",
           "Money actually paid to AI vendors according to imported transactions."),
]}


def sync_registry(session: Session) -> None:
    for m in REGISTRY.values():
        row = session.get(MetricDefinition, m.key)
        if row is None:
            session.add(MetricDefinition(key=m.key, name=m.name, formula=m.formula, unit=m.unit, description=m.description))
        else:
            row.name, row.formula, row.unit, row.description = m.name, m.formula, m.unit, m.description
    session.flush()


def _period(q, start: date | None, end: date | None):
    if start:
        q = q.where(Transaction.txn_date >= start)
    if end:
        q = q.where(Transaction.txn_date <= end)
    return q


def flows(session: Session, start: date | None = None, end: date | None = None) -> dict[str, int]:
    """revenue, other_inflows, expenses, net_cash_flow for a period — the only implementation."""
    actual = and_(Transaction.status == TxnStatus.ACTUAL, Transaction.is_transfer.is_(False))
    q = select(
        func.coalesce(func.sum(case((and_(actual, Transaction.is_revenue.is_(True), Transaction.amount_cents > 0),
                                     Transaction.amount_cents), else_=0)), 0),
        func.coalesce(func.sum(case((and_(actual, Transaction.is_revenue.is_(False), Transaction.amount_cents > 0),
                                     Transaction.amount_cents), else_=0)), 0),
        func.coalesce(func.sum(case((and_(actual, Transaction.amount_cents < 0), -Transaction.amount_cents), else_=0)), 0),
    )
    rev, other, exp = session.execute(_period(q, start, end)).one()
    rev, other, exp = int(rev), int(other), int(exp)
    return {"revenue": rev, "other_inflows": other, "expenses": exp, "net_cash_flow": rev + other - exp}


def monthly(session: Session) -> list[dict]:
    """Per calendar month flows, oldest first."""
    rows = session.execute(select(func.min(Transaction.txn_date), func.max(Transaction.txn_date))
                           .where(Transaction.status == TxnStatus.ACTUAL)).one()
    if rows[0] is None:
        return []
    first, last = rows
    out = []
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        start = date(y, m, 1)
        end = date(y + (m == 12), (m % 12) + 1, 1)
        f = flows(session, start, date.fromordinal(end.toordinal() - 1))
        out.append({"month": f"{y:04d}-{m:02d}", **f})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def burn(session: Session, months: int = 3, today: date | None = None) -> dict:
    """Burn over the last `months` complete calendar months that have data."""
    today = today or date.today()
    current = f"{today.year:04d}-{today.month:02d}"
    series = [m for m in monthly(session) if m["month"] < current]
    window = series[-months:]
    if not window:
        return {"gross_burn_monthly": None, "net_burn_monthly": None, "months_used": 0,
                "note": "No complete months of ACTUAL transactions yet."}
    n = len(window)
    gross = sum(m["expenses"] for m in window) // n
    net = sum(m["expenses"] - m["revenue"] - m["other_inflows"] for m in window) // n
    return {"gross_burn_monthly": gross, "net_burn_monthly": net, "months_used": n,
            "months": [m["month"] for m in window]}


def cash_balance(session: Session) -> dict:
    accounts = session.execute(select(Account)).scalars().all()
    if not accounts:
        return {"cash_balance": None, "note": "No accounts recorded."}
    missing = [a.name for a in accounts if a.opening_balance_cents is None or a.opening_balance_date is None]
    if missing:
        return {"cash_balance": None, "note": f"Opening balance unknown for: {', '.join(missing)}."}
    total = 0
    for a in accounts:
        moved = session.execute(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.account_id == a.id, Transaction.status == TxnStatus.ACTUAL,
            Transaction.txn_date > a.opening_balance_date)).scalar()
        total += a.opening_balance_cents + int(moved)
    return {"cash_balance": total, "note": None}


def runway(session: Session, today: date | None = None) -> dict:
    b = burn(session, today=today)
    c = cash_balance(session)
    if c["cash_balance"] is None:
        return {"runway_months": None, "note": c["note"]}
    if b["net_burn_monthly"] is None:
        return {"runway_months": None, "note": b["note"]}
    if b["net_burn_monthly"] <= 0:
        return {"runway_months": None, "note": "Not burning cash (cash-flow positive) over the measured months."}
    return {"runway_months": round(c["cash_balance"] / b["net_burn_monthly"], 1), "note": None}


def gross_margin(session: Session, cogs_categories: list[str], start: date | None = None, end: date | None = None) -> dict:
    f = flows(session, start, end)
    if not cogs_categories:
        return {"gross_margin_pct": None, "note": "No COGS categories configured (finance.cogs_categories)."}
    if f["revenue"] <= 0:
        return {"gross_margin_pct": None, "note": "No revenue in period."}
    q = select(func.coalesce(func.sum(-Transaction.amount_cents), 0)).where(
        Transaction.status == TxnStatus.ACTUAL, Transaction.is_transfer.is_(False), Transaction.amount_cents < 0,
        Transaction.category.in_(cogs_categories))
    cogs = int(session.execute(_period(q, start, end)).scalar())
    return {"gross_margin_pct": round((f["revenue"] - cogs) / f["revenue"] * 100, 1), "cogs": cogs, "note": None}


def ai_operating_cost(session: Session, start=None, end=None) -> dict:
    q = select(func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0),
               func.coalesce(func.sum(ModelUsage.actual_cost_micros), 0), func.count())
    if start:
        q = q.where(ModelUsage.created_at >= start)
    if end:
        q = q.where(ModelUsage.created_at <= end)
    est, act, n = session.execute(q).one()
    return {"ai_operating_cost_micros": int(est), "actual_reported_micros": int(act), "calls": int(n)}


def category_spend(session: Session, category: str, start: date | None = None, end: date | None = None) -> int:
    q = select(func.coalesce(func.sum(-Transaction.amount_cents), 0)).where(
        Transaction.status == TxnStatus.ACTUAL, Transaction.is_transfer.is_(False), Transaction.amount_cents < 0,
        Transaction.category == category)
    return int(session.execute(_period(q, start, end)).scalar())
