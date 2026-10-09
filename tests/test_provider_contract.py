"""The real Anthropic provider path, with the network call replaced by SDK-shaped responses.

These catch mismatches between our request/response handling and the SDK's actual types —
the part the scripted provider cannot exercise.
"""

import json

import anthropic
import pytest
from anthropic.types import Message

from aios.agents import schemas as S
from aios.core.errors import MissingCredentials, ModelError
from aios.llm.calls import tool_schema
from aios.llm.provider import AnthropicProvider, LLMRequest, TransientModelError

ALL_SCHEMAS = [S.Intake, S.WorkPlan, S.ExecutiveBrief, S.RiskAudit, S.TwinAlignment, S.ResearchFinding, S.PlanOutput,
               S.PrioritiesOutput, S.AuditReview, S.FinanceFinding, S.TechFinding, S.ProductFinding, S.GrowthFinding,
               S.OpsFinding, S.AnalyticsFinding]


@pytest.mark.parametrize("schema", ALL_SCHEMAS, ids=lambda s: s.__name__)
def test_output_schemas_use_only_supported_json_schema(schema):
    ts = tool_schema(schema)
    assert ts["type"] == "object" and ts.get("properties")
    blob = json.dumps(ts)
    assert "$ref" not in blob and "$defs" not in blob
    assert len(blob) < 60_000
    banned = {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength",
              "maxItems"}

    def walk(n):
        if isinstance(n, dict):
            assert not (banned & set(n)), set(n) & banned
            if n.get("type") == "object" or "properties" in n:
                assert n.get("additionalProperties") is False
            if "minItems" in n:
                assert n["minItems"] in (0, 1)
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(ts)


async def test_structured_output_request_shape(monkeypatch):
    p = AnthropicProvider("sk-ant-test-key-not-real")
    sent = {}

    async def fake_create(**kwargs):
        sent.update(kwargs)
        return _message([{"type": "text", "text": '{"intent": "x"}'}], stop="end_turn")

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    js = tool_schema(S.Intake)
    resp = await p.complete(LLMRequest(model="claude-sonnet-5-5", system="s", messages=[{"role": "user", "content": "q"}],
                                       output_schema=js))
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": js}}
    assert "tool_choice" not in sent and "tools" not in sent
    assert resp.text() == '{"intent": "x"}'


def _message(content, usage=None, stop="tool_use"):
    return Message.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-4-5-20251001",
        "stop_reason": stop, "stop_sequence": None, "content": content,
        "usage": usage or {"input_tokens": 1000, "output_tokens": 200, "cache_creation_input_tokens": 50,
                           "cache_read_input_tokens": 300,
                           "server_tool_use": {"web_search_requests": 2, "web_fetch_requests": 0}}})


async def test_request_mapping_and_usage_parsing(monkeypatch):
    p = AnthropicProvider("sk-ant-test-key-not-real")
    sent = {}

    async def fake_create(**kwargs):
        sent.update(kwargs)
        return _message([{"type": "tool_use", "id": "toolu_1", "name": "submit_intake", "input": {"intent": "x"}}])

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    req = LLMRequest(model="claude-haiku-4-5-20251001", system="SYS", messages=[{"role": "user", "content": "hi"}],
                     max_tokens=300, tools=[{"name": "submit_intake", "input_schema": tool_schema(S.Intake)}],
                     tool_choice={"type": "tool", "name": "submit_intake"})
    resp = await p.complete(req)
    assert sent["system"] == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    assert sent["tool_choice"] == {"type": "tool", "name": "submit_intake"} and sent["max_tokens"] == 300
    assert "temperature" not in sent
    assert resp.tool_input("submit_intake") == {"intent": "x"}
    u = resp.usage
    assert (u.input_tokens, u.output_tokens, u.cache_creation_tokens, u.cache_read_tokens, u.web_search_requests) == \
        (1000, 200, 50, 300, 2)


