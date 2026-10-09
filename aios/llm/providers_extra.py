"""Model providers beyond Anthropic. Each one is an adapter behind the same LLMProvider interface.

    Provider     models (prefix)        how it's reached                                 cost
    muse         muse-spark-*           Meta Model API, OpenAI-compatible (MODEL_API_KEY) paid per token
    openai       gpt-*                  OpenAI API (OPENAI_API_KEY)                       paid per token
    ollama       ollama/<name>          Ollama on this Mac (http://127.0.0.1:11434)       free, stays on the Mac
    shortcuts    shortcut:<Shortcut>    macOS Shortcuts CLI, e.g. a shortcut whose "Use   free (Apple/ChatGPT
                                        Model" action calls ChatGPT or Apple's models     daily limits apply)

Jev (TypeSafe AI) is not here: it doesn't write text. It answers typed questions (pick one option,
score, yes/no), so it lives in aios/llm/jev.py and is used to route work, not to do it.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from aios.core.errors import MissingCredentials, ModelError, PermissionDenied
from aios.llm.provider import LLMRequest, LLMResponse, TransientModelError, Usage

_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def _json_only(text: str) -> str:
    """Models without schema enforcement often wrap JSON in fences or add a sentence; keep the object."""
    m = _FENCE.match(text)
    if m:
        return m.group(1)
    if text.strip().startswith("{"):
        return text
    start, end = text.find("{"), text.rfind("}")
    return text[start:end + 1] if 0 <= start < end else text


def _schema_hint(schema: dict) -> str:
    return ("\n\nReturn ONLY a JSON object (no prose, no code fences) that matches this JSON schema:\n"
            + json.dumps(schema, separators=(",", ":")))


def _flatten(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(b.get("text", "") for b in c if isinstance(b, dict))
        out.append({"role": m["role"], "content": str(c)})
    return out


class OpenAICompatProvider:
    """Chat Completions over HTTP. Used for Meta Model API (Muse), OpenAI (ChatGPT models) and Ollama."""

    def __init__(self, name: str, base_url: str, api_key: str | None, *, key_name: str, strip_prefix: str = "",
                 native_schema: bool = True, max_tokens_field: str = "max_completion_tokens", timeout_s: float = 180,
                 transport: httpx.AsyncBaseTransport | None = None):
        if api_key is None and key_name:
            raise MissingCredentials(f"{key_name} is not set; add it to .env to use {name}.")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.strip_prefix = strip_prefix
        self.native_schema = native_schema
        self.max_tokens_field = max_tokens_field
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = httpx.AsyncClient(headers=headers, timeout=timeout_s, transport=transport)

    def _model(self, model: str) -> str:
        return model[len(self.strip_prefix):] if self.strip_prefix and model.startswith(self.strip_prefix) else model

    async def complete(self, req: LLMRequest) -> LLMResponse:
        system = req.system
        if req.output_schema and not self.native_schema:
            system += _schema_hint(req.output_schema)
        body: dict[str, Any] = {"model": self._model(req.model),
                                "messages": [{"role": "system", "content": system}, *_flatten(req.messages)],
                                self.max_tokens_field: req.max_tokens}
        if req.output_schema and self.native_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {
                "name": (req.schema_name or "output")[:64], "schema": req.output_schema, "strict": False}}
        if req.temperature is not None:
            body["temperature"] = req.temperature
        start = time.monotonic()
        try:
            r = await self.http.post(f"{self.base_url}/chat/completions", json=body)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise TransientModelError(f"{self.name}: {type(e).__name__}: {e}") from e
        if r.status_code in (401, 403):
            raise MissingCredentials(f"{self.name} rejected the API key ({r.status_code}).")
        if r.status_code in (408, 429, 500, 502, 503, 504, 529):
            raise TransientModelError(f"{self.name} {r.status_code}: {r.text[:200]}")
        if r.status_code >= 400:
            raise ModelError(f"{self.name} {r.status_code}: {r.text[:300]}", status=r.status_code)
        data = r.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        if req.output_schema:
            text = _json_only(text)
        u = data.get("usage") or {}
        finish = choice.get("finish_reason")
        return LLMResponse(content=[{"type": "text", "text": text}],
                           stop_reason={"length": "max_tokens", "stop": "end_turn"}.get(finish, finish),
                           usage=Usage(input_tokens=u.get("prompt_tokens", 0) or 0,
                                       output_tokens=u.get("completion_tokens", 0) or 0,
                                       cache_read_tokens=((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)),
                           model=req.model, latency_ms=int((time.monotonic() - start) * 1000), provider=self.name)


class ShortcutsProvider:
    """Runs an allowed macOS shortcut with the prompt as input and its output as the answer.

    Model id: "shortcut:<exact shortcut name>". The founder must allow each shortcut by name
    (`aios mac allow "<name>"`); anything else is refused. Free, but the prompt leaves the Mac if the
    shortcut sends it somewhere (e.g. "Use Model → ChatGPT").
    """

    name = "shortcuts"

    def __init__(self, allowed: list[str] | None = None, *, allowed_loader=None, timeout_s: float = 180, runner=None):
        self._allowed = allowed
        self._loader = allowed_loader  # read at call time, so `aios mac allow` takes effect immediately
        self.timeout_s = timeout_s
        self.runner = runner  # tests inject a fake; default runs /usr/bin/shortcuts

    async def complete(self, req: LLMRequest) -> LLMResponse:
        shortcut = req.model.split(":", 1)[1]
        allowed = set(self._loader() if self._loader else (self._allowed or []))
        if shortcut not in allowed:
            raise PermissionDenied(f"Shortcut '{shortcut}' is not allowed. Allow it first: aios mac allow \"{shortcut}\"")
        prompt = "\n\n".join(m["content"] for m in _flatten(req.messages))
        text_in = (f"{req.system}\n\n{prompt}" if req.system else prompt)
        if req.output_schema:
            text_in += _schema_hint(req.output_schema)
        start = time.monotonic()
        out = await (self.runner or run_shortcut)(shortcut, text_in, self.timeout_s)
        if req.output_schema:
            out = _json_only(out)
        n_in, n_out = len(text_in) // 4, len(out) // 4  # Shortcuts reports no token counts: rough, for display only
        return LLMResponse(content=[{"type": "text", "text": out}], stop_reason="end_turn",
                           usage=Usage(input_tokens=n_in, output_tokens=n_out, actual_cost_micros=0),
                           model=req.model, latency_ms=int((time.monotonic() - start) * 1000), provider=self.name)


async def run_shortcut(name: str, text: str, timeout_s: float) -> str:
    if sys.platform != "darwin" or not shutil.which("shortcuts"):
        raise ModelError("macOS Shortcuts is only available on a Mac.")
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.txt", Path(d) / "out.txt"
        src.write_text(text, encoding="utf-8")
        proc = await asyncio.create_subprocess_exec("shortcuts", "run", name, "--input-path", str(src),
                                                    "--output-path", str(dst), "--output-type", "public.plain-text",
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            _, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError as e:
            proc.kill()
            raise TransientModelError(f"Shortcut '{name}' took longer than {timeout_s:.0f}s.") from e
        if proc.returncode != 0:
            raise ModelError(f"Shortcut '{name}' failed: {err.decode(errors='replace')[:300]}")
        return dst.read_text(encoding="utf-8", errors="replace").strip() if dst.exists() else ""
