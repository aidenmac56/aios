"""`aios doctor`: is this installation healthy and ready to talk to the real model?

Offline checks cost nothing. `--live` makes one small structured call and one web search on the
cheapest configured model (a few cents), recorded in model_usage like any other call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import sessionmaker

from aios.config import ROOT, get_settings


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    optional: bool = False  # reported, never fails the run


class _Ping(BaseModel):
    answer: str = Field(description="The single word 'ready'.")
    confidence: int = Field(ge=0, le=100)


def offline(sm: sessionmaker) -> list[Check]:
    from aios.agents.specs import SPECS
    from aios.core import sysconfig
    from aios.core.audit import verify_chain
    from aios.db.migrate import MIGRATIONS
    from aios.db.models import Agent
    from aios.llm.pricing import price_for

    s_ = get_settings()
    out: list[Check] = []
    out.append(Check("Anthropic API key", s_.has_llm_credentials,
                     "set" if s_.has_llm_credentials else "missing — agent workflows cannot run",
                     "" if s_.has_llm_credentials else "Add ANTHROPIC_API_KEY=... to .env in the repo root."))
    gi = (ROOT / ".gitignore").read_text() if (ROOT / ".gitignore").exists() else ""
    out.append(Check(".env is git-ignored", ".env" in gi.split(), "yes" if ".env" in gi.split() else "NO",
                     "Add .env to .gitignore before putting a key in it."))
    with sm() as s:
        try:
            rev = s.execute(text("SELECT version_num FROM alembic_version")).scalar()
            heads = sorted(p.name.split("_")[0] for p in (MIGRATIONS / "versions").glob("*.py"))
            latest = heads[-1] if heads else None
            out.append(Check("Database migrations", rev == latest, f"at {rev}, latest {latest}",
                             "Run `aios init`." if rev != latest else ""))
        except Exception as e:  # pragma: no cover - only on a broken database
            out.append(Check("Database migrations", False, str(e)[:200], "Run `aios init`."))
        synced = {a for a in s.execute(select(Agent.id)).scalars()}
        missing = sorted(set(SPECS) - synced)
        out.append(Check("Agents registered", not missing, f"{len(synced)} agents" if not missing else f"missing {missing}",
                         "Run `aios init`." if missing else ""))
        chain = verify_chain(s)
        out.append(Check("Audit log hash chain", chain["ok"], f"{chain['entries']} entries"
                         + ("" if chain["ok"] else f", first bad seq {chain['first_bad_seq']}"),
                         "" if chain["ok"] else "The audit log was altered outside the system. Investigate before continuing."))
        models = sysconfig.get(s, "routing.models")
        unpriced = [m for m in models.values() if price_for(m) is None]
        out.append(Check("Model prices known", not unpriced, ", ".join(f"{t}={m}" for t, m in models.items()),
                         f"Add prices for {unpriced} in aios/llm/pricing.py." if unpriced else ""))
    web = Path(__file__).resolve().parent / "web_dist" / "index.html"
    out.append(Check("Dashboard built", web.exists(), "aios/web_dist present" if web.exists() else "missing",
                     "" if web.exists() else "cd web && npm install && npm run build"))
    out.append(Check("API token", True, "required" if s_.api_token else "not set (fine for localhost-only use)",
                     "" if s_.api_token else "Set AIOS_API_TOKEN if anyone else can reach this machine's port."))
    out += studio_checks(sm)
    return out


def studio_checks(sm: sessionmaker) -> list[Check]:
    """Optional: the voice/avatar studio. Reported, never failing, since nothing else depends on it."""
    import shutil
    import subprocess
    import sys

    from aios.db.enums import MediaKind
    from aios.modules import studio

    s_ = get_settings()

    def info(name: str, ready: bool, detail: str, fix: str) -> Check:
        return Check(f"Studio: {name}", True, detail, "" if ready else fix, optional=True)

    ff = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
    py = s_.tts_python or sys.executable
    try:
        has = subprocess.run([py, "-c", "import importlib.util as u,sys;sys.exit(0 if u.find_spec('chatterbox') else 1)"],
                             capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        has = False
    with sm() as s:
        v, a = studio.active(s, MediaKind.VOICE_REFERENCE), studio.active(s, MediaKind.AVATAR_SOURCE)
    return [
        info("ffmpeg", ff, "installed" if ff else "not installed (needed for voice and avatar)", "brew install ffmpeg"),
        info("Chatterbox (voice)", has, f"{'installed' if has else 'not installed'} in {py}",
             "See README → Studio (one-time, free install)."),
        info("Replicate token (avatar)", bool(s_.replicate_api_token), "set" if s_.replicate_api_token else "not set",
             "Add REPLICATE_API_TOKEN=... to .env (only needed for avatar videos)."),
        info("your voice / face", bool(v and a), f"voice {'ready' if v else 'not set up'}, face {'ready' if a else 'not set up'}",
             "aios voice setup <recording> --mine   and   aios avatar setup <video> --mine"),
    ]


async def live(sm: sessionmaker) -> list[Check]:
    from aios.core import sysconfig
    from aios.core.budget import BudgetGuard, Limits
    from aios.core.errors import AIOSError
    from aios.llm import calls
    from aios.llm.calls import CallContext
    from aios.llm.provider import build_registry

    out: list[Check] = []
    if not get_settings().has_llm_credentials:
        return [Check("Live model call", False, "skipped: no API key", "Add ANTHROPIC_API_KEY to .env.")]
    with sm() as s:
        sysconfig_models = sysconfig.get(s, "routing.models")
        model = sysconfig_models["BALANCED"]  # the research agent searches on this tier
        guard = BudgetGuard(sm, Limits.load(s, workflow_override_usd=0.25))
    try:
        providers = build_registry()
    except AIOSError as e:
        return [Check("Live model call", False, e.message, "Check the key in .env.")]
    ctx = CallContext(sm=sm, providers=providers, budget=guard, workflow="doctor", agent_id="analytics", tier="FAST",
                      output_retries=1, api_retries=1)
    tiers = sysconfig_models
    for tier, m in tiers.items():  # every configured model, so routing never hits a model that can't answer
        try:
            ping = await calls.structured(ctx.child(tier=tier), model=m, system="You are a health check.", schema=_Ping,
                                          prompt="Reply with answer='ready' and your confidence.", purpose="doctor",
                                          max_tokens=200)
            out.append(Check(f"Structured output: {tier}", ping.answer.strip().lower().startswith("ready"),
                             f"{m} answered '{ping.answer}'"))
        except AIOSError as e:
            fix = ("" if e.code == "missing_credentials" else
                   f"Your account may not have access to {m}. Change it with "
                   f"`aios config set routing.models '{{...}}'` or check model access in the Claude Console.")
            out.append(Check(f"Structured output: {tier}", False, e.message[:400], fix))
            return out
    out += await _other_providers(ctx)
    if not get_settings().web_search_enabled:
        out.append(Check("Web search", True, "disabled by AIOS_WEB_SEARCH=0 (research will be marked LOW confidence)"))
        return out
    before = ctx.spent_micros
    try:
        sr = await calls.web_research(ctx, model=model, system="You are a health check.", max_searches=1, max_tokens=400,
                                      prompt="Search the web once for 'Anthropic Claude' and name one result title.")
        ok = sr.live and bool(sr.results)
        out.append(Check("Web search", ok, f"{sr.searches} search(es), {len(sr.results)} results"
                         f" (${(ctx.spent_micros - before) / 1e6:.4f})" + (f"; {sr.error}" if sr.error else ""),
                         "" if ok else "Enable web search for your organization in the Claude Console, "
                                       "or set AIOS_WEB_SEARCH=0 to run research without it."))
    except AIOSError as e:
        out.append(Check("Web search", False, e.message[:300],
                         "Enable web search in the Claude Console, or set AIOS_WEB_SEARCH=0."))
    return out


async def _other_providers(ctx) -> list[Check]:
    """One tiny call to each extra provider that is connected (Muse, OpenAI, Ollama). Fractions of a cent."""
    from aios.core.errors import AIOSError
    from aios.llm import calls

    picks = {"muse": "muse-spark-1.3", "openai": "gpt-5.6-luna"}
    reg = ctx.providers
    out = []
    for name, model in picks.items():
        if name not in reg.providers:
            continue
        try:
            r = await calls.text(ctx.child(agent_id=f"doctor:{name}"), model=model, system="Health check.",
                                 prompt="Reply with the single word: ready", purpose="doctor", max_tokens=20)
            out.append(Check(f"Provider: {name}", "ready" in r.text().lower(), f"{model} answered '{r.text()[:40]}'"))
        except AIOSError as e:
            out.append(Check(f"Provider: {name}", False, e.message[:300], f"Check the key, or the model id {model} "
                             "(change multi.routes if your account uses a different one)."))
    if "ollama" in reg.providers:
        try:
            r = await calls.text(ctx.child(agent_id="doctor:ollama"), model="ollama/llama3.2", system="Health check.",
                                 prompt="Reply with the single word: ready", purpose="doctor", max_tokens=20)
            out.append(Check("Provider: ollama", bool(r.text()), "local model answered"))
        except AIOSError as e:
            out.append(Check("Provider: ollama", False, e.message[:200], "Start Ollama and run: ollama pull llama3.2"))
    return out


def run(sm: sessionmaker, with_live: bool) -> list[Check]:
    checks = offline(sm)
    if with_live:
        checks += asyncio.run(live(sm))
    return checks
