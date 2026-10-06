"""Financial records: import, validation, categorization, vendors, subscriptions, anomalies, reports.

Records are never invented. Missing data is reported as missing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import statistics
from collections import defaultdict
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from aios.core import audit, events, sysconfig
from aios.core.actor import Actor
from aios.core.errors import ValidationFailed
from aios.core.permissions import db_write, require
from aios.core.util import cents_to_str, to_cents
from aios.db.enums import Provenance, TxnStatus
from aios.db.models import Account, ImportBatch, Subscription, Transaction, Vendor
from aios.modules import metrics

DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d", "%b %d, %Y", "%d %b %Y", "%m-%d-%Y")
HEADER_ALIASES = {
    "date": {"date", "transaction date", "posted date", "posting date", "txn date", "trans date"},
    "description": {"description", "memo", "details", "payee", "name", "merchant"},
    "amount": {"amount", "amount (usd)", "value", "transaction amount"},
    "debit": {"debit", "withdrawal", "withdrawals", "money out"},
    "credit": {"credit", "deposit", "deposits", "money in"},
    "category": {"category", "type category"},
    "status": {"status"},
    "id": {"id", "transaction id", "reference", "ref"},
}
NOISE = re.compile(r"\b(pos|debit|credit|card|purchase|recurring|payment|ach|web|online|checkcard|visa|mc|"
                   r"des|id|ppd|ccd|indn|co|inc|llc|ltd|www|com)\b|[#*0-9]+|\s{2,}", re.I)


def parse_date(raw: str) -> date:
    s = raw.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{raw}'")


def vendor_name(description: str) -> str:
    cleaned = NOISE.sub(" ", description).strip(" -.,/")
    words = [w for w in re.split(r"[\s/\-]+", cleaned) if w][:3]
    return " ".join(words).title() or "Unknown"


def categorize(session: Session, description: str, amount_cents: int) -> tuple[str, bool, bool]:
    """Returns (category, is_revenue, is_transfer). First matching rule wins."""
    rules: dict[str, list[str]] = sysconfig.get(session, "finance.categories")
    d = description.lower()
    for cat in ("transfer", "revenue"):
        if any(k in d for k in rules.get(cat, [])):
            if cat == "revenue" and amount_cents <= 0:
                continue
            return cat, cat == "revenue", cat == "transfer"
    for cat, keys in rules.items():
        if cat in ("transfer", "revenue"):
            continue
        if any(k in d for k in keys):
            return cat, False, False
    return ("uncategorized_income" if amount_cents > 0 else "uncategorized"), False, False


def _map_headers(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for h in headers:
        key = h.strip().lower()
        for field, aliases in HEADER_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = h
    return mapping


def get_or_create_account(session: Session, name: str, kind: str = "CHECKING") -> Account:
    a = session.execute(select(Account).where(Account.name == name)).scalar_one_or_none()
    if a is None:
        a = Account(name=name, kind=kind)
        session.add(a)
        session.flush()
    return a


def _vendor(session: Session, name: str, ai_keywords: list[str]) -> Vendor:
    v = session.execute(select(Vendor).where(Vendor.name == name)).scalar_one_or_none()
    if v is None:
        v = Vendor(name=name, is_ai_provider=any(k in name.lower() for k in ai_keywords))
        session.add(v)
        session.flush()
    return v


def import_csv(session: Session, actor: Actor, *, text: str, filename: str, account_name: str = "Primary",
               amounts_negative_for_spend: bool = True) -> dict:
    """Validate and import a CSV of transactions. Bad rows are rejected with reasons; duplicates skipped."""
    require(actor, db_write("finance"), action="import transactions")
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValidationFailed("CSV has no header row.")
    cols = _map_headers(reader.fieldnames)
    if "date" not in cols or "description" not in cols or not ("amount" in cols or "debit" in cols or "credit" in cols):
        raise ValidationFailed("CSV needs date, description, and amount (or debit/credit) columns.",
                               found=reader.fieldnames)
    account = get_or_create_account(session, account_name)
    batch = ImportBatch(filename=filename, account_id=account.id, imported_by=str(actor))
    session.add(batch)
    session.flush()
    rules = sysconfig.get(session, "finance.categories")
    ai_keywords = rules.get("ai_tools", [])
    seen: dict[tuple, int] = defaultdict(int)
    accepted = rejected = dupes = 0
    errors: list[dict] = []
    revenue_added = expense_added = 0
    for i, row in enumerate(reader, start=2):  # header is line 1
        try:
            d = parse_date(row.get(cols["date"], "") or "")
            desc = (row.get(cols["description"], "") or "").strip()
            if not desc:
                raise ValueError("empty description")
            if "amount" in cols and (row.get(cols["amount"]) or "").strip():
                amount = to_cents(row[cols["amount"]])
                if not amounts_negative_for_spend:
                    amount = -amount
            else:
                debit = (row.get(cols.get("debit", ""), "") or "").strip() if "debit" in cols else ""
                credit = (row.get(cols.get("credit", ""), "") or "").strip() if "credit" in cols else ""
                if not debit and not credit:
                    raise ValueError("no amount")
                amount = (to_cents(credit) if credit else 0) - (abs(to_cents(debit)) if debit else 0)
            if amount == 0:
                raise ValueError("zero amount")
            if abs(amount) > 10_000_000_00:
                raise ValueError("amount over $10M; check the file")
            status_raw = (row.get(cols["status"], "") if "status" in cols else "").strip().upper()
            status = TxnStatus(status_raw) if status_raw in TxnStatus.__members__ else TxnStatus.ACTUAL
            ext = (row.get(cols["id"], "") if "id" in cols else "").strip() or None
        except (ValueError, KeyError, ArithmeticError) as e:
            rejected += 1
            errors.append({"line": i, "error": str(e), "row": {k: v for k, v in row.items() if k}})
            continue
        key = (account.id, d.isoformat(), amount, desc.lower(), ext)
        seen[key] += 1
        digest = hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest()
        if session.execute(select(Transaction.id).where(Transaction.dedupe_hash == digest)).first():
            dupes += 1
            continue
        csv_cat = (row.get(cols["category"], "") if "category" in cols else "").strip().lower()
        if csv_cat:
            cat = re.sub(r"[^a-z0-9_]+", "_", csv_cat).strip("_")
            is_rev = amount > 0 and any(w in cat for w in ("revenue", "income", "sales"))
            is_tr = "transfer" in cat
            cat_source = "IMPORT"
        else:
            cat, is_rev, is_tr = categorize(session, desc, amount)
            cat_source = "RULE"
        v = _vendor(session, vendor_name(desc), ai_keywords)
        if cat_source == "RULE" and cat.startswith("uncategorized") and v.is_ai_provider and amount < 0:
            cat = "ai_tools"
        session.add(Transaction(account_id=account.id, txn_date=d, description=desc, amount_cents=amount,
                                category=cat, category_source=cat_source, is_revenue=is_rev, is_transfer=is_tr,
                                vendor_id=v.id, status=status, source=Provenance.FINANCIAL_IMPORT,
                                import_batch_id=batch.id, external_id=ext, dedupe_hash=digest))
        accepted += 1
        if is_rev:
            revenue_added += amount
        elif amount < 0 and not is_tr:
            expense_added += -amount
    batch.row_count = accepted + rejected + dupes
    batch.accepted, batch.rejected, batch.duplicates, batch.errors = accepted, rejected, dupes, errors[:200]
    session.flush()
    detect_subscriptions(session)
    events.emit(session, events.FINANCE_IMPORTED, str(actor), {"batch_id": batch.id, "accepted": accepted})
    if revenue_added:
        events.emit(session, events.REVENUE_ADDED, str(actor), {"batch_id": batch.id, "cents": revenue_added})
    if expense_added:
        events.emit(session, events.EXPENSE_ADDED, str(actor), {"batch_id": batch.id, "cents": expense_added})
    audit.record(session, who=str(actor), what="finance.import", why=f"import {filename}",
                 input={"filename": filename, "account": account_name},
                 output={"accepted": accepted, "rejected": rejected, "duplicates": dupes},
                 target_type="import_batch", target_id=batch.id)
    return {"batch_id": batch.id, "accepted": accepted, "rejected": rejected, "duplicates": dupes,
            "errors": errors[:50]}


def detect_subscriptions(session: Session) -> list[Subscription]:
    """A vendor charged in 2+ distinct months with amounts within 15% of each other is recurring."""
    rows = session.execute(select(Transaction.vendor_id, Transaction.txn_date, Transaction.amount_cents).where(
        Transaction.status == TxnStatus.ACTUAL, Transaction.amount_cents < 0, Transaction.is_transfer.is_(False),
        Transaction.vendor_id.is_not(None))).all()
    by_vendor: dict[str, list[tuple[date, int]]] = defaultdict(list)
    for vid, d, amt in rows:
        by_vendor[vid].append((d, -amt))
    found = []
    for vid, charges in by_vendor.items():
        months = {(d.year, d.month) for d, _ in charges}
        if len(months) < 2:
            continue
        amounts = [a for _, a in charges]
        med = statistics.median(amounts)
        if med <= 0 or any(abs(a - med) / med > 0.15 for a in amounts):
            continue
        per_month = len(charges) / len(months)
        if per_month > 1.5:  # several charges a month: usage-based, not a subscription
            continue
        last = max(d for d, _ in charges)
        sub = session.execute(select(Subscription).where(Subscription.vendor_id == vid,
                                                         Subscription.source == "DETECTED")).scalar_one_or_none()
        vendor = session.get(Vendor, vid)
        if sub is None:
            sub = Subscription(vendor_id=vid, name=vendor.name if vendor else "Unknown", amount_cents=int(med),
                               interval="MONTHLY", status="ACTIVE", source="DETECTED")
            session.add(sub)
        sub.amount_cents = int(med)
        sub.last_charge_date = last
        found.append(sub)
    session.flush()
    return found


def anomalies(session: Session) -> list[dict]:
    """Unusual spending: >3σ above the mean outflow (needs 10+ outflows), or a first-time vendor ≥ $200."""
    rows = session.execute(select(Transaction).where(Transaction.status == TxnStatus.ACTUAL,
                                                     Transaction.amount_cents < 0, Transaction.is_transfer.is_(False))
                           .order_by(Transaction.txn_date)).scalars().all()
    out = []
    amounts = [-t.amount_cents for t in rows]
    if len(amounts) >= 10:
        mean, sd = statistics.mean(amounts), statistics.pstdev(amounts)
        for t in rows:
            if sd and -t.amount_cents > mean + 3 * sd:
                out.append({"transaction_id": t.id, "date": t.txn_date.isoformat(), "description": t.description,
                            "amount": cents_to_str(t.amount_cents),
                            "reason": f"more than 3 standard deviations above the average outflow ({cents_to_str(int(mean))})"})
    seen_vendor: dict[str, int] = defaultdict(int)
    for t in rows:
        seen_vendor[t.vendor_id] += 1
        if seen_vendor[t.vendor_id] == 1 and -t.amount_cents >= 200_00 and not any(a["transaction_id"] == t.id for a in out):
            out.append({"transaction_id": t.id, "date": t.txn_date.isoformat(), "description": t.description,
                        "amount": cents_to_str(t.amount_cents), "reason": "first charge from this vendor is $200 or more"})
    return out


def major_vendors(session: Session, limit: int = 10) -> list[dict]:
    rows = session.execute(
        select(Vendor.name, Vendor.is_ai_provider, func.sum(-Transaction.amount_cents), func.count())
        .join(Transaction, Transaction.vendor_id == Vendor.id)
        .where(Transaction.status == TxnStatus.ACTUAL, Transaction.amount_cents < 0, Transaction.is_transfer.is_(False))
        .group_by(Vendor.id).order_by(func.sum(-Transaction.amount_cents).desc()).limit(limit)).all()
    return [{"vendor": n, "ai_provider": bool(ai), "spend_cents": int(s), "spend": cents_to_str(int(s)), "charges": c}
            for n, ai, s, c in rows]


def by_category(session: Session) -> list[dict]:
    rows = session.execute(
        select(Transaction.category, func.sum(Transaction.amount_cents), func.count())
        .where(Transaction.status == TxnStatus.ACTUAL).group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount_cents))).all()
    return [{"category": c, "total_cents": int(s), "total": cents_to_str(int(s)), "count": n} for c, s, n in rows]


def summary(session: Session, today: date | None = None) -> dict:
    """The financial state, computed. Every value traces back to transactions via the metric registry."""
    n_txn = session.execute(select(func.count()).select_from(Transaction)).scalar() or 0
    if n_txn == 0:
        ai = metrics.ai_operating_cost(session)
        return {"has_data": False, "note": "No financial records imported yet.",
                "ai_operating_cost": {"usd": ai["ai_operating_cost_micros"] / 1e6, "calls": ai["calls"]}}
    totals = metrics.flows(session)
    b = metrics.burn(session, today=today)
    rw = metrics.runway(session, today=today)
    cash = metrics.cash_balance(session)
    gm = metrics.gross_margin(session, sysconfig.get(session, "finance.cogs_categories"))
    subs = session.execute(select(Subscription).where(Subscription.status == "ACTIVE")).scalars().all()
    recurring = sum(s.amount_cents for s in subs)
    ai_sys = metrics.ai_operating_cost(session)
    pending = session.execute(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.status != TxnStatus.ACTUAL)).scalar()
    date_range = session.execute(select(func.min(Transaction.txn_date), func.max(Transaction.txn_date))).one()
    return {
        "has_data": True,
        "period": {"from": date_range[0].isoformat(), "to": date_range[1].isoformat()},
        "transactions": n_txn,
        "totals": {k: {"cents": v, "display": cents_to_str(v)} for k, v in totals.items()},
        "burn": {**b, "gross_display": cents_to_str(b["gross_burn_monthly"]), "net_display": cents_to_str(b["net_burn_monthly"])},
        "cash": {**cash, "display": cents_to_str(cash["cash_balance"])},
        "runway": rw,
        "gross_margin": gm,
        "monthly": metrics.monthly(session),
        "by_category": by_category(session),
        "major_vendors": major_vendors(session),
        "recurring": {"monthly_cents": recurring, "display": cents_to_str(recurring),
                      "items": [{"name": s.name, "amount": cents_to_str(s.amount_cents), "source": s.source,
                                 "last_charge": s.last_charge_date.isoformat() if s.last_charge_date else None} for s in subs]},
        "anomalies": anomalies(session),
        "ai": {
            "vendor_spend_bank": {"cents": metrics.category_spend(session, "ai_tools"),
                                  "display": cents_to_str(metrics.category_spend(session, "ai_tools"))},
            "system_operating_cost": {"usd": ai_sys["ai_operating_cost_micros"] / 1e6, "calls": ai_sys["calls"],
                                      "basis": "estimated from list prices"},
        },
        "not_actual": {"cents": int(pending), "display": cents_to_str(int(pending)),
                       "note": "PENDING and COMMITTED transactions, excluded from every metric above."},
    }


def reconcile(session: Session) -> dict:
    """Check that the reported totals equal the sum of their underlying records."""
    totals = metrics.flows(session)
    raw = session.execute(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.status == TxnStatus.ACTUAL, Transaction.is_transfer.is_(False))).scalar()
    monthly_sum = sum(m["net_cash_flow"] for m in metrics.monthly(session))
    cat_sum = sum(c["total_cents"] for c in by_category(session))
    transfers = session.execute(select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
        Transaction.status == TxnStatus.ACTUAL, Transaction.is_transfer.is_(True))).scalar()
    checks = {
        "net_cash_flow_equals_sum_of_records": totals["net_cash_flow"] == int(raw),
        "monthly_sums_to_total": monthly_sum == totals["net_cash_flow"],
        "categories_sum_to_total_including_transfers": cat_sum == int(raw) + int(transfers),
    }
    return {"ok": all(checks.values()), "checks": checks}


def unit_economics(inputs: dict) -> dict:
    """Deterministic unit economics from CFO assumptions. All outputs are ESTIMATES."""
    price = inputs["price_per_customer_monthly_usd"]
    margin = inputs["gross_margin_pct"] / 100
    cac = inputs["cac_usd"]
    churn = inputs["monthly_churn_pct"] / 100
    fixed = inputs["fixed_costs_monthly_usd"]
    startup = inputs["startup_costs_usd"]
    new_per_month = inputs["new_customers_per_month"]
    contribution = price * margin
    ltv = contribution / churn if churn > 0 else None
    out = {
        "kind": "ESTIMATE",
        "contribution_per_customer_monthly_usd": round(contribution, 2),
        "ltv_usd": round(ltv, 2) if ltv is not None else None,
        "ltv_to_cac": round(ltv / cac, 2) if ltv is not None and cac > 0 else None,
        "cac_payback_months": round(cac / contribution, 1) if contribution > 0 else None,
        "breakeven_customers": (int(-(-fixed // contribution)) if contribution > 0 else None),
    }
    customers, cash, low, month_be = 0.0, -startup, -startup, None
    for month in range(1, 37):
        customers = customers * (1 - churn) + new_per_month
        cash += customers * contribution - fixed - new_per_month * cac
        low = min(low, cash)
        if month_be is None and customers * contribution >= fixed:
            month_be = month
    out.update({"months_to_operating_breakeven": month_be, "peak_cash_needed_usd": round(-low, 2) if low < 0 else 0.0,
                "customers_after_36_months": round(customers, 1), "cumulative_cash_36_months_usd": round(cash, 2),
                "simulation": "36 months, monthly churn applied before new customers, CAC paid at acquisition"})
    return out
