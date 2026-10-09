"""Sync agent specs into the database and resolve each agent's active, versioned configuration."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from aios.agents.specs import SPECS, AgentSpec
from aios.core import audit
from aios.db.enums import ModelTier
from aios.db.models import Agent, AgentConfigVersion


@dataclass
class ActiveConfig:
    spec: AgentSpec
    version: int
    system_prompt: str
    tier_override: str | None
    max_tokens: int


def sync_agents(session: Session) -> None:
    """Upsert descriptive fields from code. Never touches the active prompt version or `enabled`."""
    for spec in SPECS.values():
        row = session.get(Agent, spec.id)
        fields = dict(name=spec.name, title=spec.title, purpose=spec.purpose, responsibilities=spec.responsibilities,
                      authority=spec.authority, permissions=spec.permissions, tools=spec.tools, inputs=spec.inputs,
                      outputs=spec.outputs, escalation_rules=spec.escalation_rules,
                      default_tier=ModelTier(spec.default_tier), performance_measures=spec.performance_measures)
        if row is None:
            row = Agent(id=spec.id, enabled=True, active_config_version=1, **fields)
            session.add(row)
            session.flush()
        else:
            for k, v in fields.items():
                setattr(row, k, v)
        v1 = session.execute(select(AgentConfigVersion).where(
            AgentConfigVersion.agent_id == spec.id, AgentConfigVersion.version == 1)).scalar_one_or_none()
        if v1 is not None and v1.created_by == "system":
            # version 1 is the code seed: keep it equal to the code. Founder/agent versions (2+) are never touched.
            if v1.system_prompt != spec.system_prompt or (v1.config or {}).get("max_tokens") != spec.max_tokens:
                v1.system_prompt = spec.system_prompt
                v1.config = {**(v1.config or {}), "max_tokens": spec.max_tokens}
        if v1 is None:
            session.add(AgentConfigVersion(agent_id=spec.id, version=1, system_prompt=spec.system_prompt,
                                           config={"max_tokens": spec.max_tokens}, reason="initial version from code",
                                           created_by="system"))
    session.flush()


def active_config(session: Session, agent_id: str) -> ActiveConfig:
    spec = SPECS[agent_id]
    row = session.get(Agent, agent_id)
    version = row.active_config_version if row else 1
    cfg = session.execute(select(AgentConfigVersion).where(
        AgentConfigVersion.agent_id == agent_id, AgentConfigVersion.version == version)).scalar_one_or_none()
    if cfg is None:
        return ActiveConfig(spec, 1, spec.system_prompt, None, spec.max_tokens)
    return ActiveConfig(spec, version, cfg.system_prompt, (cfg.config or {}).get("tier"),
                        int((cfg.config or {}).get("max_tokens", spec.max_tokens)))


def config_for_version(session: Session, agent_id: str, version: int) -> ActiveConfig:
    """A specific (possibly inactive) version — used to benchmark a candidate before it goes live."""
    spec = SPECS[agent_id]
    cfg = session.execute(select(AgentConfigVersion).where(
        AgentConfigVersion.agent_id == agent_id, AgentConfigVersion.version == version)).scalar_one_or_none()
    if cfg is None:
        from aios.core.errors import NotFound

        raise NotFound(f"{agent_id} has no config version {version}")
    return ActiveConfig(spec, version, cfg.system_prompt, (cfg.config or {}).get("tier"),
                        int((cfg.config or {}).get("max_tokens", spec.max_tokens)))


def versions(session: Session, agent_id: str) -> list[dict]:
    row = session.get(Agent, agent_id)
    active = row.active_config_version if row else 1
    out = []
    for v in session.execute(select(AgentConfigVersion).where(AgentConfigVersion.agent_id == agent_id)
                             .order_by(AgentConfigVersion.version)).scalars():
        out.append({"version": v.version, "active": v.version == active, "reason": v.reason,
                    "expected_improvement": v.expected_improvement, "created_by": v.created_by,
                    "created_at": v.created_at.isoformat(), "rollback_to_version": v.rollback_to_version,
                    "test_results": v.test_results, "prompt_chars": len(v.system_prompt), "config": v.config})
    return out


def propose_version(session: Session, agent_id: str, *, system_prompt: str | None, config: dict | None,
                    reason: str, expected_improvement: str, created_by: str) -> AgentConfigVersion:
    """Store a candidate version. It does not become active until `activate_version` (founder only)."""
    current = active_config(session, agent_id)
    latest = session.execute(select(AgentConfigVersion.version).where(AgentConfigVersion.agent_id == agent_id)
                             .order_by(AgentConfigVersion.version.desc()).limit(1)).scalar() or 1
    v = AgentConfigVersion(agent_id=agent_id, version=latest + 1,
                           system_prompt=system_prompt or current.system_prompt,
                           config=config if config is not None else {"max_tokens": current.max_tokens},
                           reason=reason, expected_improvement=expected_improvement,
                           rollback_to_version=current.version, created_by=created_by)
    session.add(v)
    session.flush()
    audit.record(session, who=created_by, what="agent.version_proposed", why=reason,
                 input={"agent": agent_id, "from": current.version, "to": v.version},
                 target_type="agent", target_id=agent_id)
    return v


def activate_version(session: Session, agent_id: str, version: int, actor_str: str, approval_id: str | None,
                     why: str) -> None:
    if not actor_str.startswith("founder"):
        from aios.core.errors import PermissionDenied

        raise PermissionDenied("Only the founder can activate an agent configuration.")
    config_for_version(session, agent_id, version)  # must exist
    row = session.get(Agent, agent_id)
    old = row.active_config_version
    row.active_config_version = version
    audit.record(session, who=actor_str, what="agent.version_activated", why=why, approval_id=approval_id,
                 input={"agent": agent_id, "old_version": old, "new_version": version},
                 output={"rollback": f"activate version {old}"}, target_type="agent", target_id=agent_id)
