"""Autopilot: AIOS works on its own, within limits the founder set.

    aios autopilot on [--at 07:00] [--cap 5]   founder turns it on (installs the daily schedule on the Mac)
    aios autopilot off | status | run | log

Each cycle (every morning, and right after the founder finishes something that unlocks system work):
  1. Mondays (or first run of the week): pull this week's AI trends for local service businesses and queue
     "draft this week's video script from them" for the system, plus "review and film this week's video"
     for the founder.
  2. Run the system's ready tasks, one at a time, while today's autopilot spend is under the cap.
  3. Refresh priorities (daily cycle only).
  4. Record what it did (event + audit) and show a Mac notification.

Hard limits, not settings:
  - Never publishes, sends, approves, rejects, changes configuration or spends outside AI model calls
    (it acts as the system actor, which can't hold those permissions).
  - Stops when today's autopilot spend reaches autopilot.daily_cap_usd. Each workflow keeps its own budget too.
  - One cycle at a time (lock file).
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from aios.config import ROOT
from aios.core import audit, events, sysconfig
from aios.core.actor import Actor
from aios.core.util import utcnow
from aios.db.enums import TaskKind, TaskStatus
from aios.db.models import EventRecord, Task, WorkflowRun

AUTOPILOT = Actor("system", "autopilot")
EVENT = "AUTOPILOT_CYCLE"
LABEL = "com.aios.autopilot"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOCK = ROOT / "data" / "autopilot.lock"
MIN_TASK_BUDGET = 0.25  # don't start a task with less than this left under the cap


# ------------------------------------------------------------------------------------------- state


def settings(session: Session) -> dict[str, Any]:
    g = lambda k: sysconfig.get(session, k)  # noqa: E731
    return {"enabled": bool(g("autopilot.enabled")), "react": bool(g("autopilot.react_to_events")),
            "cap_usd": float(g("autopilot.daily_cap_usd")), "max_tasks": int(g("autopilot.max_tasks_per_cycle")),
            "at": g("autopilot.daily_time"), "weekly_topic": g("autopilot.weekly_trends_topic")}


def spent_today_usd(session: Session) -> float:
    start = datetime.combine(utcnow().date(), time.min)
    micros = session.execute(select(func.coalesce(func.sum(WorkflowRun.total_cost_micros), 0))
                             .where(WorkflowRun.actor == str(AUTOPILOT), WorkflowRun.created_at >= start)).scalar()
    return int(micros or 0) / 1e6


def last_cycle(session: Session) -> dict | None:
    e = session.execute(select(EventRecord).where(EventRecord.type == EVENT).order_by(EventRecord.created_at.desc())
                        .limit(1)).scalar()
    return {"at": e.created_at.isoformat(), **(e.payload or {})} if e else None


def status(session: Session) -> dict:
    st = settings(session)
    spent = spent_today_usd(session)
    return {**st, "spent_today_usd": round(spent, 4), "left_today_usd": round(max(0.0, st["cap_usd"] - spent), 4),
            "scheduled": PLIST.exists(), "last_cycle": last_cycle(session)}


# ------------------------------------------------------------------------------------------- the cycle


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _did_weekly(session: Session) -> bool:
    since = datetime.combine(_week_start(utcnow().date()), time.min)
    rows = session.execute(select(EventRecord.payload).where(EventRecord.type == EVENT, EventRecord.created_at >= since))
    return any((p or {}).get("weekly") for (p,) in rows)


def _open_task_titled(session: Session, title: str) -> bool:
    return session.execute(select(Task.id).where(Task.kind == TaskKind.PLAN, Task.title == title,
                                                 Task.status.not_in((TaskStatus.COMPLETED, TaskStatus.CANCELLED)))
                           .limit(1)).first() is not None


async def run_cycle(sm: sessionmaker, engine, *, reason: str = "manual") -> dict:
    from aios.modules import todos, workqueue

    with sm() as s:
        st = settings(s)
        if not st["enabled"]:
            return {"ran": False, "why": "autopilot is off (aios autopilot on)"}
        if reason == "event" and not st["react"]:
            return {"ran": False, "why": "reacting to events is off"}
        cap = st["cap_usd"]

    def left() -> float:
        with sm() as s:
            return cap - spent_today_usd(s)

    def budget_for_next() -> float | None:
        remaining = left()
        return None if remaining < MIN_TASK_BUDGET else min(remaining, 4.0)

    summary: dict[str, Any] = {"reason": reason, "weekly": False, "tasks": [], "notes": []}
    if left() < MIN_TASK_BUDGET:
        summary["notes"].append(f"daily cap ${cap:.2f} reached; nothing run")
        return _finish(sm, summary)

    # 1. weekly content loop
    with sm() as s:
        weekly_due = reason != "event" and not _did_weekly(s)
    if weekly_due:
        res = await engine.run("trends", st["weekly_topic"], actor=AUTOPILOT,
                               options={"budget_usd": min(left(), 1.5)})
        summary["weekly"] = True
        summary["trends_run"] = res["run_id"]
        if res["status"] == "COMPLETED":
            week = _week_start(date.today()).isoformat()
            script = f"Draft this week's video script ({week})"
            film = f"Review and film this week's video ({week})"
            with sm() as s:
                if not _open_task_titled(s, script):
                    workqueue.add(s, script, agent="cmo", priority=1, actor=AUTOPILOT,
                                  note=(f"Use the trends report from run {res['run_id']} (aios runs --id "
                                        f"{res['run_id'][:8]}). Pick the one trend most useful to San Diego local "
                                        "service business owners. Write a 3-4 minute script in the founder's "
                                        "voice with hook, demo idea and newsletter/booking CTA."))
                if not _open_task_titled(s, film):
                    todos.add(s, AUTOPILOT, film, priority=1,
                              note="Autopilot drafted the script; read it with aios work / aios runs.")
                s.commit()
        else:
            summary["notes"].append(f"trends run {res['status']}: {(res.get('error') or {}).get('message', '')[:120]}")

    # 2. the system's own queue
    with sm() as s:
        n_ready = len(workqueue.runnable(s))
    if n_ready:
        done = await workqueue.run_ready(sm, engine, max_tasks=st["max_tasks"], actor=AUTOPILOT,
                                         budget_for_next=budget_for_next)
        summary["tasks"] = [{k: d[k] for k in ("task", "status", "cost_usd", "run_id")} for d in done]
        if len(done) < min(n_ready, st["max_tasks"]):
            summary["notes"].append("stopped early: daily cap reached")

    # 3. priorities (once a day is enough)
    if reason != "event" and left() >= MIN_TASK_BUDGET:
        res = await engine.run("priorities", "", actor=AUTOPILOT, options={"budget_usd": min(left(), 1.0)})
        summary["priorities_run"] = res["run_id"]

    return _finish(sm, summary)


def _finish(sm: sessionmaker, summary: dict) -> dict:
    with sm() as s:
        summary["spent_today_usd"] = round(spent_today_usd(s), 4)
        events.emit(s, EVENT, str(AUTOPILOT), summary)
        audit.record(s, who=str(AUTOPILOT), what="autopilot.cycle", why=summary["reason"],
                     output={k: v for k, v in summary.items() if k != "tasks"} | {"tasks": len(summary["tasks"])})
        s.commit()
    ok = sum(1 for t in summary["tasks"] if t["status"] == "COMPLETED")
    msg = f"{ok} task(s) done" + (", weekly script queued" if summary.get("weekly") else "") + \
          f". ${summary['spent_today_usd']:.2f} spent today."
    notify("AIOS autopilot", msg)
    return {"ran": True, **summary}


def notify(title: str, text: str) -> None:
    if sys.platform == "darwin":
        def safe(x: str) -> str:
            return x.replace("\\", "").replace('"', "'")
        subprocess.run(["osascript", "-e", f'display notification "{safe(text)}" with title "{safe(title)}"'],
                       capture_output=True)


# ------------------------------------------------------------------------------------------- triggers


def react(sm: sessionmaker) -> bool:
    """Called after the founder checks something off. Starts a cycle in the background if that unlocked
    system work and autopilot is set to react. Returns whether it started one."""
    from aios.modules import workqueue

    with sm() as s:
        st = settings(s)
        if not (st["enabled"] and st["react"]) or not workqueue.runnable(s):
            return False
        if spent_today_usd(s) > st["cap_usd"] - MIN_TASK_BUDGET:
            return False
    spawn("event")
    return True


def spawn(reason: str) -> None:
    log = (ROOT / "data" / "autopilot.log").open("a")
    subprocess.Popen([sys.executable, "-m", "aios.cli", "autopilot", "run", "--reason", reason], cwd=str(ROOT),
                     stdout=log, stderr=log, start_new_session=True)


def acquire_lock() -> bool:
    LOCK.parent.mkdir(exist_ok=True)
    if LOCK.exists():
        try:
            os.kill(int(LOCK.read_text()), 0)
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            pass
    LOCK.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    LOCK.unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------- schedule (macOS)


def install_schedule(at: str) -> Path:
    hour, minute = (int(x) for x in at.split(":"))
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [sys.executable, "-m", "aios.cli", "autopilot", "run", "--reason", "daily"],
        "WorkingDirectory": str(ROOT),
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},  # if the Mac was asleep, runs on wake
        "StandardOutPath": str(ROOT / "data" / "autopilot.log"),
        "StandardErrorPath": str(ROOT / "data" / "autopilot.log"),
    }))
    if sys.platform == "darwin":
        subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        subprocess.run(["launchctl", "load", str(PLIST)], capture_output=True)
    return PLIST


def remove_schedule() -> None:
    if PLIST.exists():
        if sys.platform == "darwin":
            subprocess.run(["launchctl", "unload", str(PLIST)], capture_output=True)
        PLIST.unlink()
