"""Multi-model orchestration: routing, parallel execution, failures, synthesis, adapters. No network."""

import asyncio
import json
import time

import httpx
import pytest
from sqlalchemy import select

from aios.core import sysconfig
from aios.core.actor import FOUNDER
from aios.core.errors import MissingCredentials, ModelError, PermissionDenied, ValidationFailed
from aios.db.models import ModelUsage, WorkflowRun
from aios.llm.jev import JevClient
from aios.llm.provider import LLMRequest, LLMResponse, ProviderRegistry, TransientModelError, Usage
from aios.llm.providers_extra import OpenAICompatProvider, ShortcutsProvider
from aios.llm.testing import ScriptedProvider
from aios.orchestrator import multi
from aios.orchestrator.engine import Engine

SYNTH = {"answer": "Start with the AI receptionist video.", "agreements": ["Lead with a concrete demo"],
         "disagreements": ["Muse wanted pricing first; kept demo first because it shows value"],
         "contributions": [{"model": "muse-spark-1.3", "contribution": "pricing angle"}],
         "confidence": "MEDIUM", "caveats": ["Check Upfirst's current price"]}


class FakeProvider:
    def __init__(self, name, *, delay=0.0, fail=None, text=None):
        self.name, self.delay, self.fail, self.text = name, delay, fail, text
        self.requests = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        return LLMResponse(content=[{"type": "text", "text": self.text or f"answer from {req.model}"}],
                           stop_reason="end_turn", usage=Usage(input_tokens=100, output_tokens=200), model=req.model,
                           latency_ms=int(self.delay * 1000), provider=self.name)


def registry(**extra):
    claude = ScriptedProvider(lambda req: SYNTH if req.output_schema else "answer from claude")
    return ProviderRegistry(providers={"anthropic": claude, **extra}, default="anthropic")


def engine(sm, reg):
    return Engine(sm, reg)


# ------------------------------------------------------------------------------------------- routing


def test_rules_route_by_task_type_and_only_to_connected_models(sm):
    reg = registry(muse=FakeProvider("muse"))
    with sm() as s:
        p = asyncio.run(multi.plan(s, reg, "Write a hook for my video about missed calls", None))
        assert p.method == "rules" and p.category == "writing" and p.mode == "single"
        assert p.models == ["muse-spark-1.3"]  # first connected model in multi.routes.writing
        assert {"model": "gpt-5.6-terra", "why": "openai not set up"} in p.skipped
        p2 = asyncio.run(multi.plan(s, reg, "Should I charge $497 or $997 for the audit?", None))
        assert p2.category == "analysis" and p2.mode == "parallel"
        assert p2.models == ["claude-opus-5-5", "muse-spark-1.3"]


def test_founder_choice_must_be_connected(sm):
    with sm() as s:
        with pytest.raises(ValidationFailed, match="gpt-5.6-terra"):
            asyncio.run(multi.plan(s, registry(), "x", None, models=["gpt-5.6-terra"]))
        with pytest.raises(ValidationFailed, match="not allowed"):
            asyncio.run(multi.plan(s, registry(shortcuts=ShortcutsProvider([])), "x", None,
                                   models=["shortcut:AIOS Ask ChatGPT"]))


def _jev(answers=None, status=200):
    seen = []

    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        assert request.headers["authorization"] == "Bearer k"
        return httpx.Response(status, json={"model": "jev-1.13.0", "answers": answers or {},
                                            "usage": {"input_tokens": 300, "output_tokens": 4}})

    return JevClient("k", transport=httpx.MockTransport(handler)), seen


async def test_jev_routes_and_is_costed(sm, engine):
    jev, seen = _jev({"kind": {"type": "choice", "choice": "writing", "confidence": 0.91},
                      "many": {"type": "noul", "noul": 0.8}})
    reg = registry(muse=FakeProvider("muse"))
    rid = engine.create_run("multi", "hooks")
    from aios.core.budget import BudgetGuard, Limits
    from aios.llm.calls import CallContext

    with sm() as s:
        guard = BudgetGuard(sm, Limits.load(s), rid)
        ctx = CallContext(sm=sm, providers=reg, budget=guard, workflow_run_id=rid, workflow="multi", agent_id="multi")
        p = await multi.plan(s, reg, "Give me 5 hooks", ctx, jev=jev)
    assert p.method == "jev" and p.category == "writing" and p.mode == "parallel"
    assert seen[0]["model"] == "jev-latest" and set(seen[0]["questions"]) == {"kind", "many"}
    with sm() as s:
        u = s.execute(select(ModelUsage).where(ModelUsage.provider == "typesafe")).scalar_one()
        assert u.model == "jev-latest" and u.estimated_cost_micros == 13  # 300 tokens × $0.042/M


