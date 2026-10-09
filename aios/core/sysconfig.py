"""System configuration stored in the database, with code defaults.

Changing configuration is a SYSTEM_CHANGE: agents cannot do it; the founder can, and every change
is written to the audit log with the old and new value.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from aios.core import audit
from aios.core.actor import Actor
from aios.core.errors import PermissionDenied
from aios.core.util import utcnow
from aios.db.models import SystemConfiguration

DEFAULTS: dict[str, tuple[Any, str]] = {
    "budget.task_limit_usd": (0.75, "Max estimated AI cost for one agent task."),
    "budget.workflow_limit_usd": (4.00, "Max AI cost for one workflow run."),
    "budget.daily_limit_usd": (15.00, "Max AI cost per UTC day across everything."),
    "budget.agent_daily_limit_usd": (6.00, "Max AI cost per agent per UTC day."),
    "budget.model_daily_limit_usd": ({}, "Optional per-model daily caps, e.g. {\"claude-opus-5-5\": 8}."),
    "routing.models": (
        {"FAST": "claude-haiku-4-5-20251001", "BALANCED": "claude-sonnet-5-5", "DEEP": "claude-opus-5-5"},
        "Model used for each tier.",
    ),
    "routing.agent_model_overrides": ({}, "Run an agent on a specific model from any connected provider, e.g. "
                                          "{\"cmo\": \"muse-spark-1.3\"}. See `aios models` for what's connected."),
    "routing.agent_tier_overrides": ({}, "Force a tier for an agent, e.g. {\"research\": \"BALANCED\"}."),
    "routing.equivalence_margin": (0.03, "If a cheaper model's eval score is within this margin, prefer it."),
    "routing.min_eval_cases": (3, "Evaluations needed before eval history can change routing."),
    "routing.auto_apply_eval_history": (False, "If true, routing switches to a cheaper model as soon as benchmarks show "
                                               "it is equivalent. If false (default), that becomes an improvement you "
                                               "test and approve."),
    "routing.downgrade_when_budget_below": (0.25, "Downgrade one tier when this share of the workflow budget remains."),
    "orchestrator.max_tasks_per_workflow": (8, "Upper bound on agent tasks in one plan."),
    "orchestrator.max_parallel": (4, "Max agent tasks running at once."),
    "orchestrator.output_retries": (1, "Retries when output fails validation."),
    "orchestrator.api_retries": (2, "Retries on transient API errors."),
    "orchestrator.max_output_tokens": (8000, "Default max output tokens per agent call."),
    "research.default_freshness_days": (30, "Days before a research report is flagged stale."),
    "research.max_searches": (6, "Max web searches per research call."),
    "memory.confirm_threshold": (3, "Supporting founder decisions needed to promote INFERRED to CONFIRMED."),
    "finance.categories": (
        {
            "revenue": ["stripe payout", "invoice", "payment from", "deposit - client", "client payment", "consulting"],
            "ai_tools": ["anthropic", "openai", "chatgpt", "claude.ai", "elevenlabs", "heygen", "higgsfield",
                          "midjourney", "opusclip", "vidiq", "perplexity", "runway"],
            "software": ["notion", "google workspace", "gsuite", "beehiiv", "calendly", "cal.com", "canva",
                          "capcut", "adobe", "github", "vercel", "metricool", "zapier", "make.com", "slack"],
            "infrastructure": ["aws", "amazon web services", "gcp", "google cloud", "digitalocean", "cloudflare", "render.com"],
            "marketing": ["facebook ads", "meta ads", "google ads", "tiktok ads", "linkedin ads", "fiverr", "upwork"],
            "rent": ["rent", "property management", "leasing"],
            "transfer": ["transfer to", "transfer from", "zelle to self", "internal transfer", "credit card payment"],
        },
        "Keyword rules for transaction categories. First match wins; 'transfer' is excluded from revenue/expense.",
    ),
    "finance.cogs_categories": ([], "Expense categories counted as cost of goods sold for gross margin."),
    "multi.routes": (
        {"writing": ["muse-spark-1.3", "gpt-5.6-terra", "shortcut:AIOS Ask ChatGPT", "claude-sonnet-5-5"],
         "research": ["claude-sonnet-5-5", "gpt-5.6-terra", "muse-spark-1.3"],
         "analysis": ["claude-opus-5-5", "gpt-5.6-terra", "muse-spark-1.3"],
         "code": ["claude-sonnet-5-5", "gpt-5.6-terra", "muse-spark-1.3"],
         "quick": ["ollama/llama3.2", "shortcut:AIOS Ask ChatGPT", "gpt-5.6-luna", "claude-haiku-4-5-20251001"]},
        "Preferred models per task type, best first. Only connected models are used. These are starting "
        "guesses: compare results with `aios multi --models a,b` and reorder."),
    "multi.max_models": (3, "Most models asked at once in parallel mode."),
    "multi.synthesizer": ("claude-sonnet-5-5", "Model that reconciles parallel answers into one."),
    "multi.timeout_s": (180, "Per-model timeout in a multi-model run."),
    "mac.allowed_shortcuts": ([], "macOS shortcuts AIOS may run (exact names). Founder-only; each run is audited."),
    "media.dir": ("data/media", "Where studio files are stored (relative to the repo root). Git-ignored."),
    "media.tts_model": ("turbo", "Chatterbox model: 'turbo' (English, fastest) or 'original'."),
    "media.tts_device": ("auto", "Where speech is generated: auto (Apple GPU 'mps' if present), mps, cuda or cpu."),
    "media.lipsync_model": ("bytedance/latentsync", "Replicate model used to lip-sync your face to the generated voice."),
    "media.lipsync_usd_per_second": (0.000975, "Replicate's price per GPU-second for that model's hardware (Nvidia L40S, "
                                               "replicate.com/pricing, checked 2026-10-09). Used to record the cost."),
    "media.lipsync_projected_usd": (0.30, "Cost assumed before a lip-sync run, for the budget check."),
    "media.lipsync_max_seconds": (180, "Longest audio the avatar step accepts in one run (cost guard)."),
    "founder.principles": ([],"Founder principles the planner checks against, e.g. {\"key\":\"preserve_cash\"}."),
}


def get(session: Session, key: str) -> Any:
    row = session.get(SystemConfiguration, key)
    if row is not None:
        return copy.deepcopy(row.value)
    if key in DEFAULTS:
        return copy.deepcopy(DEFAULTS[key][0])
    raise KeyError(key)


def set_value(session: Session, key: str, value: Any, actor: Actor, why: str) -> None:
    if not actor.is_founder:
        raise PermissionDenied("Only the founder can change system configuration directly; agents must propose an improvement.",
                               key=key, actor=str(actor))
    old = None
    row = session.get(SystemConfiguration, key)
    if row is None:
        old = DEFAULTS.get(key, (None, ""))[0]
        row = SystemConfiguration(key=key, description=DEFAULTS.get(key, (None, ""))[1])
        session.add(row)
    else:
        old = row.value
    row.value = value
    row.updated_at = utcnow()
    row.updated_by = str(actor)
    audit.record(session, who=str(actor), what="config.set", why=why, input={"key": key, "old": old, "new": value},
                 target_type="system_configuration", target_id=key)


def all_config(session: Session) -> dict[str, dict]:
    out = {k: {"value": v, "description": d, "source": "default"} for k, (v, d) in DEFAULTS.items()}
    for row in session.query(SystemConfiguration).all():
        out[row.key] = {"value": row.value, "description": row.description or out.get(row.key, {}).get("description"),
                        "source": "database", "updated_by": row.updated_by,
                        "updated_at": row.updated_at.isoformat() if row.updated_at else None}
    return out
