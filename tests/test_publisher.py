"""Newsletter publishing: autopilot prepares and checks; only the founder sends."""

import json

import httpx
import pytest
from sqlalchemy import select

from aios.core import sysconfig
from aios.core.actor import FOUNDER, agent
from aios.core.errors import PermissionDenied
from aios.db.models import AuditLog, Task, WorkflowRun
from aios.integrations.kit import KitClient
from aios.llm.provider import ProviderRegistry
from aios.llm.testing import ScriptedProvider
from aios.modules import autopilot, publisher, todos, workqueue

BOOK = "https://cal.com/aiden/ai-quick-wins"
BODY = ("Hi,\n\nThree things this week.\n\n" + "AI receptionists got cheaper this month for small shops. " * 12
        + f"\n\nBook a free 20-minute call: {BOOK}\n\nAiden")


def _run(s, body=BODY):
    r = WorkflowRun(command="draft", request="newsletter", result={"draft": {"items": [
        {"label": "Subject line", "text": "AI Brief: three changes"}, {"label": "Preview text", "text": "Short preview"},
        {"label": "Issue body", "text": body}]}})
    s.add(r)
    s.flush()
    return r


def _providers(verdict="SEND"):
    return ProviderRegistry(providers={"anthropic": ScriptedProvider(lambda req: {"verdict": verdict, "reasons": ["ok"]})})


def _kit():
    sent = []

    def handler(req):
        sent.append(json.loads(req.content))
        assert req.headers["x-kit-api-key"] == "k"
        return httpx.Response(201, json={"broadcast": {"id": 42}})

    return KitClient("k", transport=httpx.MockTransport(handler)), sent


def _links(sm):
    with sm() as s:
        sysconfig.set_value(s, "links", {"booking": BOOK}, FOUNDER, "test")
        s.commit()


async def test_founder_send_rechecks_and_schedules(sm):
    _links(sm)
    with sm() as s:
        r = _run(s, BODY.replace(BOOK, "[booking link]"))  # placeholder gets the real link
        s.commit()
    kit, sent = _kit()
    res = await publisher.publish_newsletter(sm, _providers(), r.id, actor=FOUNDER, kit=kit)
    assert res["sent"] and res["broadcast_id"] == 42
    assert BOOK in sent[0]["content"] and "[booking link]" not in sent[0]["content"]
    assert sent[0]["subject"] == "AI Brief: three changes" and sent[0]["send_at"]
    with sm() as s:
        assert s.execute(select(AuditLog).where(AuditLog.what == "publish.newsletter")).scalar_one()


async def test_only_the_founder_sends(sm):
    with sm() as s:
        r = _run(s)
        s.commit()
    for who in (agent("cmo"), autopilot.AUTOPILOT):
        with pytest.raises(PermissionDenied):
            await publisher.publish_newsletter(sm, _providers(), r.id, actor=who, kit=_kit()[0])


async def test_failed_checks_never_send(sm):
    _links(sm)
    with sm() as s:
        bad = _run(s, BODY + "\n\nSee you at [event name].")
        held = _run(s)
        s.commit()
    kit, sent = _kit()
    res = await publisher.publish_newsletter(sm, _providers(), bad.id, actor=FOUNDER, kit=kit)
    assert not res["sent"] and "placeholder" in res["problems"][0]
    res = await publisher.publish_newsletter(sm, _providers("HOLD"), held.id, actor=FOUNDER, kit=kit)
    assert not res["sent"] and res["problems"][0].startswith("review:")
    assert sent == []


async def test_autopilot_prepares_and_hands_over_the_send_command(sm, engine, monkeypatch):
    monkeypatch.setattr(autopilot, "notify", lambda *a: None)
    _links(sm)
    with sm() as s:
        for k, v in (("autopilot.enabled", True), ("autopilot.react_to_events", True)):
            sysconfig.set_value(s, k, v, FOUNDER, "test")
        r = _run(s)
        t = workqueue.add(s, "Draft this week's newsletter issue (2026-10-12)", agent="cmo")
        t.status = __import__("aios.db.enums", fromlist=["TaskStatus"]).TaskStatus.COMPLETED
        t.criteria_met = True
        t.result = {"run_id": r.id}
        s.commit()
    monkeypatch.setattr(publisher, "model_check", _async_send)
    res = await autopilot.run_cycle(sm, engine, reason="event")
    assert res["newsletters"] == [{"task": "Draft this week's newsletter issue (2026-10-12)", "ready": True, "problems": []}]
    with sm() as s:
        titles = [x["title"] for x in todos.open_todos(s)]
        assert f"Send newsletter (2026-10-12): aios publish newsletter --run {r.id[:8]}" in titles
        assert s.get(Task, t.id).result["prepared"]["ok"] is True


async def _async_send(*a, **k):
    return publisher.PublishCheck(verdict="SEND", reasons=[])


def test_html_and_links_in_context(sm):
    html = publisher.to_html("1. Big news\n\nRead **this** at https://x.com/a\nline two")
    assert "<h3>1. Big news</h3>" in html and '<a href="https://x.com/a">' in html and "<strong>this</strong>" in html
    _links(sm)
    from aios.orchestrator import context

    with sm() as s:
        assert BOOK in context.build(s, "newsletter")
