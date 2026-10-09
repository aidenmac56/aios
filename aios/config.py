"""Runtime settings. Secrets come only from environment variables (or a git-ignored .env)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader: KEY=VALUE lines, never overrides real environment variables."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class Settings(BaseModel):
    database_url: str = Field(default_factory=lambda: f"sqlite:///{ROOT / 'data' / 'aios.db'}")
    anthropic_api_key: str | None = None
    anthropic_workspace_id: str | None = None  # only for organization-level keys not scoped to a workspace
    api_token: str | None = None  # optional bearer token for the local API
    host: str = "127.0.0.1"
    port: int = 8787
    llm_provider: str = "anthropic"
    web_search_enabled: bool = True
    log_level: str = "INFO"

    @property
    def has_llm_credentials(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    env = os.environ
    return Settings(
        database_url=env.get("AIOS_DATABASE_URL") or Settings().database_url,
        anthropic_api_key=env.get("ANTHROPIC_API_KEY") or None,
        anthropic_workspace_id=env.get("ANTHROPIC_WORKSPACE_ID") or None,
        api_token=env.get("AIOS_API_TOKEN") or None,
        host=env.get("AIOS_HOST", "127.0.0.1"),
        port=int(env.get("AIOS_PORT", "8787")),
        llm_provider=env.get("AIOS_LLM_PROVIDER", "anthropic"),
        web_search_enabled=env.get("AIOS_WEB_SEARCH", "1") not in ("0", "false", "False"),
        log_level=env.get("AIOS_LOG_LEVEL", "INFO"),
    )


def redact(text: str) -> str:
    """Strip anything that looks like a secret before it reaches logs."""
    import re

    text = re.sub(r"sk-ant-[A-Za-z0-9_\-]{8,}", "sk-ant-***", text)
    text = re.sub(r"(?i)(api[_-]?key|token|secret|password)(\"?\s*[:=]\s*\"?)[^\s\",]+", r"\1\2***", text)
    return text
