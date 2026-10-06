# AI Company OS — Architecture

One founder, an AI-native organization around him, and a database that holds the truth.
The founder is the final authority. Nothing runs in the background: every workflow is started by a
command, by the dashboard, or by an approval the founder just gave.

## 1. Design decisions (and why)

| Decision | Choice | Why |
|---|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2 | Typed models end to end; Pydantic schemas double as LLM output contracts. |
| Database | SQLite (WAL) now, PostgreSQL later | Zero setup for one founder. All SQL goes through SQLAlchemy + Alembic, so the move is a connection-string change plus re-running migrations (section 13). |
| Money | Integer cents; AI cost in integer micro-dollars | Floats do not reconcile. Every total is a `SUM` of integers. |
| Revenue / expenses | Views over `transactions`, not separate tables | One source of truth. A revenue table and a transaction table can disagree; a query cannot. |
| LLM | Provider abstraction, Anthropic SDK as the first provider | Not locked to one model or vendor. Tests use a scripted provider, never production code paths. |
| Structured output | Forced tool call whose input schema is the Pydantic model | Output is validated, not parsed from prose. Invalid output gets one bounded retry with the validation error, then fails visibly. |
| Numbers | Computed by code, interpreted by agents | The CFO agent never does arithmetic. Finance metrics come from `modules/metrics.py`; the agent explains them. |
| Orchestration | In-process DAG scheduler on `asyncio` | Independent agent work runs in parallel, dependent work waits. No queue infrastructure until it is needed. |
| Frontend | React + TypeScript (Vite), served by the API | One process to run. Next.js adds a second server with no benefit for a single-user local app. |
| Scheduling | Not built. Hooks only. | "Build the brain before the alarm clock." Section 12 shows where it plugs in. |
| Graph | Relational tables + explicit foreign keys / link tables | Enough to traverse founder → goals → decisions → projects → tasks → costs. No graph DB until a query needs one. |

## 2. Hierarchy

```
FOUNDER (final authority; only actor who can approve)
  └─ DIGITAL TWIN / CHIEF OF STAFF   founder memory, preference alignment
      └─ CEO / EXECUTIVE ORCHESTRATOR understands, plans, delegates, synthesizes
          ├─ CFO        finance (numbers from code)
          ├─ CTO        technology, build-vs-buy, tech decision history
          ├─ COO        process, bottlenecks, agent duplication, SOPs
          ├─ CMO        growth, positioning, experiments (not trend-chasing)
          ├─ RESEARCH   rigorous, sourced research; research library
          ├─ STRATEGY   planning hierarchy, priorities, contradictions
          ├─ PRODUCT    customer problems, JTBD, willingness to pay
          ├─ RISK       independent auditor: PASS / PASS WITH CONDITIONS / REVIEW REQUIRED / BLOCK
          └─ ANALYTICS  KPI definitions, anomalies, experiment analysis
DATABASE: shared organizational truth under all of them
```

Every agent is declared in `aios/agents/specs.py` with: purpose, responsibilities, authority,
permissions, tools, inputs, outputs, escalation rules, default model tier, and evaluation benchmark.
Agents are synced into the `agents` table at startup; their prompts are versioned in
`agent_config_versions` (old version, new version, reason, test results, rollback pointer).
Optional agents (engineering, legal, sales...) are not created until a workflow needs them.

## 3. Orchestration engine

```
REQUEST → UNDERSTAND → RETRIEVE CONTEXT → CLASSIFY → PLAN → SELECT AGENTS → EXECUTE (DAG)
        → VERIFY (Risk) → SYNTHESIZE (CEO + Twin) → APPROVAL → SAVE
```

1. **Understand + classify** — CEO intake (balanced tier): intent, request type, the decision being
   supported, missing information, whether approval will be needed.
2. **Retrieve context** — founder memory (with its status label), company, active projects, open
   decisions, fresh research (reused instead of re-run), computed financial summary. Context is
   trimmed to a token budget; stale research is marked, not deleted.
3. **Plan** — CEO returns a work plan: tasks `{key, agent, objective, depends_on}`. The engine
   validates it: known agents only, no cycles, at most `max_tasks_per_workflow`, the agent holds the
   permission the task needs, no duplicate agent+objective. Decision-type workflows always get a Risk
   task that depends on every other task.
4. **Execute** — ready tasks run concurrently (`asyncio.gather`), each as an `agent_run` with its own
   model call, cost record, and retries (max 1 for malformed output, max 2 for transient API errors,
   exponential backoff). A dependent task receives its dependencies' structured outputs, not their
   transcripts. A failed task marks its dependents BLOCKED; independent work continues.
5. **Verify** — Risk audits the combined findings. Disagreement between agents (opposing `stance`
   fields on the same proposal) is detected in code and handed to the CEO explicitly.
6. **Synthesize** — Digital Twin states how the options fit founder preferences (citing memory status:
   EXPLICIT vs INFERRED). CEO writes the executive brief: conclusion, why, evidence, opposing arguments,
   risks, costs, upside, uncertainty, confidence, recommended action, next steps. Evidence beats
   hierarchy: the CEO prompt requires it to reject findings that lack evidence even from specialists.
