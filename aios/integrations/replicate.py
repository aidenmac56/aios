"""Minimal Replicate HTTP client: upload a file, run a model version, wait, download the output.

Used only by the studio when the founder runs a video command. It never runs on its own.
Docs: https://replicate.com/docs/reference/http
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import httpx

from aios.core.errors import MissingCredentials, ModelError

API = "https://api.replicate.com/v1"


@dataclass
class Prediction:
    id: str
    status: str
    output_url: str | None
    predict_time_s: float
    error: str | None
    version: str


class ReplicateClient:
    def __init__(self, token: str | None, timeout_s: float = 900, poll_s: float = 4):
        if not token:
            raise MissingCredentials("REPLICATE_API_TOKEN is not set. Create one at https://replicate.com/account/api-tokens "
                                     "and add REPLICATE_API_TOKEN=... to .env.")
        self.http = httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=120)
        self.timeout_s = timeout_s
        self.poll_s = poll_s

    def _ok(self, r: httpx.Response) -> dict:
        if r.status_code == 401:
            raise MissingCredentials("Replicate rejected the token (401). Check REPLICATE_API_TOKEN in .env.")
        if r.status_code == 402:
            raise ModelError("Replicate says billing is not set up (402). Add a payment method at https://replicate.com/account/billing.")
        if r.status_code >= 400:
            raise ModelError(f"Replicate error {r.status_code}: {r.text[:300]}")
        return r.json()

    def latest_version(self, model: str) -> tuple[str, dict]:
        """Returns (version id, input schema properties)."""
        data = self._ok(self.http.get(f"{API}/models/{model}"))
        v = data.get("latest_version") or {}
        props = (((v.get("openapi_schema") or {}).get("components") or {}).get("schemas") or {}).get("Input", {}).get("properties", {})
        if not v.get("id"):
            raise ModelError(f"Replicate model {model} has no published version.")
        return v["id"], props

    def upload(self, path: Path, content_type: str) -> str:
        with path.open("rb") as f:
            data = self._ok(self.http.post(f"{API}/files", files={"content": (path.name, f, content_type)}))
        return data["urls"]["get"]

    def run(self, version: str, inputs: dict) -> Prediction:
        p = self._ok(self.http.post(f"{API}/predictions", json={"version": version, "input": inputs}))
        start = time.monotonic()
        while p.get("status") not in ("succeeded", "failed", "canceled"):
            if time.monotonic() - start > self.timeout_s:
                self.http.post(f"{API}/predictions/{p['id']}/cancel")
                raise ModelError(f"Replicate prediction {p['id']} took longer than {self.timeout_s:.0f}s and was cancelled.")
            time.sleep(self.poll_s)
            p = self._ok(self.http.get(f"{API}/predictions/{p['id']}"))
        out = p.get("output")
        if isinstance(out, list):
            out = out[-1] if out else None
        return Prediction(id=p["id"], status=p["status"], output_url=out,
                          predict_time_s=float((p.get("metrics") or {}).get("predict_time") or 0.0),
                          error=p.get("error"), version=version)

    def download(self, url: str, dest: Path) -> None:
        with self.http.stream("GET", url, follow_redirects=True) as r:
            if r.status_code >= 400:
                raise ModelError(f"Could not download Replicate output ({r.status_code}).")
            with dest.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
