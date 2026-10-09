"""Jev (TypeSafe AI): a decision-only model. It doesn't write text; it answers typed questions.

Used here for routing: "what kind of task is this?" (choice) and "does it need several opinions?"
(noul, a 0–1 probability). API: POST https://api.typesafe.ai/v1/systemone, Bearer TYPESAFE_API_KEY.
Docs: https://docs.typesafe.ai/api.md. Price (TypeSafe, Oct 2026): $0.042 per million input tokens,
output free. New signups were paused on 2026-09-22; existing keys keep working.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from aios.core.errors import MissingCredentials, ModelError
from aios.llm.provider import TransientModelError

API = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
INPUT_USD_PER_MTOK = 0.042


@dataclass
class JevAnswer:
    answers: dict[str, Any]
    input_tokens: int
    latency_ms: int

    @property
    def cost_micros(self) -> int:
        return int(round(self.input_tokens * INPUT_USD_PER_MTOK))


class JevClient:
    def __init__(self, api_key: str | None, transport: httpx.AsyncBaseTransport | None = None, timeout_s: float = 20):
        if not api_key:
            raise MissingCredentials("TYPESAFE_API_KEY is not set (Jev).")
        self.http = httpx.AsyncClient(headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout_s,
                                      transport=transport)

    async def ask(self, state: Any, questions: dict[str, dict]) -> JevAnswer:
        start = time.monotonic()
        try:
            r = await self.http.post(API, json={"state": state, "model": MODEL, "questions": questions})
        except (httpx.TimeoutException, httpx.TransportError) as e:
            raise TransientModelError(f"Jev: {type(e).__name__}") from e
        if r.status_code == 401:
            raise MissingCredentials("Jev rejected TYPESAFE_API_KEY (401).")
        if r.status_code in (429, 529) or r.status_code >= 500:
            raise TransientModelError(f"Jev {r.status_code}")
        if r.status_code >= 400:
            raise ModelError(f"Jev {r.status_code}: {r.text[:300]}")
        data = r.json()
        return JevAnswer(answers=data.get("answers", {}), input_tokens=(data.get("usage") or {}).get("input_tokens", 0),
                         latency_ms=int((time.monotonic() - start) * 1000))
