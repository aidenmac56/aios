"""The schema. The database is the authoritative source for durable company facts.

Money is integer cents. AI cost is integer micro-dollars. Timestamps are naive UTC.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aios.db.base import Base, IdMixin, TimestampMixin, enum_col
from aios.db.enums import (
    ApprovalStatus,
    ApprovalType,
    AuditVerdict,
    Confidence,
    Credibility,
    DecisionStatus,
    ForecastKind,
    ImprovementStatus,
    MediaKind,
    MediaStatus,
    MemoryCategory,
    MemoryStatus,
    ModelTier,
    ProjectStatus,
    Provenance,
    RunStatus,
    TaskKind,
    TaskStatus,
    TxnStatus,
)

# ---------------------------------------------------------------- founder + memory


class Founder(IdMixin, TimestampMixin, Base):
    __tablename__ = "founders"
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")


class Memory(IdMixin, TimestampMixin, Base):
    __tablename__ = "memories"
    founder_id: Mapped[str | None] = mapped_column(ForeignKey("founders.id"), index=True)
    category: Mapped[MemoryCategory] = mapped_column(enum_col(MemoryCategory), index=True)
    subject: Mapped[str] = mapped_column(String(200), index=True)  # e.g. "risk_preference"
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[MemoryStatus] = mapped_column(enum_col(MemoryStatus), index=True)
    provenance: Mapped[Provenance] = mapped_column(enum_col(Provenance))
    source_ref: Mapped[str | None] = mapped_column(Text)  # where exactly: chat, decision id, url
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_by: Mapped[str] = mapped_column(String(64))  # "founder" | agent id | "system"
    superseded_by_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id"))
    last_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("ix_memories_active", "category", "status"),
    )


class MemoryEvidence(IdMixin, TimestampMixin, Base):
    __tablename__ = "memory_evidence"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id"), index=True)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # SUPPORTS | CONTRADICTS
    note: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (CheckConstraint("kind IN ('SUPPORTS','CONTRADICTS')", name="kind"),)


# ---------------------------------------------------------------- company + planning


class Company(IdMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    name: Mapped[str] = mapped_column(String(200))
    vision: Mapped[str | None] = mapped_column(Text)
    mission: Mapped[str | None] = mapped_column(Text)
    strategy: Mapped[str | None] = mapped_column(Text)
    business_model: Mapped[str | None] = mapped_column(Text)
    products: Mapped[list] = mapped_column(JSON, default=list)
    customers: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class Goal(IdMixin, TimestampMixin, Base):
    __tablename__ = "goals"
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    horizon: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    objectives: Mapped[list[Objective]] = relationship(back_populates="goal")


class Objective(IdMixin, TimestampMixin, Base):
    __tablename__ = "objectives"
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("goals.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    metric: Mapped[str | None] = mapped_column(String(300))
    target: Mapped[str | None] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"))
    goal: Mapped[Goal | None] = relationship(back_populates="objectives")


class Initiative(IdMixin, TimestampMixin, Base):
    __tablename__ = "initiatives"
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")


class Project(IdMixin, TimestampMixin, Base):
    __tablename__ = "projects"
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"), index=True)
    objective_id: Mapped[str | None] = mapped_column(ForeignKey("objectives.id"), index=True)
    initiative_id: Mapped[str | None] = mapped_column(ForeignKey("initiatives.id"), index=True)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    objective: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    expected_impact: Mapped[str | None] = mapped_column(Text)
    owner: Mapped[str] = mapped_column(String(64), default="founder")
    status: Mapped[ProjectStatus] = mapped_column(enum_col(ProjectStatus), default=ProjectStatus.PROPOSED, index=True)
    priority: Mapped[int] = mapped_column(Integer, default=3)  # 1 highest .. 5 lowest
    expected_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    estimated_effort_hours: Mapped[float | None] = mapped_column(Float)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    blockers: Mapped[list] = mapped_column(JSON, default=list)
    success_criteria: Mapped[list] = mapped_column(JSON, default=list)
    related_research_ids: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),)


class ProjectDependency(Base):
    __tablename__ = "project_dependencies"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    __table_args__ = (CheckConstraint("project_id <> depends_on_id", name="no_self"),)


class Milestone(IdMixin, TimestampMixin, Base):
    __tablename__ = "milestones"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    due_date: Mapped[date | None] = mapped_column(Date)
    success_criteria: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="PLANNED")
    order: Mapped[int] = mapped_column(Integer, default=0)


class Task(IdMixin, TimestampMixin, Base):
    __tablename__ = "tasks"
    kind: Mapped[TaskKind] = mapped_column(enum_col(TaskKind), default=TaskKind.PLAN, index=True)
    title: Mapped[str] = mapped_column(String(400))
    description: Mapped[str | None] = mapped_column(Text)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"), index=True)
    milestone_id: Mapped[str | None] = mapped_column(ForeignKey("milestones.id"), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    objective: Mapped[str | None] = mapped_column(Text)
    responsible_agent: Mapped[str | None] = mapped_column(String(64))
    creator: Mapped[str] = mapped_column(String(64), default="founder")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[TaskStatus] = mapped_column(enum_col(TaskStatus), default=TaskStatus.PROPOSED, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    estimated_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    actual_cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_micros: Mapped[int | None] = mapped_column(BigInteger)  # AI work items
    actual_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    completion_criteria: Mapped[str | None] = mapped_column(Text)
    criteria_met: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict | None] = mapped_column(JSON)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    approval_state: Mapped[str | None] = mapped_column(String(32))
    due_date: Mapped[date | None] = mapped_column(Date)
    estimated_effort_hours: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
        # a PLAN task may only be COMPLETED when its completion criteria were marked met
        CheckConstraint(
            "kind <> 'PLAN' OR status <> 'COMPLETED' OR criteria_met = 1", name="completed_needs_criteria"
        ),
    )


class TaskDependency(Base):
    __tablename__ = "task_dependencies"
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), primary_key=True)
    __table_args__ = (CheckConstraint("task_id <> depends_on_id", name="no_self"),)


# ---------------------------------------------------------------- agents + execution


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # "ceo", "cfo", ...
    name: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(200))
    purpose: Mapped[str] = mapped_column(Text)
    responsibilities: Mapped[list] = mapped_column(JSON, default=list)
    authority: Mapped[str] = mapped_column(Text)
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    tools: Mapped[list] = mapped_column(JSON, default=list)
    inputs: Mapped[str] = mapped_column(Text)
    outputs: Mapped[str] = mapped_column(Text)
    escalation_rules: Mapped[list] = mapped_column(JSON, default=list)
    default_tier: Mapped[ModelTier] = mapped_column(enum_col(ModelTier))
    performance_measures: Mapped[list] = mapped_column(JSON, default=list)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active_config_version: Mapped[int] = mapped_column(Integer, default=1)


class AgentConfigVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_config_versions"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    system_prompt: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSON, default=dict)  # tier override, max_tokens, temperature
    reason: Mapped[str] = mapped_column(Text)
    expected_improvement: Mapped[str | None] = mapped_column(Text)
    test_results: Mapped[dict | None] = mapped_column(JSON)
    rollback_to_version: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[str] = mapped_column(String(64))
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"))
    __table_args__ = (UniqueConstraint("agent_id", "version", name="uq_agent_version"),)


class WorkflowRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_runs"
    command: Mapped[str] = mapped_column(String(64), index=True)
    request: Mapped[str] = mapped_column(Text)
    actor: Mapped[str] = mapped_column(String(64), default="founder")
    status: Mapped[RunStatus] = mapped_column(enum_col(RunStatus), default=RunStatus.PENDING, index=True)
    importance: Mapped[str] = mapped_column(String(16), default="normal")
    understanding: Mapped[dict | None] = mapped_column(JSON)
    plan: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    progress: Mapped[list] = mapped_column(JSON, default=list)
    total_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    budget_limit_micros: Mapped[int | None] = mapped_column(BigInteger)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    # plain id (decisions.workflow_run_id is the FK side; avoids a circular constraint)
    decision_id: Mapped[str | None] = mapped_column(String(32), index=True)


class AgentRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), index=True)
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), index=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[RunStatus] = mapped_column(enum_col(RunStatus), default=RunStatus.PENDING, index=True)
    objective: Mapped[str] = mapped_column(Text)
    output: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    retries: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    model: Mapped[str | None] = mapped_column(String(80))
    tier: Mapped[str | None] = mapped_column(String(16))
    routing_reason: Mapped[str | None] = mapped_column(Text)


class ModelUsage(IdMixin, TimestampMixin, Base):
    __tablename__ = "model_usage"
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(64), index=True)
    workflow: Mapped[str | None] = mapped_column(String(64), index=True)
    purpose: Mapped[str | None] = mapped_column(String(64))  # "analysis", "structure", "search", "eval"
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(80), index=True)
    tier: Mapped[str | None] = mapped_column(String(16))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    web_search_requests: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    actual_cost_micros: Mapped[int | None] = mapped_column(BigInteger)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    pricing_version: Mapped[str | None] = mapped_column(String(32))


class ToolCall(IdMixin, TimestampMixin, Base):
    __tablename__ = "tool_calls"
    agent_run_id: Mapped[str | None] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(80))
    input: Mapped[dict | None] = mapped_column(JSON)
    output_summary: Mapped[str | None] = mapped_column(Text)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)


# ---------------------------------------------------------------- finance


class Account(IdMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    kind: Mapped[str] = mapped_column(String(32), default="CHECKING")  # CHECKING|SAVINGS|CREDIT|CASH|PROCESSOR
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    opening_balance_cents: Mapped[int | None] = mapped_column(BigInteger)  # only if the founder provides it
    opening_balance_date: Mapped[date | None] = mapped_column(Date)


class Vendor(IdMixin, TimestampMixin, Base):
    __tablename__ = "vendors"
    name: Mapped[str] = mapped_column(String(200), unique=True)
    category: Mapped[str | None] = mapped_column(String(64))
    is_ai_provider: Mapped[bool] = mapped_column(Boolean, default=False)


class CostCenter(IdMixin, TimestampMixin, Base):
    __tablename__ = "cost_centers"
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str | None] = mapped_column(Text)


class ImportBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"
    filename: Mapped[str] = mapped_column(String(300))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[list] = mapped_column(JSON, default=list)
    imported_by: Mapped[str] = mapped_column(String(64), default="founder")


class Transaction(IdMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"), index=True)
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(Text)
    amount_cents: Mapped[int] = mapped_column(BigInteger)  # + inflow, - outflow
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    category: Mapped[str] = mapped_column(String(64), default="uncategorized", index=True)
    category_source: Mapped[str] = mapped_column(String(16), default="RULE")  # RULE|FOUNDER|IMPORT
    is_revenue: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_transfer: Mapped[bool] = mapped_column(Boolean, default=False)  # excluded from revenue/expense
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    cost_center_id: Mapped[str | None] = mapped_column(ForeignKey("cost_centers.id"))
    status: Mapped[TxnStatus] = mapped_column(enum_col(TxnStatus), default=TxnStatus.ACTUAL, index=True)
    source: Mapped[Provenance] = mapped_column(enum_col(Provenance), default=Provenance.FINANCIAL_IMPORT)
    import_batch_id: Mapped[str | None] = mapped_column(ForeignKey("import_batches.id"), index=True)
    external_id: Mapped[str | None] = mapped_column(String(200))
    dedupe_hash: Mapped[str] = mapped_column(String(64), unique=True)
    note: Mapped[str | None] = mapped_column(Text)
    vendor: Mapped[Vendor | None] = relationship()


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"
    vendor_id: Mapped[str | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    interval: Mapped[str] = mapped_column(String(16), default="MONTHLY")
    status: Mapped[str] = mapped_column(String(16), default="ACTIVE")
    source: Mapped[str] = mapped_column(String(16), default="DETECTED")  # DETECTED|FOUNDER
    last_charge_date: Mapped[date | None] = mapped_column(Date)
    next_charge_date: Mapped[date | None] = mapped_column(Date)


class Budget(IdMixin, TimestampMixin, Base):
    __tablename__ = "budgets"
    name: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(64))
    cost_center_id: Mapped[str | None] = mapped_column(ForeignKey("cost_centers.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    created_by: Mapped[str] = mapped_column(String(64), default="founder")


class Forecast(IdMixin, TimestampMixin, Base):
    __tablename__ = "forecasts"
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[ForecastKind] = mapped_column(enum_col(ForecastKind))
    metric: Mapped[str] = mapped_column(String(64))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    value_cents: Mapped[int] = mapped_column(BigInteger)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    created_by: Mapped[str] = mapped_column(String(64))


# ---------------------------------------------------------------- research


class ResearchReport(IdMixin, TimestampMixin, Base):
    __tablename__ = "research_reports"
    question: Mapped[str] = mapped_column(Text)
    question_key: Mapped[str] = mapped_column(String(300), index=True)  # normalized for reuse lookup
    decision_supported: Mapped[str | None] = mapped_column(Text)
    subquestions: Mapped[list] = mapped_column(JSON, default=list)
    answer: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Confidence] = mapped_column(enum_col(Confidence))
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    disagreements: Mapped[list] = mapped_column(JSON, default=list)
    what_would_change: Mapped[list] = mapped_column(JSON, default=list)
    live_search_used: Mapped[bool] = mapped_column(Boolean, default=False)
    freshness_days: Mapped[int] = mapped_column(Integer, default=30)
    stale: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    company_id: Mapped[str | None] = mapped_column(ForeignKey("companies.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    created_by_agent: Mapped[str] = mapped_column(String(64))
    claims: Mapped[list[Claim]] = relationship(back_populates="report", cascade="all")


class Source(IdMixin, TimestampMixin, Base):
    __tablename__ = "sources"
    url: Mapped[str] = mapped_column(Text)
    url_key: Mapped[str] = mapped_column(String(500), unique=True)
    title: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(String(300))
    published_date: Mapped[str | None] = mapped_column(String(64))  # as reported (often "3 days ago")
    accessed_at: Mapped[datetime | None] = mapped_column(DateTime)
    credibility: Mapped[Credibility] = mapped_column(enum_col(Credibility), default=Credibility.MEDIUM)
    kind: Mapped[str] = mapped_column(String(32), default="SECONDARY")  # PRIMARY|SECONDARY|AGGREGATOR


class Claim(IdMixin, TimestampMixin, Base):
    __tablename__ = "claims"
    report_id: Mapped[str] = mapped_column(ForeignKey("research_reports.id"), index=True)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    is_fact: Mapped[bool] = mapped_column(Boolean, default=True)  # fact vs interpretation
    cited_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Confidence] = mapped_column(enum_col(Confidence), default=Confidence.MEDIUM)
    report: Mapped[ResearchReport] = relationship(back_populates="claims")
    source: Mapped[Source | None] = relationship()


# ---------------------------------------------------------------- decisions + approvals


class Decision(IdMixin, TimestampMixin, Base):
    __tablename__ = "decisions"
    question: Mapped[str] = mapped_column(Text)
    context: Mapped[str | None] = mapped_column(Text)
    recommendation: Mapped[str | None] = mapped_column(Text)
    final_decision: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    assumptions: Mapped[list] = mapped_column(JSON, default=list)
    confidence: Mapped[str | None] = mapped_column(String(16))
    expected_result: Mapped[str | None] = mapped_column(Text)
    actual_result: Mapped[str | None] = mapped_column(Text)
    outcome_assessment: Mapped[str | None] = mapped_column(String(32))  # GOOD|MIXED|POOR
    outcome_why: Mapped[str | None] = mapped_column(Text)
    decision_maker: Mapped[str | None] = mapped_column(String(64))  # founder | delegated:<who>
    status: Mapped[DecisionStatus] = mapped_column(enum_col(DecisionStatus), default=DecisionStatus.PROPOSED, index=True)
    reversibility: Mapped[str | None] = mapped_column(String(32))
    decision_type: Mapped[str] = mapped_column(String(32), default="GENERAL")  # BUILD|GENERAL|SPEND|...
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    outcome_recorded_at: Mapped[datetime | None] = mapped_column(DateTime)
    options: Mapped[list[DecisionOption]] = relationship(back_populates="decision", cascade="all")


class DecisionOption(IdMixin, TimestampMixin, Base):
    __tablename__ = "decision_options"
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    label: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)
    pros: Mapped[list] = mapped_column(JSON, default=list)
    cons: Mapped[list] = mapped_column(JSON, default=list)
    expected_value: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str | None] = mapped_column(Text)
    recommended: Mapped[bool] = mapped_column(Boolean, default=False)
    decision: Mapped[Decision] = relationship(back_populates="options")


class Approval(IdMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    action: Mapped[str] = mapped_column(Text)
    action_type: Mapped[ApprovalType] = mapped_column(enum_col(ApprovalType), index=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    expected_effect: Mapped[str | None] = mapped_column(Text)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    cost_cents: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)  # what runs if approved
    status: Mapped[ApprovalStatus] = mapped_column(enum_col(ApprovalStatus), default=ApprovalStatus.PENDING, index=True)
    approver: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"))


# ---------------------------------------------------------------- audits + improvement


class Audit(IdMixin, TimestampMixin, Base):
    __tablename__ = "audits"
    scope: Mapped[str] = mapped_column(String(64))  # "decision", "system", "agent:<id>", ...
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    verdict: Mapped[AuditVerdict | None] = mapped_column(enum_col(AuditVerdict))
    summary: Mapped[str | None] = mapped_column(Text)
    findings: Mapped[list] = mapped_column(JSON, default=list)
    observations: Mapped[dict | None] = mapped_column(JSON)  # measured facts the audit was based on
    auditor: Mapped[str] = mapped_column(String(64))
    workflow_run_id: Mapped[str | None] = mapped_column(ForeignKey("workflow_runs.id"), index=True)


class Improvement(IdMixin, TimestampMixin, Base):
    __tablename__ = "improvements"
    title: Mapped[str] = mapped_column(String(300))
    area: Mapped[str] = mapped_column(String(64))
    problem: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    root_cause: Mapped[str] = mapped_column(Text)
    change: Mapped[str] = mapped_column(Text)
    expected_impact: Mapped[str] = mapped_column(Text)
    cost: Mapped[str] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(Text)
    test_plan: Mapped[str] = mapped_column(Text)
    rollback: Mapped[str] = mapped_column(Text)
    metric: Mapped[str | None] = mapped_column(String(200))
    change_spec: Mapped[dict | None] = mapped_column(JSON)  # machine-applicable change, if any
    status: Mapped[ImprovementStatus] = mapped_column(enum_col(ImprovementStatus), default=ImprovementStatus.PROPOSED, index=True)
    test_results: Mapped[dict | None] = mapped_column(JSON)
    priority_score: Mapped[float | None] = mapped_column(Float)
    proposed_by: Mapped[str] = mapped_column(String(64))
    audit_id: Mapped[str | None] = mapped_column(ForeignKey("audits.id"))
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"))


class Experiment(IdMixin, TimestampMixin, Base):
    __tablename__ = "experiments"
    hypothesis: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(String(200))
    variant_a: Mapped[dict] = mapped_column(JSON)
    variant_b: Mapped[dict] = mapped_column(JSON)
    results: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="PLANNED")
    conclusion: Mapped[str | None] = mapped_column(Text)
    improvement_id: Mapped[str | None] = mapped_column(ForeignKey("improvements.id"))
    domain: Mapped[str] = mapped_column(String(32), default="SYSTEM")  # SYSTEM|MARKETING|PRODUCT


class Evaluation(IdMixin, TimestampMixin, Base):
    __tablename__ = "evaluations"
    agent_id: Mapped[str] = mapped_column(String(64), index=True)
    benchmark: Mapped[str] = mapped_column(String(120))
    case_id: Mapped[str] = mapped_column(String(120))
    model: Mapped[str] = mapped_column(String(80), index=True)
    config_version: Mapped[int] = mapped_column(Integer, default=1)
    scores: Mapped[dict] = mapped_column(JSON)
    score: Mapped[float] = mapped_column(Float)  # 0..1 aggregate
    passed: Mapped[bool] = mapped_column(Boolean)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    experiment_id: Mapped[str | None] = mapped_column(ForeignKey("experiments.id"))
    notes: Mapped[str | None] = mapped_column(Text)


class MediaAsset(IdMixin, TimestampMixin, Base):
    """Voice/face references and everything generated from them. Files live on disk; this is the record.

    `synthetic` marks AI-generated media: publishing it on YouTube requires the "altered or synthetic
    content" disclosure. Nothing in the system publishes media; the founder uploads it himself.
    """

    __tablename__ = "media_assets"
    kind: Mapped[MediaKind] = mapped_column(enum_col(MediaKind), index=True)
    status: Mapped[MediaStatus] = mapped_column(enum_col(MediaStatus), index=True)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_s: Mapped[float | None] = mapped_column(Float)
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    engine: Mapped[str | None] = mapped_column(String(120))  # e.g. "chatterbox-turbo (local)", "replicate:bytedance/latentsync"
    parent_ids: Mapped[list] = mapped_column(JSON, default=list)  # what it was made from
    text: Mapped[str | None] = mapped_column(Text)  # the script that was spoken
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    created_by: Mapped[str] = mapped_column(String(64), default="founder")
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class MetricDefinition(Base):
    __tablename__ = "metrics"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    formula: Mapped[str] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    owner_agent: Mapped[str] = mapped_column(String(64), default="analytics")


# ---------------------------------------------------------------- events, audit log, config


class EventRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "events"
    type: Mapped[str] = mapped_column(String(64), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    workflow_run_id: Mapped[str | None] = mapped_column(String(32), index=True)


class AuditLog(Base):
    """Append-only. UPDATE and DELETE are rejected by database triggers (see migration)."""

    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime, index=True)
    who: Mapped[str] = mapped_column(String(64), index=True)
    what: Mapped[str] = mapped_column(String(120), index=True)
    why: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict | None] = mapped_column(JSON)
    output: Mapped[dict | None] = mapped_column(JSON)
    tools_used: Mapped[list] = mapped_column(JSON, default=list)
    cost_micros: Mapped[int] = mapped_column(BigInteger, default=0)
    approval_id: Mapped[str | None] = mapped_column(String(32))
    result: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)
    target_type: Mapped[str | None] = mapped_column(String(64))
    target_id: Mapped[str | None] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class SystemConfiguration(Base):
    __tablename__ = "system_configuration"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    updated_by: Mapped[str | None] = mapped_column(String(64))
