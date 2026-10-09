"""Multi-model orchestration: route a task to the right model(s), run them in parallel, reconcile.

    aios multi "task"                         auto: Jev (or keyword rules) picks the task type and whether
                                              it needs several opinions; models come from multi.routes
    aios multi "task" --models a,b,c          exactly these models, in parallel
    aios multi "task" --mode single|parallel  force one model or several

Every decision is recorded on the run: which models were connected, why each was picked, whether
the answer is direct (one model) or synthesized (several), each model's status, time and cost.

Data: only the task text (plus a short neutral system prompt) is sent. No company memory, finances
or files. The run lists which providers received it and whether it left the Mac.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from aios.core import sysconfig
from aios.core.errors import AIOSError, BudgetExceeded, MissingCredentials, ValidationFailed
from aios.llm import calls
from aios.llm.calls import CallContext, untrusted
from aios.llm.pricing import price_for
from aios.llm.provider import ProviderRegistry

CATEGORIES = {
    "writing": "Write or rewrite content: scripts, emails, posts, copy, outlines.",
    "research": "Find, explain or summarize information about the world.",
    "analysis": "Reason through a decision, trade-off, plan, numbers or strategy.",
    "code": "Write, fix or explain code or technical setup.",
    "quick": "A short factual answer, rewording, or simple transformation.",
}
_RULES = [
    ("code", r"\b(code|python|javascript|bug|error|function|script that|api|sql|regex|terminal)\b"),
    ("writing", r"\b(write|draft|rewrite|script|email|post|caption|headline|hook|outline|copy|tweet|newsletter)\b"),
    ("analysis", r"\b(should i|decide|compare|trade-?off|strategy|plan|pricing|which is better|pros and cons|worth it)\b"),
    ("research", r"\b(what is|who|research|find|explain|how does|latest|market|competitors?)\b"),
]
_NEEDS_MANY = r"\b(should i|decide|which is better|compare|best way|pros and cons|worth it|strategy|risky?)\b"

PROVIDER_INFO = {
    "anthropic": {"label": "Claude (Anthropic API)", "leaves_mac": True, "cost": "paid per token"},
    "muse": {"label": "Muse Spark (Meta Model API)", "leaves_mac": True, "cost": "paid per token; US public preview"},
    "openai": {"label": "ChatGPT models (OpenAI API)", "leaves_mac": True, "cost": "paid per token; ChatGPT Plus doesn't cover it"},
    "ollama": {"label": "Local model (Ollama)", "leaves_mac": False, "cost": "free"},
    "shortcuts": {"label": "macOS Shortcut", "leaves_mac": True,
                  "cost": "free; leaves the Mac if the shortcut uses ChatGPT or Apple's cloud model"},
}


@dataclass
class Plan:
    models: list[str]
    mode: str  # single | parallel
    category: str | None
    method: str  # founder | jev | rules
    reasons: list[str] = field(default_factory=list)
    available: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def is_connected(model: str, registry: ProviderRegistry, allowed_shortcuts: list[str]) -> tuple[bool, str]:
    name = registry.provider_name(model) or registry.default
    if name not in registry.providers:
        return False, f"{name} not set up"
    if name == "shortcuts" and model.split(":", 1)[1] not in allowed_shortcuts:
        return False, "shortcut not allowed yet (aios mac allow)"
    return True, "connected"


def catalog(session: Session, registry: ProviderRegistry) -> list[dict]:
    """Every model the routes mention or the founder pinned, with whether it can be used right now."""
    routes: dict[str, list[str]] = sysconfig.get(session, "multi.routes")
    allowed = sysconfig.get(session, "mac.allowed_shortcuts") or []
    seen: list[str] = []
    for lst in routes.values():
        seen += [m for m in lst if m not in seen]
    seen += [m for m in (sysconfig.get(session, "routing.agent_model_overrides") or {}).values() if m not in seen]
    seen += [f"shortcut:{n}" for n in allowed if f"shortcut:{n}" not in seen]
    out = []
    for m in seen:
        ok, why = is_connected(m, registry, allowed)
        prov = registry.provider_name(m) or registry.default
        p = price_for(m)
        out.append({"model": m, "provider": prov, "connected": ok, "status": why,
                    "leaves_mac": PROVIDER_INFO.get(prov, {}).get("leaves_mac", True),
                    "cost": PROVIDER_INFO.get(prov, {}).get("cost", "unknown"),
                    "price_per_mtok": None if p is None else {"input": p.input, "output": p.output}})
    return out


def classify_rules(request: str) -> tuple[str, bool, str]:
    low = request.lower()
    cat = next((c for c, rx in _RULES if re.search(rx, low)), "analysis")
    many = bool(re.search(_NEEDS_MANY, low))
    return cat, many, f"keyword rules → {cat}" + ("; looks like a judgment call → several opinions" if many else "")


async def classify_jev(request: str, jev, ctx: CallContext) -> tuple[str, bool, str]:
    ans = await jev.ask(request, {
        "kind": {"type": "choice", "instructions": "What kind of task is this?", "criteria": CATEGORIES},
        "many": {"type": "noul", "instructions": "Is this a judgment call where independent opinions from several "
                                                 "AI models would improve the answer (decisions, strategy, "
                                                 "trade-offs), rather than a task with one clear answer?"},
    })
    calls.record_external(ctx, model="jev-latest", provider="typesafe", purpose="routing",
                          input_tokens=ans.input_tokens, latency_ms=ans.latency_ms)
    kind = ans.answers.get("kind", {})
    many_p = float(ans.answers.get("many", {}).get("noul", 0))
    cat = kind.get("choice") if kind.get("choice") in CATEGORIES else "analysis"
    return cat, many_p >= 0.5, (f"Jev → {cat} (confidence {kind.get('confidence', 0):.2f}); "
                                f"several opinions: {many_p:.2f}")


async def plan(session: Session, registry: ProviderRegistry, request: str, ctx: CallContext, *,
               models: list[str] | None = None, mode: str = "auto", jev=None) -> Plan:
    allowed = sysconfig.get(session, "mac.allowed_shortcuts") or []
    cat_list = catalog(session, registry)
    available = [c for c in cat_list if c["connected"]]
    if models:
        bad = [(m, is_connected(m, registry, allowed)[1]) for m in models if not is_connected(m, registry, allowed)[0]]
        if bad:
            raise ValidationFailed("Not connected: " + "; ".join(f"{m} ({w})" for m, w in bad) + ". See `aios models`.")
        return Plan(models=models, mode="parallel" if len(models) > 1 else "single", category=None, method="founder",
                    reasons=[f"founder chose {', '.join(models)}"], available=available)
    reasons: list[str] = []
    method = "rules"
    cat, many, why = classify_rules(request)
    if jev is not None:
        try:
            cat, many, why = await classify_jev(request, jev, ctx)
            method = "jev"
        except AIOSError as e:
            reasons.append(f"Jev unavailable ({e.message[:80]}), used keyword rules")
    reasons.append(why)
    prefs = sysconfig.get(session, "multi.routes").get(cat) or []
    usable = [m for m in prefs if is_connected(m, registry, allowed)[0]]
    skipped = [{"model": m, "why": is_connected(m, registry, allowed)[1]} for m in prefs if m not in usable]
    if not usable:  # nothing preferred is connected: fall back to anything connected, cheapest first
        usable = sorted((c["model"] for c in available),
                        key=lambda m: (price_for(m).output if price_for(m) else 999))
        reasons.append(f"none of the preferred {cat} models are connected; using what is")
    if not usable:
        raise MissingCredentials("No model is connected. Run `aios models` to see how to connect one.")
    if mode == "single" or (mode == "auto" and not many):
        chosen, final_mode = usable[:1], "single"
        reasons.append(f"single model: {chosen[0]} is first in multi.routes[{cat}] among connected models")
    else:
        n = int(sysconfig.get(session, "multi.max_models"))
        chosen, final_mode = usable[:n], "parallel" if len(usable[:n]) > 1 else "single"
        reasons.append(f"{final_mode}: top {len(chosen)} connected models for {cat}")
    return Plan(models=chosen, mode=final_mode, category=cat, method=method, reasons=reasons, available=available,
                skipped=skipped)


SYSTEM = ("You are one of several AI models answering the same task for a solo founder. Answer directly and "
          "concretely. Plain language, no filler. If you are unsure of a fact, say so instead of guessing.")


async def ask_one(ctx: CallContext, model: str, request: str, timeout_s: float, max_tokens: int) -> dict[str, Any]:
    start = time.monotonic()
    c = ctx.child(task_key=f"multi:{model}", agent_id=f"multi:{model}"[:64])
    try:
        resp = await asyncio.wait_for(calls.text(c, model=model, system=SYSTEM, prompt=request, purpose="multi",
                                                 max_tokens=max_tokens), timeout_s)
        text = resp.text().strip()
        return {"model": model, "provider": resp.provider, "status": "ok" if text else "empty", "text": text,
                "elapsed_s": round(time.monotonic() - start, 1), "cost_usd": c.spent_micros / 1e6,
                "cut_off": resp.stop_reason == "max_tokens"}
    except BudgetExceeded:
        raise
    except TimeoutError:
        return {"model": model, "status": "timeout", "error": f"no answer within {timeout_s:.0f}s",
                "elapsed_s": round(time.monotonic() - start, 1), "cost_usd": c.spent_micros / 1e6}
    except AIOSError as e:
        return {"model": model, "status": "failed", "error": e.message[:300],
                "elapsed_s": round(time.monotonic() - start, 1), "cost_usd": c.spent_micros / 1e6}


async def run(ctx: CallContext, session_factory, registry: ProviderRegistry, request: str, *,
              models: list[str] | None = None, mode: str = "auto", jev=None, progress=lambda m: None) -> dict:
    from aios.agents.schemas import MultiSynthesis

    if not request.strip():
        raise ValidationFailed("Give the task to run.")
    with session_factory() as s:
        p = await plan(s, registry, request, ctx, models=models, mode=mode, jev=jev)
        timeout = float(sysconfig.get(s, "multi.timeout_s"))
        synth_model = sysconfig.get(s, "multi.synthesizer")
    progress(f"routing ({p.method}): {'; '.join(p.reasons)}")
    progress(f"asking {', '.join(p.models)}" + (" in parallel" if len(p.models) > 1 else ""))
    answers = await asyncio.gather(*(ask_one(ctx, m, request, timeout, 3000) for m in p.models))
    for a in answers:
        progress(f"{a['model']}: {a['status']} in {a['elapsed_s']}s (${a['cost_usd']:.4f})")
    good = [a for a in answers if a["status"] == "ok"]
    out: dict[str, Any] = {
        "routing": {"method": p.method, "category": p.category, "mode": p.mode, "reasons": p.reasons,
                    "models": p.models, "skipped": p.skipped,
                    "connected": [c["model"] for c in p.available]},
        "responses": answers,
        "data_sent": {"what": "the task text only (no memory, finances or files)",
                      "to": sorted({a.get("provider") or (registry.provider_name(a["model"]) or "") for a in answers}),
                      "left_mac": any(PROVIDER_INFO.get(registry.provider_name(m) or "", {}).get("leaves_mac", True)
                                      for m in p.models)},
    }
    if not good:
        raise AIOSError("Every model failed: " + "; ".join(f"{a['model']}: {a.get('error') or a['status']}"
                                                            for a in answers), **{"responses": answers})
    if len(good) == 1:
        out["result"] = {"kind": "direct", "model": good[0]["model"], "answer": good[0]["text"]}
        return out
    progress(f"reconciling {len(good)} answers with {synth_model}")
    blocks = "\n\n".join(untrusted(f"answer_from_{a['model']}", a["text"]) for a in good)
    try:
        syn = await calls.structured(ctx.child(task_key="multi:synthesis", agent_id="multi:synthesis"),
                                     model=synth_model, schema=MultiSynthesis, purpose="synthesis", max_tokens=4000,
                                     system="You reconcile answers from several AI models into one. Judge them on "
                                            "substance, not on which model wrote them. Never invent facts none of "
                                            "them gave; flag claims that need checking.",
                                     prompt=f"TASK:\n{untrusted('founder_request', request)}\n\nANSWERS:\n{blocks}")
        out["result"] = {"kind": "synthesized", "model": synth_model, **syn.model_dump()}
    except AIOSError as e:  # synthesis failed: still return every answer rather than nothing
        out["result"] = {"kind": "unsynthesized", "error": e.message[:300],
                         "answer": "Synthesis failed; the individual answers are below."}
    return out


SETUP = {
    "anthropic": "ANTHROPIC_API_KEY in .env (already used by the agents).",
    "muse": "Meta Model API key from https://dev.meta.ai → MODEL_API_KEY=... in .env. Paid per token "
            "($1.25 in / $4.25 out per million for muse-spark-1.3); US public preview.",
    "openai": "OpenAI API key from https://platform.openai.com/api-keys → OPENAI_API_KEY=... in .env. Paid per "
              "token; a ChatGPT Plus subscription does not include API use. Free alternative: the Shortcuts route.",
    "ollama": "Free and private: install https://ollama.com, run `ollama pull llama3.2`, then AIOS_OLLAMA=1 in .env.",
    "shortcuts": "Free: in the Shortcuts app make a shortcut named 'AIOS Ask ChatGPT' (Receive text input → "
                 "Use Model: ChatGPT with the input → Stop and output). Needs Apple Intelligence with the "
                 "ChatGPT extension on. Then: aios mac allow \"AIOS Ask ChatGPT\"",
    "typesafe": "Jev routes tasks (optional; keyword rules are used without it): TYPESAFE_API_KEY=... in .env. "
                "~$0.04 per million input tokens. New TypeSafe signups were paused 2026-09-22.",
}


def providers_status(session: Session, registry: ProviderRegistry) -> list[dict]:
    from aios.config import get_settings

    allowed = sysconfig.get(session, "mac.allowed_shortcuts") or []
    rows = []
    for name in ("anthropic", "muse", "openai", "ollama", "shortcuts"):
        connected = name in registry.providers and (name != "shortcuts" or bool(allowed))
        info = PROVIDER_INFO[name]
        rows.append({"provider": name, "label": info["label"], "connected": connected, "leaves_mac": info["leaves_mac"],
                     "cost": info["cost"], "setup": None if connected else SETUP[name],
                     "detail": (f"allowed shortcuts: {', '.join(allowed)}" if name == "shortcuts" and allowed else None)})
    jev = bool(get_settings().typesafe_api_key)
    rows.append({"provider": "typesafe", "label": "Jev (TypeSafe AI) — routing only", "connected": jev,
                 "leaves_mac": True, "cost": "~$0.04 per million input tokens", "setup": None if jev else SETUP["typesafe"],
                 "detail": "picks task type and single vs several models" if jev else "keyword rules used instead"})
    return rows