async def test_jev_failure_falls_back_to_rules(sm, engine):
    jev, _ = _jev(status=529)
    from aios.core.budget import BudgetGuard, Limits
    from aios.llm.calls import CallContext

    reg = registry()
    with sm() as s:
        ctx = CallContext(sm=sm, providers=reg, budget=BudgetGuard(sm, Limits.load(s)), workflow="multi")
        p = await multi.plan(s, reg, "Write an email", ctx, jev=jev)
    assert p.method == "rules" and any("Jev unavailable" in r for r in p.reasons)


# ------------------------------------------------------------------------------------------- execution


async def test_parallel_runs_concurrently_and_synthesizes(sm):
    reg = registry(muse=FakeProvider("muse", delay=0.4), openai=FakeProvider("openai", delay=0.4))
    start = time.monotonic()
    res = await engine(sm, reg).run("multi", "Should I start with YouTube or a newsletter?",
                                    options={"models": "muse-spark-1.3,gpt-5.6-terra,claude-sonnet-5-5"})
    assert time.monotonic() - start < 1.0  # three 0.4s models together, not 1.2s in sequence
    m = res["multi"]
    assert res["status"] == "COMPLETED" and m["routing"]["mode"] == "parallel" and m["routing"]["method"] == "founder"
    assert [a["status"] for a in m["responses"]] == ["ok", "ok", "ok"]
    assert m["result"]["kind"] == "synthesized" and m["result"]["answer"].startswith("Start with")
    assert m["data_sent"]["left_mac"] is True and "muse" in m["data_sent"]["to"]
    with sm() as s:
        muse = s.execute(select(ModelUsage).where(ModelUsage.provider == "muse")).scalar_one()
        assert muse.estimated_cost_micros == 100 * 1.25 + 200 * 4.25  # Muse Spark price table


async def test_one_provider_failing_doesnt_sink_the_run(sm):
    reg = registry(muse=FakeProvider("muse", fail=ModelError("muse 400: bad request")),
                   openai=FakeProvider("openai", fail=TransientModelError("openai 503")))
    res = await engine(sm, reg).run("multi", "Compare these", options={"models": "muse-spark-1.3,gpt-5.6-terra,claude-sonnet-5-5"})
    by = {a["model"]: a for a in res["multi"]["responses"]}
    assert by["muse-spark-1.3"]["status"] == "failed" and "bad request" in by["muse-spark-1.3"]["error"]
    assert by["gpt-5.6-terra"]["status"] == "failed"
    assert res["multi"]["result"] == {"kind": "direct", "model": "claude-sonnet-5-5", "answer": "answer from claude"}
    with sm() as s:
        failed = s.execute(select(ModelUsage).where(ModelUsage.success.is_(False))).scalars().all()
        assert {u.provider for u in failed} == {"muse", "openai"}


async def test_timeouts_are_reported(sm):
    with sm() as s:
        sysconfig.set_value(s, "multi.timeout_s", 0.2, FOUNDER, "test")
        s.commit()
    reg = registry(ollama=FakeProvider("ollama", delay=2))
    res = await engine(sm, reg).run("multi", "x", options={"models": "ollama/llama3.2,claude-sonnet-5-5"})
    by = {a["model"]: a for a in res["multi"]["responses"]}
    assert by["ollama/llama3.2"]["status"] == "timeout" and res["multi"]["result"]["kind"] == "direct"


async def test_all_failing_is_a_failed_run_not_an_empty_answer(sm):
    reg = ProviderRegistry(providers={"anthropic": FakeProvider("anthropic", fail=ModelError("down"))})
    res = await engine(sm, reg).run("multi", "x", options={"models": "claude-sonnet-5-5"})
    assert res["status"] == "FAILED" and "Every model failed" in res["error"]["message"]


async def test_only_the_task_text_is_sent(sm):
    muse = FakeProvider("muse")
    await engine(sm, registry(muse=muse)).run("multi", "Write a tagline", options={"models": "muse-spark-1.3"})
    sent = json.dumps(muse.requests[0].messages) + muse.requests[0].system
    assert "Write a tagline" in sent and "founder" in sent.lower()
    assert "memory" not in sent.lower() and "transactions" not in sent.lower()


