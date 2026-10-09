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
                "audit", "improve", "trends", "draft"]


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
    if result.get("draft"):
        d = result["draft"]
        out.append(f"\n{d.get('summary', '')}")
        for it in d.get("items", []):
            out.append(f"\n[{it['label']}]\n{it['text']}" + (f"\n  why: {it['why']}" if it.get("why") else ""))
        if d.get("recommended"):
            out.append("\nUse first: " + "; ".join(d["recommended"]))
    if result.get("trends"):
        tr = result["trends"]
        out.append(f"\nTrends: {tr.get('summary', '')}")
        for t in tr.get("trends", []):
            flag = "  [mostly viral discussion]" if t.get("mostly_viral_discussion") else ""
            out.append(f"  - {t['name']} ({t['category']}, {t['trajectory']}, relevance {t['relevance']}, "
                       f"evidence {t['evidence_strength']}, confidence {t['confidence']}){flag}")
            if t.get("business_opportunity"):
                out.append(f"      opportunity: {t['business_opportunity']} (test cost ${t.get('cost_to_test_usd', 0):,.0f})")
        for x in tr.get("ignore", []):
            out.append(f"  ignore: {x}")
        if tr.get("note"):
            out.append(f"  note: {tr['note']}")
    if result.get("test"):
        t = result["test"]
        out.append(f"\nTest of improvement {t['improvement_id']}: {t['conclusion']}")
        out.append(f"Request it with:  aios improvement request --id {t['improvement_id']}")
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
    pj = sub.add_parser("project", help="list projects or cancel one")
    pj.add_argument("action", choices=["list", "cancel"])
    pj.add_argument("project_id", nargs="?")
    pj.add_argument("--why", default="cancelled by founder")
    tp = sub.add_parser("tasks")
    tp.add_argument("--project")
    tk = sub.add_parser("task")
    tk.add_argument("task_id")
    tk.add_argument("--status", choices=["READY", "RUNNING", "BLOCKED", "COMPLETED", "CANCELLED", "WAITING"])
    tk.add_argument("--criteria-met", action="store_true")
    tk.add_argument("--note")
    ip = sub.add_parser("improvement")
    ip.add_argument("action", choices=["list", "show", "test", "request", "rollback", "verify"])
    ip.add_argument("--id")
    ip.add_argument("--result", default="")
    ip.add_argument("--success", action="store_true")
    ag = sub.add_parser("agent", help="agent prompt versions (activation is founder-only)")
    ag.add_argument("action", choices=["versions", "activate", "show-prompt"])
    ag.add_argument("agent_id")
    ag.add_argument("version", nargs="?", type=int)
    ag.add_argument("--why", default="activated from CLI")
    dbp = sub.add_parser("db", help="export the database to JSON, or import an export into a new database")
    dbp.add_argument("action", choices=["export", "import"])
    dbp.add_argument("path")
    dbp.add_argument("--url", help="target database URL for import (default: AIOS_DATABASE_URL)")
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
    vp = sub.add_parser("voice", help="your cloned voice: setup from your own recording, then say a script")
    vp.add_argument("action", choices=["setup", "say"])
    vp.add_argument("source", nargs="?", help="setup: your recording; say: the text to speak")
    vp.add_argument("--mine", action="store_true", help="confirm the recording is your own voice")
    vp.add_argument("--start", type=float, default=0, help="setup: where the clean part starts (seconds)")
    vp.add_argument("--seconds", type=float, default=20, help="setup: length of the reference clip (8–30)")
    av = sub.add_parser("avatar", help="your face for avatar videos, from your own footage")
    av.add_argument("action", choices=["setup"])
    av.add_argument("source", help="a video of you talking to the camera (15–60 s)")
    av.add_argument("--mine", action="store_true", help="confirm the footage is of you")
    vd = sub.add_parser("video", help="make a talking-head video of you from a script (saved as a draft)")
    vd.add_argument("action", choices=["make"])
    vd.add_argument("text", nargs="?")
    vd.add_argument("--audio", help="reuse audio from `aios voice say` instead of generating it again")
    for p_ in (vp, vd):
        p_.add_argument("--file", help="read the script from a file")
        p_.add_argument("--from-run", help="use a draft from `aios draft` (run id)")
        p_.add_argument("--item", type=int, help="which draft item (1-based)")
    td = sub.add_parser("todo", help="your to-do list: things only you can do outside the system")
    td.add_argument("action", choices=["list", "add", "done", "undo"], nargs="?", default="list")
    td.add_argument("text", nargs="?", help="add: what to do; done/undo: the to-do id (prefix is fine)")
    td.add_argument("--priority", type=int, choices=[1, 2, 3, 4, 5], default=2)
    td.add_argument("--due", help="YYYY-MM-DD")
    mb = sub.add_parser("menubar", help="Mac menu bar to-do list (top-right corner)")
    mb.add_argument("--install", action="store_true", help="also start it when you log in")
    mb.add_argument("--uninstall", action="store_true", help="stop starting it at login")
    md = sub.add_parser("media", help="list voice/face references and generated media")
    md.add_argument("action", choices=["list"], nargs="?", default="list")
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

    if args.cmd == "db":  # before init(): an import needs an empty, freshly migrated target
        from aios.config import get_settings
        from aios.db.portable import export_db, import_db

        if args.action == "export":
            m = export_db(get_settings().database_url, args.path)
            print(f"Exported {sum(m['counts'].values())} rows from {len(m['counts'])} tables to {args.path}")
            return 0
        r = import_db(args.url or get_settings().database_url, args.path)
        print(json.dumps({k: r[k] for k in ("ok", "mismatched", "audit_chain")}, indent=2, default=str))
        return 0 if r["ok"] else 1
    if args.cmd == "serve":
        import uvicorn

        from aios.config import get_settings

        s = get_settings()
        uvicorn.run("aios.api.app:app", host=s.host, port=args.port or s.port)
        return 0
    sm = init()
    if args.cmd in ("voice", "avatar", "video", "media"):
        return _studio(sm, args)
    if args.cmd == "todo":
        return _todo(sm, args)
    if args.cmd == "menubar":
        from aios import menubar

        if args.uninstall:
            menubar.uninstall()
            print("The menu bar app will no longer start at login.")
            return 0
        if args.install:
            print(f"Installed {menubar.install()}: the to-do list starts at login and is starting now (top-right).")
            return 0
        menubar.run()
        return 0
    if args.cmd == "init":
        print("Database ready. Agents synced.")
        return 0
    if args.cmd == "doctor":
        from aios import doctor

        checks = doctor.run(sm, args.live)
        for c in checks:
            label = ("INFO" if c.fix else "PASS") if c.optional else ("PASS" if c.ok else "FAIL")
            print(f"{label}  {c.name:<38} {c.detail}")
            if c.fix and (c.optional or not c.ok):
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
        elif args.cmd == "project":
            from aios.db.enums import ProjectStatus
            from aios.db.models import Project, Task
            from aios.core import audit as _audit
            from sqlalchemy import select

            if args.action == "list":
                for p in s.execute(select(Project).order_by(Project.created_at)).scalars():
                    n = s.execute(select(Task).where(Task.project_id == p.id)).scalars().all()
                    done = sum(1 for t in n if t.status == TaskStatus.COMPLETED)
                    print(f"{p.id}  {p.status.value:<10} {done}/{len(n)} tasks  {p.name}")
            else:
                p = s.get(Project, _resolve_id(s, "projects", args.project_id))
                p.status = ProjectStatus.CANCELLED
                for t in s.execute(select(Task).where(Task.project_id == p.id)).scalars():
                    if t.status != TaskStatus.COMPLETED:
                        t.status = TaskStatus.CANCELLED
                _audit.record(s, who="founder", what="project.cancel", why=args.why, target_type="project", target_id=p.id)
                s.commit()
                print(f"Cancelled project '{p.name}' and its open tasks.")
        elif args.cmd == "tasks":
            from sqlalchemy import select

            from aios.db.enums import TaskKind
            from aios.db.models import Task

            q = select(Task).where(Task.kind == TaskKind.PLAN, Task.status != TaskStatus.CANCELLED).order_by(
                Task.priority, Task.created_at)
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
            elif args.action == "show":
                from aios.db.models import Improvement

                _p(improvements.to_dict(s.get(Improvement, _resolve_id(s, "improvements", args.id))))
            elif args.action == "test":
                from aios.config import get_settings

                if not get_settings().has_llm_credentials:
                    print("Testing runs the agent's benchmark, which needs ANTHROPIC_API_KEY in .env.", file=sys.stderr)
                    return 2
                imp_id = _resolve_id(s, "improvements", args.id)
                s.close()
                res = asyncio.run(_engine(sm).run("test", "", options={"improvement_id": imp_id}))
                _p(res) if args.json else print(render(res))
                return 0 if res["status"] == "COMPLETED" else 1
        elif args.cmd == "agent":
            from aios.agents import registry
            from aios.agents.specs import SPECS

            if args.agent_id not in SPECS:
                print(f"Unknown agent. Known: {', '.join(SPECS)}", file=sys.stderr)
                return 2
            if args.action == "versions":
                for v in registry.versions(s, args.agent_id):
                    print(f"v{v['version']}{' (active)' if v['active'] else ''}  {v['created_at'][:16]}  "
                          f"by {v['created_by']}: {v['reason']}")
            elif args.action == "show-prompt":
                cfg = (registry.config_for_version(s, args.agent_id, args.version) if args.version
                       else registry.active_config(s, args.agent_id))
                print(f"# {args.agent_id} v{cfg.version}\n{cfg.system_prompt}")
            elif args.action == "activate":
                if args.version is None:
                    print("Give the version number to activate.", file=sys.stderr)
                    return 2
                registry.activate_version(s, args.agent_id, args.version, "founder", None, args.why)
                s.commit()
                print(f"{args.agent_id} now runs version {args.version}.")
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


