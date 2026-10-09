// Response shapes of the FastAPI backend (aios/api/app.py and the modules it calls).
// Field names match the API exactly. Amounts: *_cents / `cents` are integer cents; *_usd are dollars.

export type Conf = "HIGH" | "MEDIUM" | "LOW";

// ------------------------------------------------------------------ health + settings

export interface Health {
  ok: boolean;
  llm_credentials: boolean;
  web_search: boolean;
}

export interface ConfigEntry {
  value: unknown;
  description: string | null;
  source: "default" | "database";
  updated_by?: string | null;
  updated_at?: string | null;
}

export interface SettingsView {
  config: Record<string, ConfigEntry>;
  llm_credentials: boolean;
  web_search: boolean;
  database: string;
  api_token_required: boolean;
}

export interface MetricDef {
  key: string;
  name: string;
  formula: string;
  unit: string;
  description: string;
}

// ------------------------------------------------------------------ status

export interface CompanyRow {
  id: string;
  name: string;
  mission: string | null;
  strategy: string | null;
  business_model: string | null;
  products: unknown[] | null;
  customers: unknown[] | null;
}

export interface TaskScore {
  task_id: string;
  title: string;
  status: string;
  priority: number;
  project: string | null;
  unlocks: number;
  score: number;
  owner: string | null;
}

export interface Principle {
  key?: string;
  text?: string;
  memory_id?: string;
  [k: string]: unknown;
}

export interface ProjectSummary {
  id: string;
  name: string;
  status: string;
  priority: number;
  expected_cost: string;
  tasks_total: number;
  tasks_done: number;
  progress_pct: number;
  decision_id: string | null;
  blocked_tasks: number;
}

export interface PendingApprovalBrief {
  id: string;
  action: string;
  type: string;
  requested_by: string;
}

export interface CompanyStatus {
  companies: CompanyRow[];
  priorities: TaskScore[];
  founder_focus: Memory[];
  principles: Principle[];
  projects: ProjectSummary[];
  finance: {
    has_data: boolean;
    note: string | null;
    totals: FinanceTotals | null;
    burn: Burn | null;
    cash: Cash | null;
    runway: Runway | null;
    recurring: Recurring | null;
    ai: FinanceAI | null;
    period: { from: string; to: string } | null;
  };
  ai_costs: { last_30d_usd: number; today_usd: number; daily_limit_usd: number };
  risks: { audit_id: string; verdict: string | null; summary: string | null; at: string }[];
  opportunities: { decision_id: string; question: string; recommendation: string | null; status: string }[];
  decisions_needed: { pending_approvals: number; items: PendingApprovalBrief[] };
  contradictions: string[];
  improvements: { id: string; title: string; status: string }[];
  recent_workflows: { id: string; command: string; status: string; request: string; cost_usd: number; at: string }[];
  recent_activity: { type: string; actor: string; at: string; payload: Record<string, unknown> | null }[];
  research_reports: number;
}

// ------------------------------------------------------------------ finance

export interface Money {
  cents: number;
  display: string;
}

export interface FinanceTotals {
  revenue: Money;
  other_inflows: Money;
  expenses: Money;
  net_cash_flow: Money;
}

export interface Burn {
  gross_burn_monthly: number | null;
  net_burn_monthly: number | null;
  months_used: number;
  note?: string;
  months?: string[];
  gross_display?: string;
  net_display?: string;
}

export interface Cash {
  cash_balance: number | null;
  note: string | null;
  display?: string;
}

export interface Runway {
  runway_months: number | null;
  note: string | null;
}

export interface Recurring {
  monthly_cents: number;
  display: string;
  items: { name: string; amount: string; source: string; last_charge: string | null }[];
}

export interface FinanceAI {
  vendor_spend_bank: Money;
  system_operating_cost: { usd: number; calls: number; basis: string };
}

export interface MonthRow {
  month: string;
  revenue: number;
  other_inflows: number;
  expenses: number;
  net_cash_flow: number;
}