# ------------------------------------------------------------------------------------------- adapters


async def test_openai_compatible_adapter_request_and_errors():
    seen = []

    def handler(req: httpx.Request):
        body = json.loads(req.content)
        seen.append((req.url.path, req.headers.get("authorization"), body))
        if body["messages"][-1]["content"] == "rate":
            return httpx.Response(429, text="slow down")
        if body["messages"][-1]["content"] == "auth":
            return httpx.Response(401, text="no")
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n{\"a\": 1}\n```"},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 12, "completion_tokens": 5}})

    p = OpenAICompatProvider("muse", "https://api.meta.ai/v1", "key", key_name="MODEL_API_KEY",
                             transport=httpx.MockTransport(handler))
    r = await p.complete(LLMRequest(model="muse-spark-1.3", system="sys", messages=[{"role": "user", "content": "hi"}],
                                    max_tokens=50, output_schema={"type": "object"}, schema_name="x"))
    path, auth, body = seen[0]
    assert path == "/v1/chat/completions" and auth == "Bearer key"
    assert body["max_completion_tokens"] == 50 and body["response_format"]["type"] == "json_schema"
    assert body["messages"][0] == {"role": "system", "content": "sys"}
    assert r.text() == '{"a": 1}' and r.usage.input_tokens == 12 and r.stop_reason == "end_turn"
    with pytest.raises(TransientModelError):
        await p.complete(LLMRequest(model="muse-spark-1.3", system="", messages=[{"role": "user", "content": "rate"}]))
    with pytest.raises(MissingCredentials):
        await p.complete(LLMRequest(model="muse-spark-1.3", system="", messages=[{"role": "user", "content": "auth"}]))


async def test_ollama_adapter_strips_prefix_and_puts_schema_in_prompt():
    seen = []

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "usage": {}})

    p = OpenAICompatProvider("ollama", "http://127.0.0.1:11434/v1", None, key_name="", strip_prefix="ollama/",
                             native_schema=False, max_tokens_field="max_tokens", transport=httpx.MockTransport(handler))
    await p.complete(LLMRequest(model="ollama/llama3.2", system="s", messages=[{"role": "user", "content": "q"}],
                                output_schema={"type": "object"}))
    assert seen[0]["model"] == "llama3.2" and "max_tokens" in seen[0] and "response_format" not in seen[0]
    assert "JSON schema" in seen[0]["messages"][0]["content"]


async def test_shortcuts_need_founder_allowlist():
    calls = []

    async def fake_run(name, text, timeout):
        calls.append((name, text))
        return "chatgpt says hi"

    p = ShortcutsProvider(["AIOS Ask ChatGPT"], runner=fake_run)
    with pytest.raises(PermissionDenied):
        await p.complete(LLMRequest(model="shortcut:Delete Files", system="", messages=[{"role": "user", "content": "x"}]))
    r = await p.complete(LLMRequest(model="shortcut:AIOS Ask ChatGPT", system="be brief",
                                    messages=[{"role": "user", "content": "hello"}]))
    assert r.text() == "chatgpt says hi" and calls == [("AIOS Ask ChatGPT", "be brief\n\nhello")]
    assert r.usage.actual_cost_micros == 0


def test_mac_allowlist_is_founder_only(sm):
    from aios.core.actor import agent
    from aios.core.errors import PermissionDenied as PD

    with sm() as s:
        with pytest.raises(PD):
            sysconfig.set_value(s, "mac.allowed_shortcuts", ["Anything"], agent("cto"), "sneaky")


def test_founder_can_pin_an_agent_to_another_provider(sm):
    from aios.llm import router

    with sm() as s:
        sysconfig.set_value(s, "routing.agent_model_overrides", {"cmo": "muse-spark-1.3"}, FOUNDER, "try muse for copy")
        s.commit()
        r = router.choose(s, agent_id="cmo", default_tier="BALANCED")
        assert r.model == "muse-spark-1.3" and "pinned" in r.reason
        assert router.choose(s, agent_id="cfo", default_tier="BALANCED").model == "claude-sonnet-5-5"


def test_registry_resolves_by_prefix():
    reg = registry(muse=FakeProvider("muse"))
    assert reg.for_model("muse-spark-1.3").name == "muse"
    assert reg.for_model("claude-opus-5-5").name == "scripted"
    with pytest.raises(MissingCredentials, match="openai"):
        reg.for_model("gpt-5.6-terra")