def _todo(sm, args) -> int:
    from datetime import date

    from aios.modules import todos

    with sm() as s:
        if args.action == "add":
            if not args.text:
                raise AIOSError('Say what to do: aios todo add "Record a 30-second voice clip"')
            t = todos.add(s, FOUNDER, args.text, priority=args.priority,
                          due=date.fromisoformat(args.due) if args.due else None)
            s.commit()
            print(f"Added [{t.id[:8]}] {t.title}")
            return 0
        if args.action in ("done", "undo"):
            tid = _resolve_id(s, "tasks", args.text)
            t = (todos.complete if args.action == "done" else todos.reopen)(s, FOUNDER, tid)
            s.commit()
            print(f"{'Done' if args.action == 'done' else 'Reopened'}: {t.title}")
            return 0
        rows, done = todos.open_todos(s), todos.recently_done(s)
    if args.json:
        _p({"open": rows, "done_today": done})
        return 0
    if not rows:
        print("Nothing on your list.")
    for t in rows:
        flag = " (waiting)" if t["waiting"] else (" (overdue)" if t["due_date"] and t["due_date"] < date.today().isoformat() else "")
        print(f"[ ] {t['id'][:8]}  P{t['priority']}  {t['title']}" + (f"  · {t['project']}" if t["project"] else "") + flag)
    for t in done:
        print(f"[x] {t['id'][:8]}  {t['title']}")
    return 0