export interface FinanceSummary {
  has_data: boolean;
  note?: string;
  ai_operating_cost?: { usd: number; calls: number };
  period?: { from: string; to: string };
  transactions?: number;
  totals?: FinanceTotals;
  burn?: Burn;
  cash?: Cash;
  runway?: Runway;
  gross_margin?: { gross_margin_pct: number | null; note: string | null; cogs?: number };
  monthly?: MonthRow[];
  by_category?: { category: string; total_cents: number; total: string; count: number }[];
  major_vendors?: { vendor: string; ai_provider: boolean; spend_cents: number; spend: string; charges: number }[];
  recurring?: Recurring;
  anomalies?: { transaction_id: string; date: string; description: string; amount: string; reason: string }[];
  ai?: FinanceAI;
  not_actual?: { cents: number; display: string; note: string };
  reconciliation?: Reconciliation | null;
}

export interface Reconciliation {
  ok: boolean;
  checks: Record<string, boolean>;
}

export interface Transaction {
  id: string;
  date: string;
  description: string;
  amount_cents: number;
  category: string | null;
  status: string;
  is_revenue: boolean;
  is_transfer: boolean;
  vendor: string | null;
}

export interface ImportResult {
  batch_id: string;
  accepted: number;
  rejected: number;
  duplicates: number;
  errors: { line: number; error: string; row: Record<string, string> }[];
}

// ------------------------------------------------------------------ costs

