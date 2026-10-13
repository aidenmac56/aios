"""Kit (formerly ConvertKit) newsletter API: create and schedule a broadcast.

Free plan includes API access and unlimited broadcasts up to 10,000 subscribers (help.kit.com, checked
2026-10-13). Docs: https://developers.kit.com/api-reference/broadcasts/create-a-broadcast
"""

from __future__ import annotations

from datetime import datetime

import httpx

from aios.core.errors import MissingCredentials, ModelError
from aios.core.util import utcnow

API = "https://api.kit.com/v4"


class KitClient:
    def __init__(self, api_key: str | None, transport: httpx.BaseTransport | None = None):
        if not api_key:
            raise MissingCredentials("KIT_API_KEY is not set. In Kit: Settings → Developer → API keys (v4) → "
                                     "Add a new key, then put KIT_API_KEY=... in .env.")
        self.http = httpx.Client(headers={"X-Kit-Api-Key": api_key, "Accept": "application/json"}, timeout=60,
                                 transport=transport)

    def create_broadcast(self, *, subject: str, preview_text: str, html: str, send_at: datetime | None,
                         description: str, public: bool = True) -> dict:
        body = {"subject": subject, "preview_text": preview_text, "content": html, "description": description,
                "public": public, "published_at": (send_at or utcnow()).isoformat() + "Z",
                "send_at": send_at.isoformat() + "Z" if send_at else None}
        r = self.http.post(f"{API}/broadcasts", json=body)
        if r.status_code == 401:
            raise MissingCredentials("Kit rejected KIT_API_KEY (401).")
        if r.status_code >= 400:
            raise ModelError(f"Kit {r.status_code}: {r.text[:300]}")
        return (r.json() or {}).get("broadcast", r.json())
