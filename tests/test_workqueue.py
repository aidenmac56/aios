"""The system's own list: agent-owned tasks, run only when the founder says so."""

from sqlalchemy import select

from aios.db.enums import ProjectStatus, TaskKind, TaskStatus
from aios.db.models import Project, Task, WorkflowRun
from aios.modules import todos, workqueue


def _setup(s):
    p = Project(name="Newsletter", owner="founder", status=ProjectStatus.ACTIVE, priority=1, objective="x", reason="x")
    s.add(p)
    s.flush()
    write = Task(kind=TaskKind.PLAN, title="Draft the welcome email", project_id=p.id, responsible_agent="cmo",
                 priority=1, status=TaskStatus.READY, completion_criteria="A welcome email draft exists")
    later = Task(kind=TaskKind.PLAN, title="Research newsletter tools", project_id=p.id, responsible_agent="research",
                 priority=2, status=TaskStatus.PLANNED)
    mine = Task(kind=TaskKind.PLAN, title="Create beehiiv account", project_id=p.id, responsible_agent="founder",
                priority=1, status=TaskStatus.READY, completion_criteria="Account exists")
    s.add_all([write, later, mine])
    s.flush()
    return write, later, mine


def test_lists_are_split_between_founder_and_system(sm):
    with sm() as s:
        write, later, mine = _setup(s)
        s.commit()
        q = {x["id"]: x for x in workqueue.queue(s)}
        assert set(q) == {write.id, later.id}
        assert q[write.id]["workflow"] == "draft" and q[later.id]["workflow"] == "research"
        assert [x["id"] for x in workqueue.runnable(s)] == [write.id]
        assert [t["id"] for t in todos.open_todos(s)] == [mine.id]


async def test_run_completes_the_task_with_the_run_as_evidence(sm, engine):
    with sm() as s:
        write, _, mine = _setup(s)
        s.commit()
    res = await workqueue.run_ready(sm, engine, max_tasks=3)
    assert len(res) == 1 and res[0]["status"] == "COMPLETED" and res[0]["workflow"] == "draft"
    with sm() as s:
        t = s.get(Task, write.id)
        assert t.status == TaskStatus.COMPLETED and t.result["run_id"] == res[0]["run_id"]
        run = s.get(WorkflowRun, res[0]["run_id"])
        assert "Draft the welcome email" in run.request and "Done when:" in run.request
        assert s.get(Task, mine.id).status == TaskStatus.READY  # the founder's task is never touched
        workqueue.reopen(s, write.id, "too generic")
        s.commit()
        assert s.get(Task, write.id).status == TaskStatus.READY


async def test_nothing_runs_without_a_call(sm):
    with sm() as s:
        write, _, _ = _setup(s)
        s.commit()
        assert s.execute(select(WorkflowRun)).scalars().all() == []
        assert s.get(Task, write.id).status == TaskStatus.READY


def test_founder_can_hand_tasks_to_the_system_and_back(sm):
    with sm() as s:
        _, _, mine = _setup(s)
        t = workqueue.add(s, "Write 5 hooks for video 1", agent="cmo")
        workqueue.assign(s, mine.id, "research")
        s.commit()
        ids = [x["id"] for x in workqueue.queue(s)]
        assert t.id in ids and mine.id in ids
        workqueue.assign(s, mine.id, "founder")
        s.commit()
        assert mine.id in [x["id"] for x in todos.open_todos(s)]
