"""Output contracts. Every agent answers in one of these shapes; anything else is rejected.

Descriptions are part of the prompt: they tell the model exactly what each field means.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Conf = Literal["HIGH", "MEDIUM", "LOW"]
Stance = Literal["SUPPORT", "OPPOSE", "CONDITIONAL", "NEUTRAL"]


class Evidence(BaseModel):
    claim: str = Field(description="One specific claim this evidence supports.")
    source: str = Field(description="URL, 'memory:<id>', 'research:<id>', 'computed:<metric>', 'decision:<id>', or 'assumption'.")
    source_type: Literal["EXTERNAL", "INTERNAL", "COMPUTED", "FOUNDER", "ASSUMPTION"]
    confidence: Conf


class RiskItem(BaseModel):
    risk: str
    likelihood: Literal["HIGH", "MEDIUM", "LOW"]
    impact: Literal["HIGH", "MEDIUM", "LOW"]
    mitigation: str


class CostItem(BaseModel):
    item: str
    low_usd: float = Field(ge=0)
    high_usd: float = Field(ge=0)
    recurring: Literal["ONE_TIME", "MONTHLY", "ANNUAL"]
    basis: str = Field(description="Where the number comes from. Every cost here is an ESTIMATE, never an actual.")


class AgentFinding(BaseModel):
    """Common shape for every specialist."""

    summary: str = Field(description="Two to four plain sentences. The answer first.")
    conclusion: str = Field(description="The single most important conclusion from your area.")
    stance: Stance = Field(description="Your position on the proposal or question being considered.")
    key_points: list[str] = Field(default_factory=list, max_length=8)
    evidence: list[Evidence] = Field(default_factory=list, max_length=12)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    risks: list[RiskItem] = Field(default_factory=list, max_length=8)
    costs: list[CostItem] = Field(default_factory=list, max_length=8)
    upside: str = Field(default="", description="What goes right and how big it could be.")
    confidence: Conf
    open_questions: list[str] = Field(default_factory=list, max_length=8)
    recommendation: str = Field(description="What you recommend, in one or two sentences.")
    escalate: bool = Field(default=False, description="True if the founder must see something before anything proceeds.")
    escalation_reason: str = ""


# --------------------------------------------------------------- specialist extensions


class ProductAssessment(BaseModel):
    customer: str = Field(description="Who exactly has the problem.")
    job_to_be_done: str
    pain_severity: int = Field(ge=1, le=5)
    frequency: Literal["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY", "RARE"]
    willingness_to_pay: str = Field(description="What evidence suggests they would pay, and how much.")
    current_alternatives: list[str] = Field(default_factory=list)
    switching_costs: Literal["HIGH", "MEDIUM", "LOW"]
    differentiation: str
    riskiest_assumption: str
    cheapest_test: str = Field(description="The cheapest experiment that would test the riskiest assumption.")


class ProductFinding(AgentFinding):
    product: ProductAssessment


class TechDimension(BaseModel):
    dimension: Literal["capability", "reliability", "cost", "speed", "security", "maturity", "compatibility",
                       "migration_difficulty", "maintainability", "business_benefit"]
    score: int = Field(ge=1, le=5)
    note: str


class TechAssessment(BaseModel):
    feasibility: Literal["STRAIGHTFORWARD", "MODERATE", "HARD", "NOT_FEASIBLE"]
    recommended_stack: list[str] = Field(default_factory=list)
    build_vs_buy: str
    dimensions: list[TechDimension] = Field(default_factory=list)
    time_to_mvp_weeks_low: float = Field(ge=0)
    time_to_mvp_weeks_high: float = Field(ge=0)
    security_concerns: list[str] = Field(default_factory=list)
    technical_debt_or_lock_in: list[str] = Field(default_factory=list)


class TechFinding(AgentFinding):
    tech: TechAssessment


class FinanceInputs(BaseModel):
    """Assumptions only. The system computes unit economics from these in code."""

    price_per_customer_monthly_usd: float = Field(ge=0)
    gross_margin_pct: float = Field(ge=0, le=100)
    cac_usd: float = Field(ge=0, description="Customer acquisition cost estimate.")
    monthly_churn_pct: float = Field(gt=0, le=100)
    fixed_costs_monthly_usd: float = Field(ge=0)
    startup_costs_usd: float = Field(ge=0)
    new_customers_per_month: float = Field(ge=0)
    basis: list[str] = Field(default_factory=list, description="Where each assumption comes from.")


class FinanceFinding(AgentFinding):
    finance_inputs: FinanceInputs | None = Field(
        default=None, description="Fill when evaluating a business or project; leave null for pure financial-state reviews.")


class Channel(BaseModel):
    channel: str
    why: str
    audience: str
    cost_to_test_usd: float = Field(ge=0)
    evidence_strength: Literal["STRONG", "MODERATE", "WEAK"]


class GrowthExperiment(BaseModel):
    hypothesis: str
    metric: str
    success_threshold: str
    budget_usd: float = Field(ge=0)
    duration_days: int = Field(ge=1)


class GrowthPlan(BaseModel):
    positioning: str
    channels: list[Channel] = Field(default_factory=list)
    experiments: list[GrowthExperiment] = Field(default_factory=list)
    trend_notes: list[str] = Field(default_factory=list, description="Each with why it matters, who cares, and evidence strength.")


class GrowthFinding(AgentFinding):
    growth: GrowthPlan


class Trend(BaseModel):
    name: str
    category: Literal["technology", "consumer", "business", "cultural", "economic", "startup", "AI", "software",
                      "social_platforms", "regulatory"]
    signal: str = Field(description="What measurably changed, and since when.")
    evidence: list[Evidence] = Field(default_factory=list, max_length=6)
    evidence_strength: Literal["STRONG", "MODERATE", "WEAK"]
    mostly_viral_discussion: bool = Field(description="True when the evidence is mainly social-media attention, "
                                                      "not adoption, spending, revenue or regulation.")
    trajectory: Literal["EMERGING", "RISING", "PEAKING", "DECLINING", "UNCLEAR"]
    market_impact: str = Field(description="Who it affects and roughly how much.")
    relevance: Literal["HIGH", "MEDIUM", "LOW"]
    relevance_why: str = Field(description="Why it matters (or not) for this company specifically.")
    business_opportunity: str = Field(description="A concrete move this company could make. Empty if none.")
    cost_to_test_usd: float = Field(ge=0)
    risks: list[str] = Field(default_factory=list)
    confidence: Conf


class TrendReport(BaseModel):
    summary: str = Field(description="The two or three trends that matter most for this company, and why.")
    trends: list[Trend] = Field(default_factory=list, max_length=10)
    ignore: list[str] = Field(default_factory=list, description="Popular topics deliberately ranked low, with the reason.")
    experiments: list[GrowthExperiment] = Field(default_factory=list, max_length=5,
                                                description="Cheap tests for the most relevant opportunities.")
    stance: Stance = "NEUTRAL"


class OpsFinding(AgentFinding):
    bottlenecks: list[str] = Field(default_factory=list)
    duplicated_work: list[str] = Field(default_factory=list)
    sops_needed: list[str] = Field(default_factory=list)
    automate_later: list[str] = Field(default_factory=list)


class AnalyticsFinding(AgentFinding):
    kpis: list[str] = Field(default_factory=list, description="Metric keys from the metric registry that matter here.")
    anomalies: list[str] = Field(default_factory=list)


# --------------------------------------------------------------- research


class ResearchClaim(BaseModel):
    text: str
    source_url: str | None = Field(description="Must be one of the URLs returned by search. Null if the claim is your interpretation.")
    cited_text: str | None = None
    is_fact: bool = Field(description="True for a sourced fact, False for interpretation.")
    confidence: Conf


class ResearchSource(BaseModel):
    url: str
    title: str | None = None
    publisher: str | None = None
    published: str | None = Field(default=None, description="Publication date as stated by the source or search result.")
    credibility: Literal["HIGH", "MEDIUM", "LOW"]
    kind: Literal["PRIMARY", "SECONDARY", "AGGREGATOR"]


class ResearchFinding(BaseModel):
    question: str
    decision_supported: str
    subquestions: list[str] = Field(default_factory=list)
    answer: str = Field(description="Plain-language answer, the conclusion first.")
    claims: list[ResearchClaim] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list, description="Where sources disagree.")
    assumptions: list[str] = Field(default_factory=list)
    what_would_change: list[str] = Field(default_factory=list, description="Evidence that would change the conclusion.")
    confidence: Conf
    freshness_days: int = Field(ge=1, le=365, description="How many days until this should be re-checked.")
    stance: Stance = "NEUTRAL"
    summary: str = ""


# --------------------------------------------------------------- CEO + orchestration


class Intake(BaseModel):
    intent: str = Field(description="What the founder actually wants, in one sentence.")
    request_type: Literal["DECISION", "ANALYSIS", "RESEARCH", "PLAN", "STATUS", "AUDIT", "FINANCE", "OPPORTUNITY"]
    decision_question: str = Field(description="The decision being supported, phrased as a question. Empty if none.")
    importance: Literal["normal", "high"]
    key_questions: list[str] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list)
    approval_likely: bool


class PlannedTask(BaseModel):
    key: str = Field(description="Short unique key like 'market' or 'unit_econ'.")
    agent: Literal["research", "product", "cmo", "cto", "cfo", "coo", "strategy", "analytics", "risk"]
    objective: str = Field(description="Exactly what this agent must answer. Specific, not generic.")
    depends_on: list[str] = Field(default_factory=list, description="Keys of tasks whose output this task needs.")
    complexity: Literal["low", "medium", "high"]


class WorkPlan(BaseModel):
    rationale: str = Field(description="Why these agents and no others.")
    tasks: list[PlannedTask]
    skipped_agents: list[str] = Field(default_factory=list, description="Agents deliberately not used, with a reason each.")


class Issue(BaseModel):
    severity: Literal["CRITICAL", "MAJOR", "MINOR"]
    target: str = Field(description="Which agent or claim this is about.")
    problem: str
    fix: str


class RiskAudit(BaseModel):
    verdict: Literal["PASS", "PASS_WITH_CONDITIONS", "REVIEW_REQUIRED", "BLOCK"]
    summary: str
    issues: list[Issue] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    calculation_checks: list[str] = Field(default_factory=list, description="Each computed number you re-checked and the result.")
    conditions: list[str] = Field(default_factory=list, description="Conditions that must hold for a PASS_WITH_CONDITIONS.")
    strongest_counterargument: str


class MemoryRef(BaseModel):
    memory_id: str
    status: Literal["EXPLICIT", "CONFIRMED", "INFERRED", "HYPOTHESIS"]
    note: str


class ProposedInference(BaseModel):
    subject: str = Field(description="snake_case key, e.g. 'prefers_low_capital_tests'.")
    content: str
    status: Literal["INFERRED", "HYPOTHESIS"]
    evidence: str


class TwinAlignment(BaseModel):
    alignment_summary: str = Field(description="How the options fit what the founder has said and decided.")
    aligned_with: list[MemoryRef] = Field(default_factory=list)
    conflicts_with: list[MemoryRef] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list, description="Preferences that matter here but are not known.")
    proposed_inferences: list[ProposedInference] = Field(default_factory=list,
        description="New INFERRED/HYPOTHESIS memories suggested by this case. Never EXPLICIT.")


class DecisionOptionOut(BaseModel):
    label: str
    description: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    expected_value: str
    risk: str
    recommended: bool


class Disagreement(BaseModel):
    topic: str
    positions: list[str]
    resolution: str
    basis: str = Field(description="The evidence that settled it, or 'unresolved'.")


class ScoreLine(BaseModel):
    dimension: Literal["customer_pain", "market_size", "market_growth", "competition", "differentiation",
                       "willingness_to_pay", "distribution", "technical_feasibility", "capital_requirement",
                       "time_to_market", "defensibility", "regulatory_risk"]
    score: int = Field(ge=1, le=5, description="5 = most favorable for building.")
    note: str


class ExecutiveBrief(BaseModel):
    conclusion: str = Field(description="The answer in one or two sentences.")
    verdict: Literal["BUILD", "INVESTIGATE", "WATCH", "PASS", "PROCEED", "DO_NOT_PROCEED", "NO_DECISION"]
    why: list[str] = Field(description="The 3-6 reasons that carry the conclusion.")
    evidence: list[Evidence] = Field(default_factory=list)
    opposing_arguments: list[str] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    costs: list[CostItem] = Field(default_factory=list)
    upside: str
    uncertainty: str = Field(description="What is unknown and how much it matters.")
    confidence: Conf
    recommended_action: str
    next_steps: list[str] = Field(default_factory=list, max_length=8)
    options: list[DecisionOptionOut] = Field(default_factory=list)
    disagreements: list[Disagreement] = Field(default_factory=list)
    founder_alignment: str = Field(default="", description="How this fits the founder's stated preferences (cite EXPLICIT vs INFERRED).")
    scorecard: list[ScoreLine] = Field(default_factory=list, description="Fill for opportunity evaluations.")
    requires_approval: bool = Field(description="True if acting on this needs the founder's decision.")
    decision_type: Literal["BUILD", "GENERAL", "SPEND", "TECH", "MARKETING", "HIRING", "NONE"] = "GENERAL"
    reversibility: Literal["EASY", "MODERATE", "HARD"] = "MODERATE"


# --------------------------------------------------------------- planning


class PlanObjective(BaseModel):
    title: str
    metric: str
    target: str
    due_in_days: int = Field(ge=1, le=730)


class PlanProject(BaseModel):
    name: str
    objective: str
    reason: str
    expected_impact: str
    priority: int = Field(ge=1, le=5)
    expected_cost_usd: float = Field(ge=0)
    estimated_effort_hours: float = Field(ge=0)
    risks: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(min_length=1)


class PlanMilestone(BaseModel):
    key: str
    title: str
    due_in_days: int = Field(ge=1, le=730)
    success_criteria: str


class PlanTask(BaseModel):
    key: str
    title: str
    description: str
    milestone_key: str
    responsible: str = Field(description="'founder' or an agent id.")
    priority: int = Field(ge=1, le=5)
    depends_on: list[str] = Field(default_factory=list)
    completion_criteria: str = Field(description="Observable condition that makes this task done.")
    estimated_effort_hours: float = Field(ge=0)
    estimated_cost_usd: float = Field(ge=0)


class PlanOutput(BaseModel):
    objective: PlanObjective
    project: PlanProject
    milestones: list[PlanMilestone] = Field(min_length=1, max_length=8)
    tasks: list[PlanTask] = Field(min_length=1, max_length=30)
    assumptions: list[str] = Field(default_factory=list)


class RankedItem(BaseModel):
    item_type: Literal["project", "task", "decision", "approval", "objective"]
    item_id: str
    title: str
    why: str
    expected_value: Literal["HIGH", "MEDIUM", "LOW"]


class PrioritiesOutput(BaseModel):
    summary: str
    do_next: list[RankedItem] = Field(default_factory=list, max_length=10)
    kill_or_pause: list[RankedItem] = Field(default_factory=list)
    blocked: list[str] = Field(default_factory=list)
    decisions_waiting_on_founder: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


# --------------------------------------------------------------- audit + improvement


class ChangeSpec(BaseModel):
    """A change the system can apply itself once approved. Leave null for changes a human must make."""

    type: Literal["routing_override", "budget", "config", "prompt_addendum"] = Field(
        description="routing_override/budget/config change a configuration key. prompt_addendum appends guidance to "
                    "one agent's prompt as a new, versioned configuration that can be benchmarked and rolled back.")
    key: str = Field(description="For config types: the config key, e.g. 'routing.agent_tier_overrides' or "
                                 "'budget.workflow_limit_usd'. For prompt_addendum: the agent id, e.g. 'research'.")
    value: str = Field(description="For config types: the new value as JSON text, e.g. '{\"analytics\": \"FAST\"}'. "
                                   "For prompt_addendum: the exact guidance text to add (plain text, under 1,500 characters).")


class ImprovementOut(BaseModel):
    title: str
    area: Literal["agent_quality", "model_choice", "prompts", "context_size", "cost", "accuracy", "research_quality",
                  "latency", "architecture", "code", "ux", "planning", "operations", "database", "security", "finance"]
    problem: str
    evidence: list[str] = Field(min_length=1, description="Measured observations from the audit data. No evidence, no proposal.")
    root_cause: str
    change: str
    expected_impact: str
    cost: str
    risk: str
    test_plan: str
    rollback: str
    metric: str = Field(description="How success is measured.")
    priority: int = Field(ge=1, le=5, description="1 = do first.")
    change_spec: ChangeSpec | None = None


class AuditReview(BaseModel):
    summary: str
    findings: list[str] = Field(default_factory=list)
    proposals: list[ImprovementOut] = Field(default_factory=list, max_length=8)
