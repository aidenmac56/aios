"""Context retrieval: what an agent needs to know, trimmed to a budget, with every item labeled."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.db.enums import ProjectStatus
from aios.db.models import Company, Project
from aios.modules import decisions, finance, memory, research

MAX_CHARS = 14_000


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 20] + "\n…(truncated)"


def financial_brief(session: Session) -> str:
    s = finance.summary(session)
    if not s.get("has_data"):
        return f"No financial records imported yet. AI operating cost so far: ${s['ai_operating_cost']['usd']:.2f}."
    t = s["totals"]
    lines = [
        f"Period {s['period']['from']} to {s['period']['to']} ({s['transactions']} transactions, ACTUAL only):",
        f"- computed:revenue = {t['revenue']['display']}",
        f"- computed:expenses = {t['expenses']['display']}",
        f"- computed:net_cash_flow = {t['net_cash_flow']['display']}",
        f"- computed:gross_burn_monthly = {s['burn']['gross_display']} ; computed:net_burn_monthly = {s['burn']['net_display']} "
        f"(over {s['burn'].get('months_used', 0)} complete months)",
        f"- computed:cash_balance = {s['cash']['display']}" + (f" ({s['cash']['note']})" if s['cash'].get('note') else ""),
        f"- computed:runway_months = {s['runway']['runway_months']}" + (f" ({s['runway']['note']})" if s['runway'].get('note') else ""),
        f"- computed:recurring_costs_monthly = {s['recurring']['display']}",
        f"- computed:ai_vendor_spend = {s['ai']['vendor_spend_bank']['display']} ; computed:ai_operating_cost = "
        f"${s['ai']['system_operating_cost']['usd']:.2f} (estimated)",
        f"- top vendors: " + ", ".join(f"{v['vendor']} {v['spend']}" for v in s["major_vendors"][:5]),
    ]
    if s["anomalies"]:
        lines.append("- anomalies: " + "; ".join(f"{a['date']} {a['description']} {a['amount']} ({a['reason']})"
                                                 for a in s["anomalies"][:5]))
    return "\n".join(lines)


def build(session: Session, request: str, *, agent_id: str | None = None, include_finance: bool = True) -> str:
    parts: list[str] = []
    mems = memory.retrieve(session, request, limit=25)
    parts.append("FOUNDER & COMPANY MEMORY (status | provenance):\n" + memory.format_for_prompt(mems))
    companies = session.execute(select(Company)).scalars().all()
    if companies:
        parts.append("COMPANIES:\n" + "\n".join(
            f"- {c.name}: mission={c.mission or 'n/a'}; strategy={c.strategy or 'n/a'}; model={c.business_model or 'n/a'}"
            for c in companies))
    projects = session.execute(select(Project).where(Project.status.in_([ProjectStatus.ACTIVE, ProjectStatus.PROPOSED,
                                                                          ProjectStatus.BLOCKED]))
                               .order_by(Project.priority).limit(10)).scalars().all()
    if projects:
        parts.append("ACTIVE/PROPOSED PROJECTS:\n" + "\n".join(
            f"- [{p.status.value} P{p.priority}] {p.name}: {p.objective or ''} (expected cost "
            f"{(p.expected_cost_cents or 0) / 100:,.0f} USD)" for p in projects))
    dtype = "TECH" if agent_id == "cto" else ("MARKETING" if agent_id == "cmo" else None)
    hist = decisions.relevant_history(session, request, decision_type=dtype)
    if hist:
        parts.append("PAST DECISIONS (learn from outcomes):\n" + "\n".join(decisions.brief_line(d) for d in hist))
    reports = research.related(session, request, limit=4)
    if reports:
        parts.append("EXISTING RESEARCH (reuse before re-researching):\n" + "\n\n".join(research.brief(r) for r in reports))
    if include_finance:
        parts.append("FINANCIAL STATE (computed by code; cite as computed:<key>):\n" + financial_brief(session))
    return _clip("\n\n".join(parts), MAX_CHARS)


def dependency_block(outputs: dict[str, dict]) -> str:
    if not outputs:
        return ""
    chunks = []
    for key, out in outputs.items():
        chunks.append(f"### {key} ({out.get('_agent', '?')})\n{json.dumps(out, default=str)[:6000]}")
    return "FINDINGS FROM OTHER AGENTS (check their evidence; do not defer to them):\n" + "\n\n".join(chunks)
