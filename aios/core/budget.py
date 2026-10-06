"""Budget controls: task, workflow, daily, per-agent and per-model limits.

Checked with a *projected* cost before every model call. When a limit would be crossed the call is
not made; the orchestrator stops and returns what is already finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from aios.core import sysconfig
from aios.core.errors import BudgetExceeded
from aios.core.util import micros_to_usd, usd_to_micros, utcnow
from aios.db.models import ModelUsage


@dataclass
class Limits:
    task: int
    workflow: int
    daily: int
    agent_daily: int
    model_daily: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, session: Session, workflow_override_usd: float | None = None) -> Limits:
        g = lambda k: sysconfig.get(session, k)  # noqa: E731
        return cls(
            task=usd_to_micros(g("budget.task_limit_usd")),
            workflow=usd_to_micros(workflow_override_usd if workflow_override_usd is not None else g("budget.workflow_limit_usd")),
            daily=usd_to_micros(g("budget.daily_limit_usd")),
            agent_daily=usd_to_micros(g("budget.agent_daily_limit_usd")),
            model_daily={m: usd_to_micros(v) for m, v in (g("budget.model_daily_limit_usd") or {}).items()},
        )


def _day_start() -> datetime:
    now = utcnow()
    return datetime.combine(now.date(), time.min)


def spent_today(session: Session, *, agent_id: str | None = None, model: str | None = None) -> int:
    q = select(func.coalesce(func.sum(ModelUsage.estimated_cost_micros), 0)).where(ModelUsage.created_at >= _day_start())
    if agent_id:
        q = q.where(ModelUsage.agent_id == agent_id)
    if model:
        q = q.where(ModelUsage.model == model)
    return int(session.execute(q).scalar() or 0)


class BudgetGuard:
    """One per workflow run. Thread-unsafe by design: the orchestrator runs on one event loop."""

    def __init__(self, sm: sessionmaker, limits: Limits, workflow_run_id: str | None = None):
        self.sm = sm
        self.limits = limits
        self.workflow_run_id = workflow_run_id
        self.workflow_spent = 0
        self.task_spent: dict[str, int] = {}

    @property
    def remaining_ratio(self) -> float:
        if self.limits.workflow <= 0:
            return 0.0
        return max(0.0, 1 - self.workflow_spent / self.limits.workflow)

    def check(self, *, agent_id: str, model: str, projected: int, task_key: str | None = None) -> None:
        def stop(scope: str, limit: int, spent: int):
            raise BudgetExceeded(
                f"{scope} budget would be exceeded: spent ${micros_to_usd(spent):.4f} + projected "
                f"${micros_to_usd(projected):.4f} > limit ${micros_to_usd(limit):.4f}",
                scope=scope, limit_usd=micros_to_usd(limit), spent_usd=micros_to_usd(spent),
                projected_usd=micros_to_usd(projected), agent=agent_id, model=model,
            )

        if task_key is not None:
            t = self.task_spent.get(task_key, 0)
            if t + projected > self.limits.task:
                stop("task", self.limits.task, t)
        if self.workflow_spent + projected > self.limits.workflow:
            stop("workflow", self.limits.workflow, self.workflow_spent)
        with self.sm() as s:
            day = spent_today(s)
            if day + projected > self.limits.daily:
                stop("daily", self.limits.daily, day)
            a = spent_today(s, agent_id=agent_id)
            if a + projected > self.limits.agent_daily:
                stop(f"agent:{agent_id} daily", self.limits.agent_daily, a)
            if model in self.limits.model_daily:
                m = spent_today(s, model=model)
                if m + projected > self.limits.model_daily[model]:
                    stop(f"model:{model} daily", self.limits.model_daily[model], m)

    def add(self, micros: int, task_key: str | None = None) -> None:
        self.workflow_spent += micros
        if task_key is not None:
            self.task_spent[task_key] = self.task_spent.get(task_key, 0) + micros
