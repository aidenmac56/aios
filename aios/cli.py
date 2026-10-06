"""Command interface. Every command maps to real functionality; nothing runs unless you run it.

    aios ceo "Analyze whether I should build X"     aios approve <approval_id>
    aios board | research | market | opportunity | decision | cto | plan | priorities
    aios finance [--import file.csv]                 aios cost | agents | memory | status
    aios audit | improve                             aios serve
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from aios.bootstrap import init
from aios.core.actor import FOUNDER
from aios.core.errors import AIOSError

LLM_COMMANDS = ["ceo", "board", "research", "market", "opportunity", "decision", "cto", "plan", "priorities",
                "audit", "improve"]


def _p(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _engine(sm):
    from aios.llm.provider import build_registry
    from aios.orchestrator.engine import Engine

    return Engine(sm, build_registry, on_progress=lambda run_id, msg: print(f"  · {msg}", file=sys.stderr))


def render(result: dict) -> str:
    out: list[str] = []
    st = result.get("status")
    out.append(f"\nRun {result.get('run_id')} — {st} — AI cost ${result.get('cost_usd', 0):.3f}")
    if result.get("error"):
        out.append(f"ERROR: {result['error'].get('message')}")
    if result.get("stopped") == "budget":
        out.append(f"STOPPED by budget: {result['budget']}. Finished: {list(result.get('completed', {}))}. "
                   f"Remaining: {result.get('remaining')}")
    b = result.get("brief")
    if b:
        out += [f"\n{b['verdict']}: {b['conclusion']}", "", "Why:"] + [f"  - {w}" for w in b["why"]]
        if b.get("opposing_arguments"):
            out += ["Against:"] + [f"  - {w}" for w in b["opposing_arguments"]]
        if b.get("risks"):
            out += ["Risks:"] + [f"  - [{r['likelihood']}/{r['impact']}] {r['risk']} → {r['mitigation']}" for r in b["risks"]]
        if b.get("costs"):
            out += ["Costs (estimates):"] + [f"  - {c['item']}: ${c['low_usd']:,.0f}–${c['high_usd']:,.0f} {c['recurring']}"
                                            for c in b["costs"]]
        out += [f"Upside: {b['upside']}", f"Uncertainty: {b['uncertainty']}", f"Confidence: {b['confidence']}",
                f"Recommended action: {b['recommended_action']}"]
        if b.get("next_steps"):
            out += ["Next steps:"] + [f"  {i + 1}. {s}" for i, s in enumerate(b["next_steps"])]
        if b.get("scorecard"):
            out += ["Scorecard:"] + [f"  {s['dimension']:<22} {s['score']}/5  {s['note']}" for s in b["scorecard"]]
        if b.get("founder_alignment"):
            out.append(f"Fit with your preferences: {b['founder_alignment']}")
    if result.get("unit_economics"):
        out.append("Unit economics (computed from CFO assumptions; ESTIMATES): " + json.dumps(result["unit_economics"]))
    if result.get("risk_audit"):
        r = result["risk_audit"]
        out.append(f"Independent risk audit: {r['verdict']} — {r['summary']}")
    if result.get("research"):
        r = result["research"]
        out += [f"\nResearch ({r.get('confidence')}, live search: {r.get('live_search_used')}): {r.get('answer')}"]
        for c in (r.get("claims") or [])[:10]:
            src = c.get("source_url") or (c.get("source") or {}).get("url") or "interpretation"
            out.append(f"  - {c['text']} [{src}]")
    if result.get("created"):
        c = result["created"]
        out.append(f"\nPlan saved: project {c['project_id']} ({c['status']}), {len(c['task_ids'])} tasks.")
        for x in c.get("contradictions") or []:
            out.append(f"  ! {x}")
    if result.get("improvements") is not None and "audit_id" in result:
        out.append(f"\nAudit {result['audit_id']}: {len(result['improvements'])} improvement proposals")
        for i in result["improvements"]:
            out.append(f"  - [{i['id'][:8]}] {i['title']} ({i['area']}): {i['change']}")
    if result.get("approval_id"):
        out.append(f"\nWaiting on you. Approve:  aios approve {result['approval_id']}    Reject:  aios reject {result['approval_id']}")
    return "\n".join(out)


async def _run_followups(engine, follow: list[dict]) -> None:
    for f in follow or []:
        print(f"\nRunning follow-up '{f['workflow']}' for decision {f['decision_id']} (caused by your approval)…", file=sys.stderr)
        res = await engine.run(f["workflow"], "", options={"decision_id": f["decision_id"]})
        print(render(res))
        if f["workflow"] == "learn":
            print(f"  memories created: {res.get('memories_created')}, promoted to CONFIRMED: {res.get('memories_promoted')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="aios", description="AI Company OS")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create/upgrade the database and sync agents")
    sp = sub.add_parser("seed", help="load founder memory from a JSON seed file (reviewed by you)")
    sp.add_argument("--file", default=str(Path(__file__).parent / "seed" / "founder_seed.json"))
    for c in LLM_COMMANDS:
        p = sub.add_parser(c)
        p.add_argument("request", nargs="?", default="")
        p.add_argument("--budget", type=float, help="workflow budget in USD (overrides config for this run)")
        p.add_argument("--importance", choices=["normal", "high"], default="normal")
        if c == "research":
            p.add_argument("--force", action="store_true", help="ignore reusable research")
        if c == "plan":
            p.add_argument("--decision", help="build the plan from an approved decision id")
        if c == "cto":
            p.add_argument("--no-research", action="store_true")
    fp = sub.add_parser("finance")
    fp.add_argument("--import", dest="import_file")
    fp.add_argument("--account", default="Primary")
    fp.add_argument("--spend-positive", action="store_true", help="CSV shows spending as positive numbers")
    fp.add_argument("--opening", nargs=3, metavar=("ACCOUNT", "AMOUNT", "DATE"), help="set an account opening balance")
    fp.add_argument("--no-commentary", action="store_true", help="numbers only, no CFO model call")
    fp.add_argument("request", nargs="?", default="")
    cp = sub.add_parser("cost")
    cp.add_argument("--days", type=int, default=30)
    sub.add_parser("agents")
    sub.add_parser("status")
    mp = sub.add_parser("memory")
    mp.add_argument("action", nargs="?", default="list", choices=["list", "add", "correct", "conflicts"])
    mp.add_argument("--subject")
    mp.add_argument("--content")
    mp.add_argument("--id")
    mp.add_argument("--category", default="FOUNDER")
    mp.add_argument("--tag", action="append", default=[])
    mp.add_argument("--all", action="store_true", help="include SUPERSEDED")
    for name in ("approve", "reject"):
        p = sub.add_parser(name)
        p.add_argument("approval_id")
        p.add_argument("--note")
        p.add_argument("--no-follow-up", action="store_true")
    sub.add_parser("approvals")
    dp = sub.add_parser("decisions")
    dp.add_argument("--id")
    op = sub.add_parser("outcome", help="record what actually happened after a decision")
    op.add_argument("decision_id")
    op.add_argument("--actual", required=True)
    op.add_argument("--assessment", choices=["GOOD", "MIXED", "POOR"], required=True)
    op.add_argument("--why", required=True)
    tp = sub.add_parser("tasks")
    tp.add_argument("--project")
    tk = sub.add_parser("task")
    tk.add_argument("task_id")
    tk.add_argument("--status", choices=["READY", "RUNNING", "BLOCKED", "COMPLETED", "CANCELLED", "WAITING"])
    tk.add_argument("--criteria-met", action="store_true")
    tk.add_argument("--note")
    ip = sub.add_parser("improvement")
    ip.add_argument("action", choices=["list", "request", "rollback", "verify"])
    ip.add_argument("--id")
    ip.add_argument("--result", default="")
    ip.add_argument("--success", action="store_true")
    ep = sub.add_parser("eval")
    ep.add_argument("agent")
    ep.add_argument("--model", required=True)
    cfg = sub.add_parser("config")
    cfg.add_argument("action", choices=["list", "get", "set"], nargs="?", default="list")
    cfg.add_argument("key", nargs="?")
    cfg.add_argument("value", nargs="?", help="JSON value")
    cfg.add_argument("--why", default="set from CLI")
    rp = sub.add_parser("runs")
    rp.add_argument("--id")
    sub.add_parser("verify-log", help="verify the audit log hash chain")
    dr = sub.add_parser("doctor", help="check the installation; --live makes one tiny real model call + one search")
    dr.add_argument("--live", action="store_true")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    try:
        return _dispatch(args)
    except BrokenPipeError:  # output piped into `head` etc.
        return 0
    except AIOSError as e:
        print(f"error ({e.code}): {e.message}", file=sys.stderr)
        if e.details:
            print(json.dumps(e.details, default=str, indent=2), file=sys.stderr)
        return 2


def _dispatch(args) -> int:
    from aios.core import approvals, sysconfig
    from aios.db.enums import MemoryCategory, MemoryStatus, Provenance, TaskStatus
    from aios.modules import decisions, finance, improvements, memory, planning, status

    if args.cmd == "serve":
        import uvicorn

        from aios.config import get_settings

        s = get_settings()
        uvicorn.run("aios.api.app:app", host=s.host, port=args.port or s.port)
        return 0
    sm = init()
    if args.cmd == "init":
        print("Database ready. Agents synced.")
        return 0
    if args.cmd == "doctor":
        from aios import doctor

        checks = doctor.run(sm, args.live)
        for c in checks:
            print(f"{'PASS' if c.ok else 'FAIL'}  {c.name:<38} {c.detail}")
            if not c.ok and c.fix:
                print(f"      → {c.fix}")
        if not args.live:
            print("\nRun `aios doctor --live` to make one tiny real model call and one web search (a few cents).")
        return 0 if all(c.ok for c in checks) else 1
    if args.cmd == "seed":
        from aios.seed import load_seed

        with sm() as s:
            n = load_seed(s, Path(args.file))
            s.commit()
        print(f"Loaded {n} memories/records from {args.file}")
        return 0
    if args.cmd in LLM_COMMANDS:
        from aios.config import get_settings

        if not get_settings().has_llm_credentials:
            print("ANTHROPIC_API_KEY is not set. Put it in .env (git-ignored) and run again. "
                  "Finance, memory, planning and the dashboard work without it.", file=sys.stderr)
            return 2
        engine = _engine(sm)
        opts = {"importance": args.importance}
        if args.budget is not None:
            opts["budget_usd"] = args.budget
        if getattr(args, "force", False):
            opts["force"] = True
        if getattr(args, "decision", None):
            opts["decision_id"] = args.decision
        if getattr(args, "no_research", False):
            opts["research"] = False
        res = asyncio.run(engine.run(args.cmd, args.request, options=opts))
        _p(res) if args.json else print(render(res))
        return 0 if res["status"] in ("COMPLETED", "AWAITING_APPROVAL") else 1
    if args.cmd == "finance":
        with sm() as s:
            if args.opening:
                from datetime import date

                from aios.core.util import to_cents

                acct = finance.get_or_create_account(s, args.opening[0])
                acct.opening_balance_cents = to_cents(args.opening[1])
                acct.opening_balance_date = date.fromisoformat(args.opening[2])
                from aios.core import audit

                audit.record(s, who="founder", what="finance.opening_balance", input={"account": acct.name,
                             "amount": args.opening[1], "date": args.opening[2]}, target_type="account", target_id=acct.id)
                print(f"Opening balance set for {acct.name}.")
            if args.import_file:
                text = Path(args.import_file).read_text()
                r = finance.import_csv(s, FOUNDER, text=text, filename=Path(args.import_file).name,
                                       account_name=args.account, amounts_negative_for_spend=not args.spend_positive)
                print(f"Imported {r['accepted']} rows, rejected {r['rejected']}, duplicates {r['duplicates']}.")
                for e in r["errors"][:10]:
                    print(f"  line {e['line']}: {e['error']}")
            s.commit()
        engine = _engine(sm)
        from aios.config import get_settings

        no_llm = args.no_commentary or not get_settings().has_llm_credentials
        res = asyncio.run(engine.run("finance", args.request, options={"no_commentary": no_llm}))
        if args.json:
            _p(res)
        else:
            _print_finance(res)
        return 0
    with sm() as s:
        if args.cmd == "cost":
            _p(status.costs(s, args.days))
        elif args.cmd == "agents":
            for a in status.agents_view(s):
                print(f"{a['id']:<10} {a['title']:<42} tier {a['default_tier']:<8} runs {a['runs']:<4} "
                      f"fail {a['failed']:<3} ${a['total_cost_usd']:.3f}  perms: {', '.join(a['permissions'])}")
        elif args.cmd == "status":
            _p(status.company_status(s))
        elif args.cmd == "memory":
            if args.action == "list":
                from sqlalchemy import select

                from aios.db.models import Memory

                q = select(Memory).order_by(Memory.category, Memory.status, Memory.subject)
                for m in s.execute(q).scalars():
                    if m.status == MemoryStatus.SUPERSEDED and not args.all:
                        continue
                    print(f"[{m.id[:8]}] {m.status.value:<10} {m.provenance.value:<17} {m.subject}: {m.content}")
            elif args.action == "add":
                if not (args.subject and args.content):
                    print("--subject and --content are required", file=sys.stderr)
                    return 2
                m = memory.add(s, FOUNDER, category=MemoryCategory(args.category), subject=args.subject,
                               content=args.content, status=MemoryStatus.EXPLICIT, provenance=Provenance.FOUNDER,
                               source_ref="founder via CLI", tags=args.tag)
                print(f"Saved memory {m.id} (EXPLICIT).")
            elif args.action == "correct":
                m = memory.supersede(s, FOUNDER, _resolve_id(s, "memories", args.id), new_content=args.content,
                                     reason="founder correction")
                print(f"Superseded; new memory {m.id}.")
            elif args.action == "conflicts":
                _p(memory.conflicts(s))
        elif args.cmd in ("approve", "reject"):
            fn = approvals.approve if args.cmd == "approve" else approvals.reject
            res = fn(s, _resolve_id(s, "approvals", args.approval_id), FOUNDER, args.note)
            s.commit()
            print(json.dumps({k: v for k, v in res.items() if k != "follow_up"}, default=str))
            if res.get("follow_up") and not args.no_follow_up:
                asyncio.run(_run_followups(_engine(sm), res["follow_up"]))
        elif args.cmd == "approvals":
            from sqlalchemy import select

            from aios.db.models import Approval

            for a in s.execute(select(Approval).order_by(Approval.created_at.desc()).limit(30)).scalars():
                print(f"{a.id}  {a.status.value:<9} {a.action_type.value:<14} {a.action[:90]}")
        elif args.cmd == "decisions":
            from sqlalchemy import select

            from aios.db.models import Decision

            if args.id:
                _p(decisions.to_dict(s.get(Decision, _resolve_id(s, "decisions", args.id))))
            else:
                for d in s.execute(select(Decision).order_by(Decision.created_at.desc()).limit(30)).scalars():
                    print(f"{d.id}  {d.status.value:<16} {d.decision_type:<8} {d.question[:80]}"
                          + (f"  outcome: {d.outcome_assessment}" if d.outcome_assessment else ""))
        elif args.cmd == "outcome":
            decisions.record_outcome(s, FOUNDER, _resolve_id(s, "decisions", args.decision_id), actual_result=args.actual,
                                     assessment=args.assessment, why=args.why)
            s.commit()
            print("Outcome recorded. Future recommendations will use it.")
        elif args.cmd == "tasks":
            from sqlalchemy import select

            from aios.db.enums import TaskKind
            from aios.db.models import Task

            q = select(Task).where(Task.kind == TaskKind.PLAN).order_by(Task.priority, Task.created_at)
            if args.project:
                q = q.where(Task.project_id == _resolve_id(s, "projects", args.project))
            for t in s.execute(q).scalars():
                print(f"{t.id}  P{t.priority} {t.status.value:<17} {t.responsible_agent or '':<9} {t.title[:70]}")
        elif args.cmd == "task":
            t = planning.update_task(s, FOUNDER, _resolve_id(s, "tasks", args.task_id),
                                     status=TaskStatus(args.status) if args.status else None,
                                     criteria_met=True if args.criteria_met else None, result_note=args.note)
            s.commit()
            print(f"Task {t.id}: {t.status.value} (criteria met: {t.criteria_met})")
        elif args.cmd == "improvement":
            if args.action == "list":
                from sqlalchemy import select

                from aios.db.models import Improvement

                for i in s.execute(select(Improvement).order_by(Improvement.created_at.desc()).limit(40)).scalars():
                    print(f"{i.id}  {i.status.value:<11} {i.area:<14} {i.title}")
            elif args.action == "request":
                a = improvements.request_implementation(s, FOUNDER, _resolve_id(s, "improvements", args.id))
                s.commit()
                print(f"Approval requested: aios approve {a.id}")
            elif args.action == "rollback":
                _p(improvements.rollback(s, FOUNDER, _resolve_id(s, "improvements", args.id), "founder rollback"))
                s.commit()
            elif args.action == "verify":
                _p(improvements.verify(s, FOUNDER, _resolve_id(s, "improvements", args.id), result=args.result,
                                       success=args.success))
                s.commit()
        elif args.cmd == "eval":
            from aios.llm.provider import build_registry
            from aios.modules.evaluations import run_benchmark

            _p(asyncio.run(run_benchmark(sm, build_registry(), args.agent, args.model)))
        elif args.cmd == "config":
            if args.action == "list":
                _p(sysconfig.all_config(s))
            elif args.action == "get":
                _p(sysconfig.get(s, args.key))
            else:
                sysconfig.set_value(s, args.key, json.loads(args.value), FOUNDER, args.why)
                s.commit()
                print(f"{args.key} updated.")
        elif args.cmd == "runs":
            from sqlalchemy import select

            from aios.db.models import WorkflowRun

            if args.id:
                r = s.get(WorkflowRun, _resolve_id(s, "workflow_runs", args.id))
                print(render({"run_id": r.id, "status": r.status.value, "cost_usd": r.total_cost_micros / 1e6, **(r.result or {})}))
            else:
                for r in s.execute(select(WorkflowRun).order_by(WorkflowRun.created_at.desc()).limit(25)).scalars():
                    print(f"{r.id}  {r.status.value:<17} {r.command:<11} ${r.total_cost_micros / 1e6:.3f}  {r.request[:60]}")
        elif args.cmd == "verify-log":
            from aios.core.audit import verify_chain

            _p(verify_chain(s))
    return 0


def _resolve_id(session, table: str, prefix: str | None) -> str:
    """Accept full ids or unique prefixes (as printed by list commands)."""
    from sqlalchemy import text

    if not prefix:
        raise AIOSError("an id is required")
    rows = session.execute(text(f"SELECT id FROM {table} WHERE id LIKE :p LIMIT 2"), {"p": f"{prefix}%"}).scalars().all()
    if len(rows) != 1:
        raise AIOSError(f"{'No' if not rows else 'Ambiguous'} {table} id matching '{prefix}'")
    return rows[0]


def _print_finance(res: dict) -> None:
    f = res.get("financials") or {}
    if not f.get("has_data"):
        print(f.get("note"), f"AI operating cost so far: ${f.get('ai_operating_cost', {}).get('usd', 0):.2f}")
        return
    t = f["totals"]
    print(f"Period {f['period']['from']} → {f['period']['to']}  ({f['transactions']} transactions, ACTUAL only)")
    for k in ("revenue", "other_inflows", "expenses", "net_cash_flow"):
        print(f"  {k:<16} {t[k]['display']:>14}")
    b = f["burn"]
    net = b.get("net_burn_monthly")
    net_txt = (f"cash-flow positive, +{b['net_display'].lstrip('-')}/mo" if net is not None and net <= 0
               else f"net burn/mo {b['net_display']}")
    print(f"  gross burn/mo    {b['gross_display']:>14}   {net_txt} (last {b.get('months_used', 0)} complete months)")
    print(f"  cash             {f['cash']['display']:>14}   {f['cash'].get('note') or ''}")
    print(f"  runway (months)  {str(f['runway']['runway_months']):>14}   {f['runway'].get('note') or ''}")
    print(f"  recurring/mo     {f['recurring']['display']:>14}")
    print(f"  AI vendor spend (bank) {f['ai']['vendor_spend_bank']['display']}  |  AI system cost (estimated) "
          f"${f['ai']['system_operating_cost']['usd']:.2f}")
    print("Major vendors: " + ", ".join(f"{v['vendor']} {v['spend']}" for v in f["major_vendors"][:6]))
    for a in f["anomalies"][:8]:
        print(f"  ! {a['date']} {a['description']} {a['amount']}: {a['reason']}")
    rec = res.get("reconciliation") or {}
    print(f"Reconciliation: {'OK' if rec.get('ok') else 'MISMATCH'} {rec.get('checks')}")
    if res.get("cfo") and res["cfo"].get("summary"):
        print(f"\nCFO: {res['cfo']['summary']}\nRecommendation: {res['cfo'].get('recommendation')}")


if __name__ == "__main__":
    raise SystemExit(main())
