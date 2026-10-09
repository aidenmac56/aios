"""Provider abstraction. The rest of the system never imports a vendor SDK directly."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from aios.core.errors import MissingCredentials, ModelError


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    web_search_requests: int = 0
    actual_cost_micros: int | None = None  # only if the provider reports billed cost


@dataclass
class LLMRequest:
    model: str
    system: str
    messages: list[dict[str, Any]]
    max_tokens: int = 4000
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None
    temperature: float | None = None
    cache_system: bool = True


@dataclass
class LLMResponse:
    content: list[dict[str, Any]]  # normalized content blocks (type, text, input, citations, ...)
    stop_reason: str | None
    usage: Usage
    model: str
    latency_ms: int
    provider: str

    def text(self) -> str:
        return "".join(b.get("text", "") for b in self.content if b.get("type") == "text")

    def tool_input(self, name: str) -> dict[str, Any] | None:
        for b in self.content:
            if b.get("type") == "tool_use" and b.get("name") == name:
                return b.get("input")
        return None


class TransientModelError(ModelError):
    """Retryable: rate limit, overload, timeout, connection, 5xx."""

    code = "model_transient"


class LLMProvider(Protocol):
    name: str

    async def complete(self, req: LLMRequest) -> LLMResponse: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, workspace_id: str | None = None):
        if not api_key:
            raise MissingCredentials(
                "ANTHROPIC_API_KEY is not set. Add it to your environment or the .env file (never commit it).")
        import anthropic

        self._anthropic = anthropic
        headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
        self.client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0, timeout=300, default_headers=headers)

    async def complete(self, req: LLMRequest) -> LLMResponse:
        a = self._anthropic
        system: Any = req.system
        if req.cache_system and req.system:
            system = [{"type": "text", "text": req.system, "cache_control": {"type": "ephemeral"}}]
        kwargs: dict[str, Any] = {"model": req.model, "max_tokens": req.max_tokens, "system": system,
                                  "messages": req.messages}
        if req.tools:
            kwargs["tools"] = req.tools
        if req.tool_choice:
            kwargs["tool_choice"] = req.tool_choice
        if req.temperature is not None:
            kwargs["temperature"] = req.temperature
        start = time.monotonic()
        try:
            resp = await self.client.messages.create(**kwargs)
        except (a.RateLimitError, a.APITimeoutError, a.APIConnectionError, a.InternalServerError) as e:
            raise TransientModelError(f"{type(e).__name__}: {e}") from e
        except a.APIStatusError as e:
            if getattr(e, "status_code", 0) in (429, 500, 502, 503, 504, 529):
                raise TransientModelError(f"{type(e).__name__}: {e}") from e
            if isinstance(e, a.AuthenticationError):
                raise MissingCredentials("The Anthropic API rejected the API key.") from e
            if "anthropic-workspace-id" in f"{e} {getattr(e, 'body', '')}":
                raise MissingCredentials(
                    "This API key is not tied to a workspace. Easiest fix: in console.anthropic.com open a workspace "
                    "(e.g. Default), create a new API key inside it, and put that key in .env. Or keep this key and "
                    "add ANTHROPIC_WORKSPACE_ID=wrkspc_... to .env.") from e
            raise ModelError(f"{type(e).__name__}: {e}", status=getattr(e, "status_code", None)) from e
        latency = int((time.monotonic() - start) * 1000)
        u = resp.usage
        stu = getattr(u, "server_tool_use", None)
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_creation_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            web_search_requests=(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
        )
        content = [b.model_dump(exclude_none=True) for b in resp.content]
        return LLMResponse(content=content, stop_reason=resp.stop_reason, usage=usage, model=resp.model,
                           latency_ms=latency, provider=self.name)


@dataclass
class ProviderRegistry:
    """Resolves the provider for a model id. One provider today; the seam for others."""

    providers: dict[str, LLMProvider] = field(default_factory=dict)
    default: str = "anthropic"

    def for_model(self, model: str) -> LLMProvider:
        if model.startswith("claude") and "anthropic" in self.providers:
            return self.providers["anthropic"]
        return self.providers[self.default]


def build_registry() -> ProviderRegistry:
    from aios.config import get_settings

    s = get_settings()
    return ProviderRegistry(providers={"anthropic": AnthropicProvider(s.anthropic_api_key, s.anthropic_workspace_id)}, default="anthropic")
