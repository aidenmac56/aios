"""Bring the system up: migrate, sync agents and metrics, register approval handlers."""

from __future__ import annotations

import logging

from sqlalchemy.orm import sessionmaker

from aios.agents.registry import sync_agents
from aios.config import get_settings
from aios.core import approvals
from aios.db.base import session_factory
from aios.db.migrate import upgrade
from aios.modules import decisions, improvements, metrics, planning

_registered = False


def register_handlers() -> None:
    global _registered
    if _registered:
        return
    approvals.register("decision.approve", decisions.on_approved, decisions.on_rejected)
    approvals.register("plan.activate", planning.activate_project, planning.cancel_project_on_reject)
    approvals.register("improvement.implement", improvements.on_approved, improvements.on_rejected)
    _registered = True


def init(url: str | None = None) -> sessionmaker:
    logging.basicConfig(level=get_settings().log_level, format="%(levelname)s %(name)s: %(message)s")
    url = url or get_settings().database_url
    upgrade(url)
    sm = session_factory(url)
    with sm() as s:
        sync_agents(s)
        metrics.sync_registry(s)
        s.commit()
    register_handlers()
    return sm
