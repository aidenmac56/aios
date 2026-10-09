"""Founder to-do list: what the menu bar shows and what checking a box does to the rest of the system."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from aios.core.actor import FOUNDER, agent
from aios.core.errors import NotFound, PermissionDenied
from aios.db.enums import ProjectStatus, TaskKind, TaskStatus
from aios.db.models import AuditLog, EventRecord, Project, Task, TaskDependency
from aios.modules import planning, todos


def _project_with_chain(s, status=ProjectStatus.ACTIVE):
    p = Project(name="YouTube launch", owner="founder", status=status, priority=1, objective="x", reason="x")
    s.add(p)
    s.flush()
    film = Task(kind=TaskKind.PLAN, title="Film video 1", project_id=p.id, responsible_agent="founder", priority=1,
                status=TaskStatus.READY, completion_criteria="Video recorded")
    upload = Task(kind=TaskKind.PLAN, title="Upload video 1", project_id=p.id, responsible_agent="founder", priority=1,
                  status=TaskStatus.PLANNED, completion_criteria="Live on YouTube")
    agent_task = Task(kind=TaskKind.PLAN, title="Draft 10 topics", project_id=p.id, responsible_agent="cmo", priority=1,
                      status=TaskStatus.READY)
    s.add_all([film, upload, agent_task])
    s.flush()
    s.add(TaskDependency(task_id=upload.id, depends_on_id=film.id))
    s.flush()
    return p, film, upload, agent_task


def test_list_shows_only_founder_work_in_live_projects(sm):
    with sm() as s:
        _, film, upload, agent_task = _project_with_chain(s)
        _project_with_chain(s, status=ProjectStatus.CANCELLED)
        mine = todos.add(s, FOUNDER, "Record a 30-second voice clip", priority=1)
        s.commit()
        rows = todos.open_todos(s)
        ids = [r["id"] for r in rows]
        assert agent_task.id not in ids
        assert set(ids) == {film.id, upload.id, mine.id}  # nothing from the cancelled project
        assert ids[-1] == upload.id and rows[-1]["waiting"]  # blocked work sinks to the bottom


def test_checking_off_completes_the_task_everywhere(sm):
    with sm() as s:
        _, film, upload, _ = _project_with_chain(s)
        s.commit()
        todos.complete(s, FOUNDER, film.id)
        s.commit()
        assert s.get(Task, film.id).status == TaskStatus.COMPLETED and s.get(Task, film.id).criteria_met
        assert s.get(Task, upload.id).status == TaskStatus.READY  # the dependent unlocked
        assert s.execute(select(EventRecord).where(EventRecord.type == "TASK_COMPLETED")).scalars().all()
        assert film.id not in [x["task_id"] for x in planning.priority_scores(s)]  # priorities sees it as done
        assert [d["id"] for d in todos.recently_done(s)] == [film.id]

        todos.reopen(s, FOUNDER, film.id)  # misclick
        s.commit()
        assert s.get(Task, film.id).status == TaskStatus.READY
        assert s.get(Task, upload.id).status == TaskStatus.PLANNED
        assert s.execute(select(AuditLog).where(AuditLog.what == "todo.reopen")).scalars().all()


def test_agents_cannot_touch_the_founders_list(sm):
    with sm() as s:
        _, film, _, agent_task = _project_with_chain(s)
        s.commit()
        with pytest.raises(PermissionDenied):
            todos.complete(s, agent("coo"), film.id)
        with pytest.raises(PermissionDenied):
            todos.add(s, agent("ceo"), "do this")
        with pytest.raises(NotFound):
            todos.complete(s, FOUNDER, agent_task.id)  # not a founder to-do


def test_api_round_trip(tmp_path, monkeypatch):
    import importlib

    monkeypatch.setenv("AIOS_DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.delenv("AIOS_API_TOKEN", raising=False)
    from aios import config

    config.get_settings.cache_clear()
    monkeypatch.setattr(config, "ROOT", tmp_path)
    import aios.api.app as appmod

    importlib.reload(appmod)
    with TestClient(appmod.app) as c:
        t = c.post("/api/todos", json={"title": "Set up beehiiv"}).json()
        assert [x["title"] for x in c.get("/api/todos").json()["open"]] == ["Set up beehiiv"]
        assert c.post(f"/api/todos/{t['id']}/done").status_code == 200
        body = c.get("/api/todos").json()
        assert body["open"] == [] and body["done_today"][0]["id"] == t["id"]
        assert c.post(f"/api/todos/{t['id']}/undo").status_code == 200
    config.get_settings.cache_clear()


def test_menubar_module_imports_without_rumps():
    from aios import menubar

    assert menubar._short("x" * 100, 10).endswith("…")