export interface CostRow {
  key: string;
  calls: number;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Costs {
  window_days: number;
  total_usd: number;
  calls: number;
  failed_calls: number;
  retry_cost_usd: number;
  web_search: { cost_usd_included: number; calls: number };
  today_usd: number;
  daily_limit_usd: number;
  by_agent: CostRow[];
  by_model: CostRow[];
  by_workflow: CostRow[];
  by_purpose: CostRow[];
  by_day: { day: string; cost_usd: number }[];
  per_run_avg_usd: { command: string; runs: number; avg_usd: number }[];
  basis: string;
}

// ------------------------------------------------------------------ agents + runs

export interface AgentView {
  id: string;
  name: string;
  title: string;
  purpose: string;
  responsibilities: string[];
  authority: string;
  permissions: string[];
  tools: string[];
  inputs: string;
  outputs: string;
  escalation_rules: string[];
  default_tier: string;
  performance_measures: string[];
  enabled: boolean;
  config_version: number;
  runs: number;
  failed: number;
  total_cost_usd: number;
  avg_duration_s: number;
  last_run: { at: string; status: string; model: string | null } | null;
}

export interface AgentRunRow {
  id: string;
  /** Not currently returned by the API's _run_row; used when present. */
  agent_id?: string;
  workflow_run_id: string | null;
  status: string;
  objective: string | null;
  model: string | null;
  tier: string | null;
  routing_reason: string | null;
  cost_usd: number;
  duration_ms: number | null;
  retries: number | null;
  error: string | null;
  summary: string | null;
  started_at: string | null;
}

export interface AgentDetail extends AgentView {
  versions: {
    version: number;
    reason: string | null;
    created_by: string | null;
    created_at: string;
    prompt_chars: number;
    rollback_to: number | null;
    test_results: unknown;
    active?: boolean;
  }[];
  system_prompt: string | null;
  recent_runs: AgentRunRow[];
}

export interface RunListRow {
  id: string;
  command: string;
  request: string;
  status: string;
  cost_usd: number;
  created_at: string;
  finished_at: string | null;
  decision_id: string | null;
}

export interface ProgressEntry {
  at: string;
  msg: string;
}

export interface RunDetail {
  id: string;
  command: string;
  request: string;
  status: string;
  importance: string;
  understanding: Intake | null;
  plan: WorkPlan | null;
  result: RunResult | null;
  progress: ProgressEntry[] | null;
  cost_usd: number;
  budget_usd: number;
  error: string | null;
  decision_id: string | null;
  created_at: string;
  agent_runs: AgentRunRow[];
}

export interface CommandStarted {
  run_id: string;
  status: string;
}

// ------------------------------------------------------------------ agent output schemas (aios/agents/schemas.py)

export interface Evidence {
  claim: string;
  source: string;
  source_type: "EXTERNAL" | "INTERNAL" | "COMPUTED" | "FOUNDER" | "ASSUMPTION";
  confidence: Conf;
}

export interface RiskItem {
  risk: string;
  likelihood: Conf;
  impact: Conf;
  mitigation: string;
}

export interface CostItem {
  item: string;
  low_usd: number;
  high_usd: number;
  recurring: "ONE_TIME" | "MONTHLY" | "ANNUAL";
  basis: string;
}

export interface DecisionOptionOut {
  label: string;
  description: string;
  pros: string[];
  cons: string[];
  expected_value: string;
  risk: string;
  recommended: boolean;
}

export interface Disagreement {
  topic: string;
  positions: string[];
  resolution: string;
  basis: string;
}

export interface ScoreLine {
  dimension: string;
  score: number;
  note: string;
}

export interface ExecutiveBrief {
  conclusion: string;
  verdict: "BUILD" | "INVESTIGATE" | "WATCH" | "PASS" | "PROCEED" | "DO_NOT_PROCEED" | "NO_DECISION";
  why: string[];
  evidence: Evidence[];
  opposing_arguments: string[];
  risks: RiskItem[];
  costs: CostItem[];
  upside: string;
  uncertainty: string;
  confidence: Conf;
  recommended_action: string;
  next_steps: string[];
  options: DecisionOptionOut[];
  disagreements: Disagreement[];
  founder_alignment: string;
  scorecard: ScoreLine[];
  requires_approval: boolean;
  decision_type: string;
  reversibility: string;
}

export interface Issue {
  severity: "CRITICAL" | "MAJOR" | "MINOR";
  target: string;
  problem: string;
  fix: string;
}

export interface RiskAudit {
  verdict: "PASS" | "PASS_WITH_CONDITIONS" | "REVIEW_REQUIRED" | "BLOCK";
  summary: string;
  issues: Issue[];
  unsupported_claims: string[];
  calculation_checks: string[];
  conditions: string[];
  strongest_counterargument: string;
}

export interface MemoryRef {
  memory_id: string;
  status: string;
  note: string;
}

export interface TwinAlignment {
  alignment_summary: string;
  aligned_with: MemoryRef[];
  conflicts_with: MemoryRef[];
  unknowns: string[];
  proposed_inferences: { subject: string; content: string; status: string; evidence: string }[];
}

export interface UnitEconomics {
  kind: string;
  contribution_per_customer_monthly_usd: number | null;
  ltv_usd: number | null;
  ltv_to_cac: number | null;
  cac_payback_months: number | null;
  breakeven_customers: number | null;
  months_to_operating_breakeven: number | null;
  peak_cash_needed_usd: number | null;
  customers_after_36_months: number | null;
  cumulative_cash_36_months_usd: number | null;
  simulation?: string;
}

/** A research claim as produced by the agent (source_url) or as stored (source object). */
export interface ResearchClaimAny {
  text: string;
  is_fact: boolean;
  confidence: Conf;
  source_url?: string | null;
  cited_text?: string | null;
  source?: ClaimSource | null;
}

export interface ClaimSource {
  url: string;
  title: string | null;
  publisher: string | null;
  published: string | null;
  credibility: Conf;
}

export interface ResearchOutput {
  question?: string;
  decision_supported?: string;
  answer?: string;
  summary?: string;
  claims?: ResearchClaimAny[];
  sources?: { url: string; title?: string | null; publisher?: string | null; published?: string | null; credibility?: string; kind?: string }[];
  disagreements?: string[];
  assumptions?: string[];
  what_would_change?: string[];
  confidence?: Conf;
  live_search_used?: boolean;
  report_id?: string;
  reused_report_id?: string;
  source_problems?: string[];
  search_error?: string | null;
}

export interface Intake {
  intent: string;
  request_type: string;
  decision_question: string;
  importance: string;
  key_questions: string[];
  missing_information: string[];
  approval_likely: boolean;
}

export interface PlannedTask {
  key: string;
  agent: string;
  objective: string;
  depends_on: string[];
  complexity: string;
}

export interface WorkPlan {
  rationale: string;
  tasks: PlannedTask[];
  skipped_agents: string[];
}

export interface PlanCreated {
  objective_id: string;
  project_id: string;
  milestone_ids: string[];
  task_ids: string[];
  status: string;
  contradictions: string[];
  warnings: string[];
  approval_id: string | null;
}

export interface AgentFindingLike {
  summary?: string;
  conclusion?: string;
  stance?: string;
  key_points?: string[];
  risks?: RiskItem[];
  recommendation?: string;
  confidence?: Conf;
  open_questions?: string[];
  error?: string;
  [k: string]: unknown;
}

export interface RankedItem {
  item_type: string;
  item_id: string;
  title: string;
  why: string;
  expected_value: Conf;
}

export interface PrioritiesOutput {
  summary: string;
  do_next: RankedItem[];
  kill_or_pause: RankedItem[];
  blocked: string[];
  decisions_waiting_on_founder: string[];
  contradictions: string[];
}

export interface ApiErrorBody {
  code: string;
  message: string;
  [k: string]: unknown;
}

export interface DraftOutput {
  summary: string;
  items: { label: string; text: string; why: string }[];
  recommended: string[];
  assumptions: string[];
}

export interface RunResult {
  draft?: DraftOutput;
  test?: TestResult;
  trends?: TrendReport;
  brief?: ExecutiveBrief;
  risk_audit?: RiskAudit | null;
  founder_alignment?: TwinAlignment | null;
  agents?: Record<string, { agent: string; ok: boolean; summary: string | null; stance: string | null; error: string | null; run_id: string | null }>;
  disagreements?: { topic: string; support?: { task: string; conclusion: string }[]; oppose?: { task: string; conclusion: string }[] }[];
  unit_economics?: UnitEconomics;
  decision_id?: string;
  approval_id?: string | null;
  research?: ResearchOutput;
  created?: PlanCreated;
  improvements?: Improvement[];
  measured_candidates?: Improvement[];
  financials?: FinanceSummary;
  reconciliation?: Reconciliation | null;
  cfo?: AgentFindingLike;
  cto?: AgentFindingLike;
  priorities?: PrioritiesOutput | { error: string };
  risk_review?: RiskAudit | { error: string };
  audit_id?: string;
  findings?: Record<string, string[] | null>;
  error?: ApiErrorBody;
  stopped?: string;
  budget?: Record<string, unknown>;
  remaining?: string[];
  intake?: Intake;
  alignment?: TwinAlignment;
  memories_created?: string[];
  memories_promoted?: string[];
  cost_usd?: number;
  research_report_ids?: string[];
  [k: string]: unknown;
}

// ------------------------------------------------------------------ approvals + decisions

export interface Approval {
  id: string;
  action: string;
  type: string;
  requested_by: string;
  reason: string | null;
  expected_effect: string | null;
  risks: string[] | null;
  cost_usd: number | null;
  status: string;
  approver: string | null;
  decided_at: string | null;
  decision_id: string | null;
  created_at: string;
}

export interface ApprovalDecision {
  approval_id: string;
  status: string;
  decision_id?: string;
  decision_status?: string;
  follow_up?: { workflow: string; decision_id: string }[];
  follow_up_runs: { workflow: string; run_id: string }[];
  project_id?: string;
  project_status?: string;
  improvement_id?: string;
  improvement_status?: string;
  note?: string;
  [k: string]: unknown;
}

export interface Decision {
  id: string;
  question: string;
  recommendation: string | null;
  final_decision: string | null;
  reasoning: string | null;
  evidence: unknown[] | null;
  confidence: string | null;
  status: string;
  decision_type: string | null;
  reversibility: string | null;
  decision_maker: string | null;
  expected_result: string | null;
  actual_result: string | null;
  outcome_assessment: string | null;
  outcome_why: string | null;
  workflow_run_id: string | null;
  created_at: string;
  decided_at: string | null;
  options: DecisionOptionOut[];
}

// ------------------------------------------------------------------ planning

export interface PlanningState {
  projects: ProjectSummary[];
  pending_approvals: PendingApprovalBrief[];
  decisions_waiting: { id: string; question: string }[];
  top_tasks: TaskScore[];
  contradictions: string[];
}

export interface TaskRow {
  id: string;
  title: string;
  description: string | null;
  status: string;
  priority: number;
  owner: string | null;
  milestone_id: string | null;
  completion_criteria: string | null;
  criteria_met: boolean;
  estimated_effort_hours: number | null;
  estimated_cost_usd: number;
  due_date: string | null;
}

export interface ProjectDetail {
  id: string;
  name: string;
  objective: string | null;
  reason: string | null;
  expected_impact: string | null;
  status: string;
  priority: number;
  expected_cost_usd: number;
  estimated_effort_hours: number | null;
  risks: string[] | null;
  success_criteria: string[] | null;
  blockers: unknown[] | null;
  decision_id: string | null;
  milestones: { id: string; title: string; due_date: string | null; success_criteria: string | null; status: string }[];
  tasks: TaskRow[];
  dependencies: { task_id: string; depends_on_id: string }[];
}

// ------------------------------------------------------------------ research

export interface ResearchReport {
  id: string;
  question: string;
  decision_supported: string | null;
  answer: string;
  confidence: Conf;
  assumptions: string[] | null;
  disagreements: string[] | null;
  what_would_change: string[] | null;
  live_search_used: boolean;
  freshness_days: number;
  stale: boolean;
  subquestions: string[] | null;
  created_by_agent: string | null;
  created_at: string;
  claims?: { text: string; is_fact: boolean; confidence: Conf; source: ClaimSource | null }[];
}

// ------------------------------------------------------------------ audits + improvements

export interface AuditRow {
  id: string;
  scope: string;
  verdict: string | null;
  summary: string | null;
  /** Strings for system audits; Issue objects for workflow audits by the risk agent. */
  findings: (string | Issue | Record<string, unknown>)[] | null;
  auditor: string | null;
  workflow_run_id: string | null;
  created_at: string;
}

export interface Improvement {
  id: string;
  title: string;
  area: string;
  problem: string;
  evidence: string[] | null;
  root_cause: string | null;
  change: string | null;
  expected_impact: string | null;
  cost: string | null;
  risk: string | null;
  test_plan: string | null;
  rollback: string | null;
  metric: string | null;
  change_spec: { type: string; key: string; value: string } | null;
  status: string;
  test_results: {
    applied?: AppliedChange;
    verification?: unknown;
    verdict?: "BETTER" | "EQUIVALENT" | "WORSE";
    score_delta?: number;
    cost_delta_usd?: number;
    experiment_id?: string;
    baseline?: TestArm;
    candidate?: TestArm;
    candidate_version?: number;
    [k: string]: unknown;
  } | null;
  priority_score: number | null;
  proposed_by: string | null;
  audit_id: string | null;
  created_at: string;
}

/** Config change ({key, old, new}) or prompt change ({type:"prompt", agent, old_version, new_version}). */
export interface AppliedChange {
  type?: "prompt";
  key?: string;
  old?: unknown;
  new?: unknown;
  agent?: string;
  old_version?: number;
  new_version?: number;
  at: string;
}

export interface TestArm {
  model: string;
  config_version: number;
  avg_score: number;
  total_cost_usd: number;
}

export interface TestResult {
  improvement_id: string;
  experiment_id: string;
  verdict: "BETTER" | "EQUIVALENT" | "WORSE";
  conclusion: string;
  baseline: TestArm & { cases: { case: string; score: number; error: string | null }[] };
  candidate: TestArm & { cases: { case: string; score: number; error: string | null }[] };
}

export interface TrendItem {
  name: string;
  category: string;
  signal: string;
  evidence: { claim: string; source: string; source_type: string; confidence: string }[];
  evidence_strength: "STRONG" | "MODERATE" | "WEAK";
  mostly_viral_discussion: boolean;
  trajectory: string;
  market_impact: string;
  relevance: "HIGH" | "MEDIUM" | "LOW";
  relevance_why: string;
  business_opportunity: string;
  cost_to_test_usd: number;
  risks: string[];
  confidence: "HIGH" | "MEDIUM" | "LOW";
}

export interface TrendReport {
  summary: string;
  trends: TrendItem[];
  ignore: string[];
  experiments: { hypothesis: string; metric: string; success_threshold: string; budget_usd: number; duration_days: number }[];
  note?: string;
}

export interface AuditLogEntry {
  seq: number;
  at: string;
  who: string;
  what: string;
  why: string | null;
  result: string | null;
  error: string | null;
  cost_usd: number;
  target_type: string | null;
  target_id: string | null;
  approval_id: string | null;
}

export interface ChainVerify {
  ok: boolean;
  entries: number;
  first_bad_seq: number | null;
}

// ------------------------------------------------------------------ memory

export interface Memory {
  id: string;
  category: string;
  subject: string;
  content: string;
  status: string;
  provenance: string;
  source_ref: string | null;
  confidence: number | null;
  created_by: string | null;
  superseded_by_id: string | null;
  tags: string[] | null;
  created_at: string | null;
  last_confirmed_at: string | null;
}

export interface MemoryConflict {
  subject: string;
  memories: { id: string; status: string; content: string }[];
}

export interface MemoryList {
  memories: Memory[];
  conflicts: MemoryConflict[];
}