7. **Approval** — anything consequential becomes a `decision` (PENDING_APPROVAL) + an `approval`.
   Only the founder actor can approve.
8. **Save** — workflow run, agent runs, research reports + sources + claims, audit verdict, decision,
   events, costs, audit log.

On approval of a build/launch decision the engine invokes the Strategy agent to create the objective,
project, milestones, and tasks. This is an *event caused by an approved action*, called explicitly in
the approval handler — not a background listener.

## 4. Model routing

| Tier | Default model | Used for |
|---|---|---|
| FAST | claude-haiku-4-5 | classification, extraction, formatting, structuring search results |
| BALANCED | claude-sonnet-5-5 | most specialist analysis, intake, planning |
| DEEP | claude-opus-5-5 | CEO synthesis, strategy, risk audit of high-impact decisions, conflicting evidence |

The router picks a tier from: the agent's default, the task's declared complexity, workflow
importance, budget remaining (downgrades when near a limit), a floor for audits that must stay strong,
and founder overrides in `system_configuration`. Every choice is logged with its reason.

Evaluation history (benchmark scores for the agent's *active* prompt version) reaches routing in one
of two ways. By default it produces an improvement ("route cfo to FAST: equivalent score, lower cost")
that the founder tests and approves. If the founder sets `routing.auto_apply_eval_history`, the router
switches to the cheapest model within `routing.equivalence_margin` on its own. Scores from inactive
prompt versions never count.

## 5. Memory and provenance

The database, not model context, is the authority for durable facts.

- Categories: FOUNDER, COMPANY, PROJECT, RESEARCH, DECISION, FINANCIAL, AGENT, SYSTEM.
- Status: **EXPLICIT** (founder said it) · **CONFIRMED** (repeated founder decisions support it) ·
  **INFERRED** · **HYPOTHESIS** · **SUPERSEDED**.
- Provenance: FOUNDER, INTERNAL_DATABASE, AGENT_INFERENCE, EXTERNAL_RESEARCH, FINANCIAL_IMPORT,
  TOOL_OUTPUT, SYSTEM_OBSERVATION, OTHER_AGENT.

Rules enforced in `modules/memory.py`, not in prompts:
- Agents can only write INFERRED or HYPOTHESIS. Only the founder writes EXPLICIT.
- INFERRED → CONFIRMED requires ≥ 3 linked founder decisions that support it and none that
  contradict it; the promotion is an event + audit entry, never silent.
- Correcting or replacing a memory sets the old one SUPERSEDED with `superseded_by_id`. Nothing is
  deleted.
- When the founder approves or rejects a decision, the Twin may propose INFERRED preferences with the
  decision linked as evidence.

## 6. Finance

- `transactions` (integer cents, ACTUAL / PENDING / COMMITTED, source, import batch, dedupe hash),
  `accounts`, `vendors`, `cost_centers`, `subscriptions`, `budgets`, `forecasts` (FORECAST / ESTIMATE),
  `import_batches`.
- CSV import validates every row (date, amount, description), rejects bad rows with reasons, dedupes
  by hash, categorizes by rules (founder-editable), detects AI vendors.
- Metrics have exactly one definition each in `modules/metrics.py`, mirrored to the `metrics` table:
  revenue, expenses, net cash flow, monthly burn rate, runway, gross margin, recurring costs, AI
  operating cost. Forecasts are never summed with actuals.
- AI operating cost is the sum of `model_usage` + `tool_calls`, reported separately from bank data.
- Adapters (`aios/integrations/`) implement `FinancialSource.fetch()` and go through the same
  `finance.ingest` path as a CSV upload. Built: CSV. Not built until needed: Stripe, bank feeds,
  accounting software.

## 7. Planning

VISION (company) → GOALS → OBJECTIVES → INITIATIVES → PROJECTS → MILESTONES → TASKS.
Projects carry objective, reason, expected impact, owner, status, priority, dependencies, blockers,
expected cost, effort, risks, success criteria, related decisions and research.
Tasks carry every field in the spec, including completion criteria. A task is COMPLETED only when
its criteria are marked met; generated text does not complete a task.
Contradiction checks run in code: a founder principle such as "preserve cash" against the sum of
approved project costs, budgets vs commitments, dependencies on cancelled projects, cycles.

## 8. Permissions and approvals

Tiers: READ, RESEARCH, ANALYZE, DRAFT, LOCAL_EXECUTE, DATABASE_WRITE:<domain>, EXTERNAL_WRITE,
FINANCIAL_ACTION, SYSTEM_CHANGE. Each agent holds only what its spec grants. Research writes only to
the research domain; Marketing cannot publish; the CFO cannot move money (no agent holds
FINANCIAL_ACTION). Checks run in the service layer via `require(actor, permission)`.

Approval required for: spending, external communication, deleting important data, production
changes, system changes (agent prompts, permissions, budgets, routing), publishing, contracts, and
decisions. Approval records hold action, requester, reason, expected effect, risks, cost, status,
approver, timestamp, decision.

Safeguards (code-enforced): an agent cannot change its own or anyone's permissions, cannot approve,
cannot remove approval gates, cannot delete or update audit log rows (SQLite triggers abort), cannot
write EXPLICIT memory, cannot authorize spend, cannot send external communications.

## 9. Cost accounting and budgets

Every model call writes `model_usage`: agent, workflow, model, provider, tier, input/output tokens,
cache write/read tokens, web searches, estimated cost (pricing table with source + as-of date),
actual cost when a provider reports it, latency, attempt number, outcome. Tool calls write
`tool_calls`. Queries answer: cost per agent / workflow / model / day; cost of one strategy analysis;
retries wasted.

Limits (config): per task, per workflow, per day, per model per day, per agent per day. The guard
checks a projected cost before every call. When a limit would be crossed the workflow stops, returns
what is finished, and lists what remains.

## 10. Research library

Reports store the decision supported, sub-questions, answer, confidence, assumptions, what would
change the conclusion, freshness window, and claims linked to sources (URL, title, publisher,
publication date, accessed date, credibility, fact vs interpretation). Before researching, the engine
looks for a fresh report on the same question and reuses it. Stale reports are flagged, not deleted.
Live search uses Anthropic's server-side web search tool; if it is unavailable the report says so and
caps confidence at LOW. Sources are never invented: only URLs returned by the search tool are stored.

## 10b. Improvement loop

OBSERVE (`observations()`: measured facts only) → PROPOSE (COO, CTO, Analytics review the facts; each
proposal needs evidence, root cause, change, impact, cost, risk, test plan, rollback; Risk reviews the
proposals) → TEST + COMPARE (`aios improvement test`: the agent's benchmark runs on the current setup
and on the candidate inside one workflow run, stored as an `experiment`; verdict BETTER / EQUIVALENT /
WORSE against `routing.equivalence_margin`; nothing live changes) → APPROVE (founder) → IMPLEMENT
(config change, or a new agent prompt version activated) → VERIFY (`aios improvement verify`) →
ROLLBACK if needed (restores the old config value or prompt version).

Prompt changes are never edits in place: a `prompt_addendum` becomes a new row in
`agent_config_versions` (reason, expected improvement, rollback version), benchmarked while inactive,
and activated only by the founder.

## 10c. Trend intelligence

`aios trends "<topic>"`: Research gathers live signals; the CMO scores each trend on signal, evidence,
evidence strength, trajectory, market impact, relevance to this company, opportunity, cost to test,
risks and confidence, and flags trends that are mostly viral discussion. Without live search, no trend
can be rated HIGH confidence (enforced in code).

## 11. Audit log, events, errors, security

- `audit_log`: who, what, when, why, input, output, tools, cost, approval, result, error, plus a hash
  chain (`prev_hash`, `hash`) so tampering is detectable. Append-only, enforced by triggers.
- `events`: TASK_CREATED, TASK_COMPLETED, RESEARCH_COMPLETED, DECISION_CREATED, DECISION_APPROVED,
  EXPENSE_ADDED, REVENUE_ADDED, PROJECT_BLOCKED, AGENT_FAILED, AUDIT_COMPLETED, IMPROVEMENT_PROPOSED,
  WORKFLOW_*. Recorded only. No handler can start work on its own.
- Errors: model failure, malformed output, API failure, timeouts, partial agent failure, missing
  credentials, budget limits — each has a typed exception and is shown, never swallowed.
- Security: secrets only in environment variables (`.env` git-ignored), API bound to localhost with an
  optional bearer token, Pydantic validation on every input and output, external content wrapped in
  `<untrusted_data>` tags with an instruction that it is data, sanitized logs (keys redacted).

## 12. Future scheduling (not built)

A scheduler would call the same `run_workflow(command, request, actor=SYSTEM)` entry point the CLI
and API use, under the same budgets, permissions, and approvals. Events are already recorded, so a
future scheduler can subscribe to them. Nothing in the core assumes a human is watching.

## 13. PostgreSQL migration path

1. `pip install psycopg[binary]`, set `AIOS_DATABASE_URL=postgresql+psycopg://...`.
2. `alembic upgrade head` (migrations are dialect-neutral; the audit-log triggers have a PostgreSQL
   branch in the migration).
3. Copy data: `aios db export ./export` on the old database, then
   `aios db import ./export --url postgresql+psycopg://...` (JSON per table; ids, timestamps and the
   audit-log hash chain preserved; refuses a non-empty target; verifies row counts and the chain).

## 14. Data model (tables)

founders, memories, memory_evidence, companies, goals, objectives, initiatives, projects,
project_dependencies, milestones, tasks, task_dependencies, agents, agent_config_versions,
workflow_runs, agent_runs, model_usage, tool_calls, accounts, vendors, cost_centers, transactions,
import_batches, subscriptions, budgets, forecasts, research_reports, sources, claims, decisions,
decision_options, approvals, audits, improvements, experiments, evaluations, metrics, events,
audit_log, system_configuration.
