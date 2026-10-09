"""Deterministic provider for automated tests ONLY.

It is never wired into the CLI or API. It lets tests drive the real orchestrator, database writes,
routing, budgets and cost accounting without network access, by answering each request with a
caller-supplied function.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from aios.llm.provider import LLMRequest, LLMResponse, Usage

Responder = Callable[[LLMRequest], dict[str, Any] | LLMResponse]


class ScriptedProvider:
    name = "scripted"

    def __init__(self, responder: Responder):
        self.responder = responder
        self.requests: list[LLMRequest] = []

    async def complete(self, req: LLMRequest) -> LLMResponse:
        self.requests.append(req)
        out = self.responder(req)
        if isinstance(out, LLMResponse):
            return out
        tool_name = (req.tool_choice or {}).get("name")
        usage = Usage(input_tokens=1200, output_tokens=600)
        if req.output_schema is not None:
            text = out if isinstance(out, str) else json.dumps(out)
            return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", usage=usage,
                               model=req.model, latency_ms=5, provider=self.name)
        if tool_name:
            content = [{"type": "tool_use", "id": f"toolu_{len(self.requests)}", "name": tool_name, "input": out}]
            return LLMResponse(content=content, stop_reason="tool_use", usage=usage, model=req.model,
                               latency_ms=5, provider=self.name)
        return LLMResponse(content=[{"type": "text", "text": str(out)}], stop_reason="end_turn", usage=usage,
                           model=req.model, latency_ms=5, provider=self.name)