def _studio(sm, args) -> int:
    from aios.modules import studio

    def script() -> str:
        if getattr(args, "from_run", None):
            with sm() as s:
                return studio.script_from_run(s, _resolve_id(s, "workflow_runs", args.from_run), args.item)
        if getattr(args, "file", None):
            return Path(args.file).expanduser().read_text(encoding="utf-8")
        text = args.source if args.cmd == "voice" else args.text
        if not text:
            raise AIOSError("Give the script as text, --file script.txt, or --from-run <draft run id> --item N")
        return text

    def show(a: dict) -> None:
        if args.json:
            _p(a)
            return
        print(f"{a['kind']} {a['id']}  {a['status']}  {a['duration_s'] or 0:.1f}s  {a['engine']}"
              + (f"  ${a['cost_usd']:.3f}" if a["cost_usd"] else ""))
        print(f"  file: {a['path']}")
        if a.get("disclosure"):
            print(f"  ! {a['disclosure']}")

    if args.cmd == "media":
        with sm() as s:
            rows = studio.list_assets(s)
        if args.json:
            _p(rows)
        for a in [] if args.json else rows:
            print(f"{a['id']}  {a['kind']:<15} {a['status']:<8} {a['duration_s'] or 0:>6.1f}s  "
                  f"${a['cost_usd']:.3f}  {Path(a['path']).name}")
        return 0
    if args.action == "setup":
        if not args.source:
            raise AIOSError("Give the path to your recording.")
        with sm() as s:
            fn = studio.setup_voice if args.cmd == "voice" else studio.setup_avatar
            kw = ({"confirm_own_voice": args.mine, "start_s": args.start, "seconds": args.seconds} if args.cmd == "voice"
                  else {"confirm_own_face": args.mine})
            a = fn(s, FOUNDER, Path(args.source), **kw)
            s.commit()
            show(studio.to_dict(a))
        nxt = 'aios voice say "Testing my cloned voice."' if args.cmd == "voice" else 'aios video make "Quick test of my avatar."'
        print(f"Ready. Try:  {nxt}")
        return 0
    if args.cmd == "voice":
        print("Generating speech on this computer (first run downloads the model, ~1–2 GB)…", file=sys.stderr)
        show(studio.speak(sm, FOUNDER, script()))
        return 0
    print("Generating voice, then lip-syncing on Replicate (usually 1–3 minutes)…", file=sys.stderr)
    show(studio.make_video(sm, FOUNDER, "" if args.audio else script(),
                           audio_asset_id=_resolve_id_sm(sm, "media_assets", args.audio) if args.audio else None))
    return 0


def _resolve_id_sm(sm, table: str, prefix: str) -> str:
    with sm() as s:
        return _resolve_id(s, table, prefix)


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
