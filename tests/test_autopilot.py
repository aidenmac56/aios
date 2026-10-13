"""Autopilot: off by default, founder-enabled, capped, weekly content loop, reacts to events, never escalates."""

from sqlalchemy import select

from aios.core import sysconfig
from aios.core.actor import FOUNDER
from aios.core.permissions import NEVER_FOR_AGENTS, has
from aios.db.enums import ProjectStatus, TaskKind, TaskStatus
from aios.db.models import EventRecord, Project, Task, WorkflowRun
from aios.modules import autopilot, todos, workqueue


def _on(sm, cap=5.0, react=True):
    with sm() as s:
        sysconfig.set_value(s, "autopilot.enabled", True, FOUNDER, "test")
        sysconfig.set_value(s, "autopilot.react_to_events", react, FOUNDER, "test")
        sysconfig.set_value(s, "autopilot.daily_cap_usd", cap, FOUNDER, "test")
        s.commit()


async def test_off_by_default_does_nothing(sm, engine):
    res = await autopilot.run_cycle(sm, engine, reason="daily")
    assert res == {"ran": False, "why": "autopilot is off (aios autopilot on)"}
    with sm() as s:
        assert s.execute(select(WorkflowRun)).scalars().all() == []


async def test_daily_cycle_runs_weekly_loop_queue_and_priorities(sm, engine, monkeypatch):
    monkeypatch.setattr(autopilot, "notify", lambda *a: None)
    _on(sm)
    with sm() as s:
        workqueue.add(s, "Draft the welcome email", agent="cmo")
        s.commit()
    res = await autopilot.run_cycle(sm, engine, reason="daily")
    assert res["ran"] and res["weekly"] and res["trends_run"] and res["priorities_run"]
    titles = [t["task"] for t in res["tasks"]]
    assert "Draft the welcome email" in titles and any(t.startswith("Draft this week's video script") for t in titles)
    with sm() as s:
        runs = s.execute(select(WorkflowRun)).scalars().all()
        assert runs and all(r.actor == "system:autopilot" for r in runs)
        assert any(t["title"].startswith("Review and film this week's video") for t in todos.open_todos(s))
        assert s.execute(select(EventRecord).where(EventRecord.type == "AUTOPILOT_CYCLE")).scalar_one()
    again = await autopilot.run_cycle(sm, engine, reason="daily")  # same week: no second trends pull
    assert again["weekly"] is False


async def test_cap_stops_work(sm, engine, monkeypatch):
    monkeypatch.setattr(autopilot, "notify", lambda *a: None)
    _on(sm, cap=0.10)  # below the minimum for one task
    with sm() as s:
        workqueue.add(s, "Draft something", agent="cmo")
        s.commit()
    res = await autopilot.run_cycle(sm, engine, reason="daily")
    assert res["tasks"] == [] and "cap" in res["notes"][0]


async def test_event_cycle_skips_weekly_and_priorities(sm, engine, monkeypatch):
    monkeypatch.setattr(autopilot, "notify", lambda *a: None)
    _on(sm)
    with sm() as s:
        workqueue.add(s, "Draft the welcome email", agent="cmo")
        s.commit()
    res = await autopilot.run_cycle(sm, engine, reason="event")
    assert not res["weekly"] and "priorities_run" not in res and len(res["tasks"]) == 1


def test_react_only_when_enabled_and_work_is_ready(sm, monkeypatch):
    spawned = []
    monkeypatch.setattr(autopilot, "spawn", lambda reason: spawned.append(reason))
    with sm() as s:
        p = Project(name="P", owner="founder", status=ProjectStatus.ACTIVE, priority=1, objective="x", reason="x")
        s.add(p)
        s.flush()
        film = Task(kind=TaskKind.PLAN, title="Film", project_id=p.id, responsible_agent="founder",
                    status=TaskStatus.READY, completion_criteria="x")
        edit = Task(kind=TaskKind.PLAN, title="Write captions", project_id=p.id, responsible_agent="cmo",
                    status=TaskStatus.PLANNED)
        s.add_all([film, edit])
        s.flush()
        from aios.db.models import TaskDependency

        s.add(TaskDependency(task_id=edit.id, depends_on_id=film.id))
        s.commit()
        assert autopilot.react(sm) is False  # off
        _on(sm)
        assert autopilot.react(sm) is False  # nothing ready yet
        todos.complete(s, FOUNDER, film.id)
        s.commit()
    assert autopilot.react(sm) is True and spawned == ["event"]


def test_autopilot_actor_can_never_publish_approve_or_reconfigure():
    assert all(not has(autopilot.AUTOPILOT, p) for p in NEVER_FOR_AGENTS)


async def test_weekly_loop_queues_newsletter_and_supersedes_last_week(sm, engine, monkeypatch):
    monkeypatch.setattr(autopilot, "notify", lambda *a: None)
    _on(sm)
    with sm() as s:
        old_film = todos.add(s, autopilot.AUTOPILOT, "Review and film this week's video (2000-01-03)")
        mine = todos.add(s, FOUNDER, "Review and film this week's video (2000-01-03)")  # founder's own: untouched
        s.commit()
    res = await autopilot.run_cycle(sm, engine, reason="daily")
    assert res["superseded"] == 1
    with sm() as s:
        assert s.get(Task, old_film.id).status == TaskStatus.CANCELLED
        assert s.get(Task, mine.id).status == TaskStatus.READY
        titles = [t["title"] for t in todos.open_todos(s)]
        assert any(t.startswith(("Send newsletter (", "Newsletter needs a fix (")) for t in titles)
    assert any(t["task"].startswith("Draft this week's newsletter issue") for t in res["tasks"])


def test_due_dates(sm):
    from datetime import date

    from aios.core.actor import agent
    from aios.core.errors import PermissionDenied

    with sm() as s:
        t = todos.add(s, FOUNDER, "Cancel Upfirst")
        todos.set_due(s, FOUNDER, t.id, date(2026, 10, 20))
        s.commit()
        assert todos.open_todos(s)[0]["due_date"] == "2026-10-20"
        import pytest

        with pytest.raises(PermissionDenied):
            todos.set_due(s, agent("coo"), t.id, None)
