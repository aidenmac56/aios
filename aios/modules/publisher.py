"""Publishing: the system prepares, the founder sends.

    aios publish newsletter --run <id>   send one drafted issue (founder action, via Kit)
    aios links set booking https://...   links substituted into anything published

Publishing is an EXTERNAL_WRITE: agents and autopilot never do it. Autopilot drafts the weekly issue and
runs `preflight` (no sending): parsed from a draft with exact labels (Subject line / Preview text /
Issue body), checked by code (no [placeholders], booking link present, sane length) and by a model (no
unverified claims stated as fact, nothing embarrassing). Then it puts the one-line send command on the
founder's to-do list. The send runs the same checks again and refuses if they fail.
"""

from __future__ import annotations

import html as htmlmod
import re
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from aios.config import get_settings
from aios.core import audit, sysconfig
from aios.core.actor import Actor
from aios.core.errors import AIOSError, PermissionDenied, ValidationFailed
from aios.core.util import utcnow
from aios.db.models import WorkflowRun

def links(session: Session) -> dict[str, str]:
    return dict(sysconfig.get(session, "links") or {})


# ------------------------------------------------------------------------------------------- parse + check


def issue_from_run(session: Session, run_id: str) -> dict[str, str]:
    run = session.get(WorkflowRun, run_id)
    items = (((run.result or {}).get("draft") or {}).get("items") or []) if run else []
    found: dict[str, str] = {}
    for it in items:
        label = it.get("label", "").lower()
        key = "subject" if "subject" in label else "preview" if "preview" in label else "body" if (
            "body" in label or "issue" in label) else None
        if key and key not in found:
            found[key] = it.get("text", "").strip()
    missing = [k for k in ("subject", "preview", "body") if not found.get(k)]
    if missing:
        raise ValidationFailed(f"The draft is missing {', '.join(missing)} (needs items labeled Subject line, "
                               "Preview text, Issue body).", run_id=run_id)
    return found


_PLACEHOLDER = re.compile(r"\[(?:[^\]]*(?:link|url|name|insert|todo|tbd|placeholder)[^\]]*)\]|\bTBD\b|\bXX+\b", re.I)


def fill_links(text: str, lk: dict[str, str]) -> str:
    for name, url in lk.items():
        text = re.sub(rf"\[{re.escape(name)}(?: link| url)?\]", url, text, flags=re.I)
    return text


def code_checks(issue: dict[str, str], lk: dict[str, str]) -> list[str]:
    problems = []
    for k, v in issue.items():
        if _PLACEHOLDER.search(v):
            problems.append(f"{k} still has a placeholder: {_PLACEHOLDER.search(v).group(0)}")
    if lk.get("booking") and lk["booking"] not in issue["body"]:
        problems.append("the booking link isn't in the issue")
    words = len(issue["body"].split())
    if not 80 <= words <= 900:
        problems.append(f"body is {words} words (expected 80-900)")
    if len(issue["subject"]) > 120:
        problems.append("subject line is over 120 characters")
    return problems


class PublishCheck(BaseModel):
    verdict: Literal["SEND", "HOLD"]
    reasons: list[str] = Field(default_factory=list, description="Why, in short sentences (at most 5).")


async def model_check(sm: sessionmaker, providers, issue: dict[str, str]) -> PublishCheck:
    from aios.core.budget import BudgetGuard, Limits
    from aios.llm import calls
    from aios.llm.calls import CallContext, untrusted

    with sm() as s:
        model = sysconfig.get(s, "routing.models")["BALANCED"]
        guard = BudgetGuard(sm, Limits.load(s, workflow_override_usd=0.25))
    ctx = CallContext(sm=sm, providers=providers, budget=guard, workflow="publish", agent_id="risk")
    return await calls.structured(
        ctx, model=model, schema=PublishCheck, purpose="publish_check", max_tokens=800,
        system=("You are the last check before an email goes to real subscribers under the founder's name. "
                "HOLD if it states unverified things as certain, invents numbers or quotes, could embarrass him, "
                "makes promises he can't keep, or reads as spam. Otherwise SEND. Don't nitpick style."),
        prompt=untrusted("newsletter_issue", f"Subject: {issue['subject']}\nPreview: {issue['preview']}\n\n{issue['body']}"))


def to_html(body: str) -> str:
    out = []
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = [htmlmod.escape(x) for x in block.strip().splitlines()]
        text = "<br>".join(lines)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', text)
        if re.match(r"^\d+\.\s", block.strip()) and len(lines) == 1:
            out.append(f"<h3>{text}</h3>")
        else:
            out.append(f"<p>{text}</p>")
    return "\n".join(out)


# ------------------------------------------------------------------------------------------- send


async def preflight(sm: sessionmaker, providers, run_id: str) -> dict[str, Any]:
    """Everything except sending. Safe for autopilot: no external write."""
    with sm() as s:
        lk = links(s)
        try:
            issue = {k: fill_links(v, lk) for k, v in issue_from_run(s, run_id).items()}
        except ValidationFailed as e:
            return {"ok": False, "problems": [e.message], "run_id": run_id}
    problems = code_checks(issue, lk)
    check = None
    if not problems:
        check = await model_check(sm, providers, issue)
        if check.verdict == "HOLD":
            problems = [f"review: {r}" for r in check.reasons] or ["review said hold"]
    return {"ok": not problems, "problems": problems, "issue": issue, "run_id": run_id,
            "check": check.model_dump() if check else None}


async def publish_newsletter(sm: sessionmaker, providers, run_id: str, *, actor: Actor, kit=None,
                             send_in_minutes: float = 5, force: bool = False) -> dict[str, Any]:
    """Founder sends one drafted issue via Kit. Checks run again first; failures don't send."""
    from aios.integrations.kit import KitClient

    if not actor.is_founder:
        raise PermissionDenied("Only the founder can publish.", actor=str(actor))
    pre = await preflight(sm, providers, run_id)
    if not pre["ok"] and not (force and "issue" in pre):
        with sm() as s:
            audit.record(s, who=str(actor), what="publish.hold", why="; ".join(pre["problems"])[:500],
                         target_type="workflow_run", target_id=run_id, result="HELD")
            s.commit()
        return {"sent": False, **pre}
    issue = pre["issue"]
    kit = kit or KitClient(get_settings().kit_api_key)
    send_at = utcnow() + timedelta(minutes=max(1.0, send_in_minutes))
    b = kit.create_broadcast(subject=issue["subject"], preview_text=issue["preview"], html=to_html(issue["body"]),
                             send_at=send_at, description=f"AIOS draft run {run_id[:8]}")
    with sm() as s:
        audit.record(s, who=str(actor), what="publish.newsletter", why="weekly issue" + (" (forced)" if force else ""),
                     input={"subject": issue["subject"], "run_id": run_id},
                     output={"broadcast_id": b.get("id"), "send_at": send_at.isoformat()}, tools_used=["kit"],
                     target_type="workflow_run", target_id=run_id)
        s.commit()
    return {"sent": True, "broadcast_id": b.get("id"), "send_at": send_at.isoformat() + "Z",
            "subject": issue["subject"], "problems": pre["problems"]}