async def test_web_search_blocks_survive_round_trip(monkeypatch):
    """Blocks we send back on pause_turn must be the dicts the SDK produced, including encrypted fields."""
    p = AnthropicProvider("sk-ant-test-key-not-real")

    async def fake_create(**kwargs):
        return _message([
            {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "q"}},
            {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1",
             "content": [{"type": "web_search_result", "url": "https://a.example", "title": "A",
                          "encrypted_content": "enc", "page_age": "1 day"}]},
            {"type": "text", "text": "Found it.",
             "citations": [{"type": "web_search_result_location", "url": "https://a.example", "title": "A",
                            "cited_text": "c", "encrypted_index": "ei"}]}], stop="end_turn")

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    resp = await p.complete(LLMRequest(model="m", system="", messages=[{"role": "user", "content": "q"}]))
    result = next(b for b in resp.content if b["type"] == "web_search_tool_result")
    assert result["content"][0]["encrypted_content"] == "enc"
    assert resp.content[2]["citations"][0]["encrypted_index"] == "ei"
    assert resp.text() == "Found it."


@pytest.mark.parametrize("status,expected", [(429, TransientModelError), (529, TransientModelError),
                                             (500, TransientModelError), (400, ModelError)])
async def test_error_classification(monkeypatch, status, expected):
    import httpx

    p = AnthropicProvider("sk-ant-test-key-not-real")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status, request=request, json={"type": "error", "error": {"type": "x", "message": "boom"}})

    async def fake_create(**kwargs):
        raise p.client._make_status_error("boom", body=None, response=response)

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    with pytest.raises(expected):
        await p.complete(LLMRequest(model="m", system="s", messages=[{"role": "user", "content": "x"}]))


async def test_bad_key_is_reported_as_credentials(monkeypatch):
    import httpx

    p = AnthropicProvider("sk-ant-test-key-not-real")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(401, request=request, json={"type": "error", "error": {"type": "authentication_error",
                                                                                      "message": "invalid x-api-key"}})

    async def fake_create(**kwargs):
        raise p.client._make_status_error("invalid", body=None, response=response)

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    with pytest.raises(MissingCredentials):
        await p.complete(LLMRequest(model="m", system="s", messages=[{"role": "user", "content": "x"}]))


def test_missing_key_fails_fast():
    with pytest.raises(MissingCredentials):
        AnthropicProvider(None)


def test_doctor_offline(sm):
    from aios import doctor

    checks = {c.name: c for c in doctor.offline(sm)}
    assert checks["Database migrations"].ok and checks["Agents registered"].ok
    assert checks["Audit log hash chain"].ok and checks["Model prices known"].ok
    assert checks[".env is git-ignored"].ok


async def test_unscoped_key_error_explains_the_fix(monkeypatch):
    import httpx

    p = AnthropicProvider("sk-ant-test-key-not-real")
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(400, request=request, json={"type": "error", "error": {
        "type": "invalid_request_error",
        "message": "This API key is not scoped to a workspace, so this request must include the anthropic-workspace-id header"}})

    async def fake_create(**kwargs):
        raise p.client._make_status_error("bad", body=response.json(), response=response)

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    with pytest.raises(MissingCredentials, match="workspace"):
        await p.complete(LLMRequest(model="m", system="s", messages=[{"role": "user", "content": "x"}]))


def test_workspace_header_is_sent_when_configured():
    p = AnthropicProvider("sk-ant-test-key-not-real", "wrkspc_123")
    assert p.client.default_headers.get("anthropic-workspace-id") == "wrkspc_123"


@pytest.mark.parametrize("schema", ALL_SCHEMAS, ids=lambda s: s.__name__)
def test_output_schema_keeps_every_field(schema):
    """Regression: sanitizing must never drop a real field (e.g. one named 'title')."""
    original = schema.model_json_schema()
    sent = tool_schema(schema)

    def props(sch, defs):
        if "$ref" in sch:
            sch = defs[sch["$ref"].split("/")[-1]]
        return sch

    def compare(orig, new, defs):
        orig = props(orig, defs)
        if "properties" in orig:
            assert set(orig["properties"]) == set(new["properties"]), (set(orig["properties"]) ^ set(new["properties"]))
            assert set(orig.get("required", [])) == set(new.get("required", []))
            for k in orig["properties"]:
                compare(orig["properties"][k], new["properties"][k], defs)
        for key in ("items",):
            if key in orig:
                compare(orig[key], new[key], defs)
        for key in ("anyOf",):
            if key in orig:
                for a, b in zip(orig[key], new[key]):
                    compare(a, b, defs)

    compare(original, sent, original.get("$defs", {}))
