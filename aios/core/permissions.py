"""Least-privilege permissions.

Tiers: READ, RESEARCH, ANALYZE, DRAFT, LOCAL_EXECUTE, DATABASE_WRITE:<domain>, EXTERNAL_WRITE,
FINANCIAL_ACTION, SYSTEM_CHANGE. Agent permissions are declared in code (agents/specs.py). The
founder holds everything. No code path lets an agent grant itself a permission.
"""

from __future__ import annotations

from enum import StrEnum

from aios.core.actor import Actor
from aios.core.errors import PermissionDenied


class Perm(StrEnum):
    READ = "READ"
    RESEARCH = "RESEARCH"
    ANALYZE = "ANALYZE"
    DRAFT = "DRAFT"
    LOCAL_EXECUTE = "LOCAL_EXECUTE"
    DATABASE_WRITE = "DATABASE_WRITE"
    EXTERNAL_WRITE = "EXTERNAL_WRITE"
    FINANCIAL_ACTION = "FINANCIAL_ACTION"
    SYSTEM_CHANGE = "SYSTEM_CHANGE"


DOMAINS = {"research", "planning", "finance", "memory", "decisions", "audits", "improvements", "evaluations"}

# Permissions no agent may ever hold, whatever a config says.
NEVER_FOR_AGENTS = {Perm.FINANCIAL_ACTION.value, Perm.SYSTEM_CHANGE.value, Perm.EXTERNAL_WRITE.value}


def db_write(domain: str) -> str:
    if domain not in DOMAINS:
        raise ValueError(f"unknown domain {domain}")
    return f"{Perm.DATABASE_WRITE}:{domain}"


def agent_permissions(agent_id: str) -> set[str]:
    from aios.agents.specs import SPECS

    spec = SPECS.get(agent_id)
    if spec is None:
        return set()
    perms = set(spec.permissions)
    leaked = perms & NEVER_FOR_AGENTS
    if leaked:  # defensive: a spec edit must not silently hand out dangerous powers
        raise PermissionDenied(f"Agent spec for {agent_id} declares forbidden permissions {sorted(leaked)}")
    return perms


def has(actor: Actor, perm: str) -> bool:
    if actor.is_founder:
        return True
    if actor.kind == "system":
        # the engine itself: may write records on behalf of a run, never external/financial/system changes
        return perm not in NEVER_FOR_AGENTS
    return perm in agent_permissions(actor.id)


def require(actor: Actor, perm: str, *, action: str = "") -> None:
    if not has(actor, perm):
        raise PermissionDenied(f"{actor} lacks {perm}" + (f" for {action}" if action else ""), actor=str(actor), permission=perm)
