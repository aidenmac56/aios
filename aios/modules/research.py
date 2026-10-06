"""Research library: reusable reports, sources, claims, freshness.

Sources are only stored if the search tool actually returned them. Claims pointing anywhere else
are kept as interpretation with LOW confidence and flagged.
"""

from __future__ import annotations

import re
from datetime import timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.agents.schemas import ResearchFinding
from aios.core import audit, events
from aios.core.actor import Actor
from aios.core.permissions import db_write, require
from aios.core.util import utcnow
from aios.db.enums import Confidence, Credibility
from aios.db.models import Claim, ResearchReport, Source
from aios.modules.memory import _terms


def question_key(q: str) -> str:
    return " ".join(sorted(_terms(q)))[:300]


def url_key(url: str) -> str:
    p = urlsplit(url.strip())
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.rstrip("/")
    return f"{host}{path}"[:500]


def refresh_staleness(session: Session) -> int:
    now = utcnow()
    n = 0
    for r in session.execute(select(ResearchReport).where(ResearchReport.stale.is_(False))).scalars():
        if r.created_at + timedelta(days=r.freshness_days) < now:
            r.stale = True
            n += 1
    session.flush()
    return n


def find_reusable(session: Session, question: str, min_overlap: float = 0.6) -> ResearchReport | None:
    refresh_staleness(session)
    terms = _terms(question)
    if not terms:
        return None
    best, best_score = None, 0.0
    for r in session.execute(select(ResearchReport).where(ResearchReport.stale.is_(False))).scalars():
        other = _terms(r.question)
        if not other:
            continue
        score = len(terms & other) / len(terms | other)
        if score > best_score:
            best, best_score = r, score
    return best if best_score >= min_overlap else None


def related(session: Session, text: str, limit: int = 5) -> list[ResearchReport]:
    refresh_staleness(session)
    terms = _terms(text)
    scored = []
    for r in session.execute(select(ResearchReport)).scalars():
        overlap = len(terms & _terms(r.question + " " + r.answer[:400]))
        if overlap >= 2:
            scored.append((overlap - (2 if r.stale else 0), r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored[:limit]]


def save(session: Session, actor: Actor, finding: ResearchFinding, *, allowed_urls: dict[str, dict], live: bool,
         workflow_run_id: str | None = None, project_id: str | None = None) -> tuple[ResearchReport, list[str]]:
    """Persist a research finding. Returns (report, problems found while enforcing source rules)."""
    require(actor, db_write("research"), action="save research")
    problems: list[str] = []
    confidence = finding.confidence
    if not live and confidence != "LOW":
        problems.append("No live search was available; confidence capped at LOW.")
        confidence = "LOW"
    report = ResearchReport(
        question=finding.question, question_key=question_key(finding.question),
        decision_supported=finding.decision_supported, subquestions=finding.subquestions, answer=finding.answer,
        confidence=Confidence(confidence), assumptions=finding.assumptions, disagreements=finding.disagreements,
        what_would_change=finding.what_would_change, live_search_used=live, freshness_days=finding.freshness_days,
        workflow_run_id=workflow_run_id, project_id=project_id, created_by_agent=actor.id or str(actor))
    session.add(report)
    session.flush()
    src_meta = {url_key(s.url): s for s in finding.sources}
    source_rows: dict[str, Source] = {}

    def source_for(url: str) -> Source | None:
        k = url_key(url)
        if k not in {url_key(u) for u in allowed_urls}:
            return None
        if k in source_rows:
            return source_rows[k]
        row = session.execute(select(Source).where(Source.url_key == k)).scalar_one_or_none()
        meta = src_meta.get(k)
        hit = next((v for u, v in allowed_urls.items() if url_key(u) == k), {})
        if row is None:
            row = Source(url=url, url_key=k, title=(meta.title if meta else None) or hit.get("title"),
                         publisher=meta.publisher if meta else urlsplit(url).netloc,
                         published_date=(meta.published if meta else None) or hit.get("page_age"),
                         accessed_at=utcnow(),
                         credibility=Credibility(meta.credibility) if meta else Credibility.MEDIUM,
                         kind=meta.kind if meta else "SECONDARY")
            session.add(row)
            session.flush()
        source_rows[k] = row
        return row

    for c in finding.claims:
        src = source_for(c.source_url) if c.source_url else None
        is_fact, conf = c.is_fact, c.confidence
        if c.source_url and src is None:
            problems.append(f"Claim cited a URL the search did not return; kept as unsupported: {c.text[:120]}")
            is_fact, conf = False, "LOW"
        elif c.is_fact and not c.source_url:
            problems.append(f"Fact without a source downgraded to interpretation: {c.text[:120]}")
            is_fact, conf = False, "LOW"
        session.add(Claim(report_id=report.id, source_id=src.id if src else None, text=c.text, is_fact=is_fact,
                          cited_text=c.cited_text, confidence=Confidence(conf)))
    for s in finding.sources:  # sources listed but not tied to a claim are still recorded if real
        source_for(s.url)
    session.flush()
    events.emit(session, events.RESEARCH_COMPLETED, str(actor), {"report_id": report.id, "live": live}, workflow_run_id)
    audit.record(session, who=str(actor), what="research.save", why=finding.decision_supported,
                 output={"report_id": report.id, "claims": len(finding.claims), "sources": len(source_rows),
                         "problems": problems[:10]},
                 tools_used=["web_search"] if live else [], target_type="research_report", target_id=report.id)
    return report, problems


def to_dict(r: ResearchReport, with_claims: bool = True) -> dict:
    d = {"id": r.id, "question": r.question, "decision_supported": r.decision_supported, "answer": r.answer,
         "confidence": r.confidence.value, "assumptions": r.assumptions, "disagreements": r.disagreements,
         "what_would_change": r.what_would_change, "live_search_used": r.live_search_used,
         "freshness_days": r.freshness_days, "stale": r.stale, "subquestions": r.subquestions,
         "created_by_agent": r.created_by_agent, "created_at": r.created_at.isoformat()}
    if with_claims:
        d["claims"] = [{"text": c.text, "is_fact": c.is_fact, "confidence": c.confidence.value,
                        "source": ({"url": c.source.url, "title": c.source.title, "publisher": c.source.publisher,
                                    "published": c.source.published_date, "credibility": c.source.credibility.value}
                                   if c.source else None)} for c in r.claims]
    return d


def brief(r: ResearchReport) -> str:
    """Compact form for prompts: answer + sourced claims with ids."""
    lines = [f"[research:{r.id} | confidence {r.confidence.value} | {'STALE' if r.stale else 'fresh'} | "
             f"{'live search' if r.live_search_used else 'no live search'}] Q: {r.question}", f"A: {r.answer}"]
    for c in r.claims[:12]:
        src = c.source.url if c.source else "unsourced interpretation"
        lines.append(f"  - {'FACT' if c.is_fact else 'INTERP'} ({c.confidence.value}): {c.text} [{src}]")
    return "\n".join(lines)


_slug = re.compile(r"[^a-z0-9]+")
