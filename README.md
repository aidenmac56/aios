# AI Company OS

A digital twin and an AI-native company built around one founder. Specialist agents (CEO, CFO, CTO, COO,
CMO, Research, Strategy, Product, Risk, Analytics, Digital Twin) work through one orchestrator, share one
database of truth, get audited by an independent risk agent, and never act without the founder's approval.

Nothing runs in the background. Every workflow starts from a command, the dashboard, or an approval you just gave.

## Setup (5 minutes)

```bash
git clone https://github.com/aidenmac56/aios && cd aios
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env          # then put your ANTHROPIC_API_KEY in .env
aios init                     # creates data/aios.db
aios seed                     # loads your founder memory (review aios/seed/founder_seed.json first)
aios serve                    # dashboard at http://127.0.0.1:8787
```

Get an API key at console.anthropic.com. It lives only in `.env`, which git ignores. Finance import,
metrics, the dashboard, memory, planning and audit logs all work without a key; agent workflows need one.

## Commands

| Command | What it does |
|---|---|
| `aios ceo "Analyze whether I should build X"` | CEO understands the request, picks agents, runs them (parallel where independent), Risk audits, Twin checks fit with your preferences, CEO recommends. Big calls wait for your approval. |
| `aios approve <id>` / `aios reject <id>` | Your decision. Approving a build decision creates the objective, project, milestones and tasks, and the Twin learns from your choice. |
| `aios opportunity "idea"` | Research → product, marketing, tech in parallel → CFO economics → Risk → BUILD / INVESTIGATE / WATCH / PASS with a 12-point scorecard. |
| `aios board "question"` | CFO, CTO, CMO, Product and COO weigh in at once; Risk audits; CEO synthesizes. |
| `aios decision "question"` | Options, evidence, expected value, recommendation, saved to decision history. |
| `aios research "question"` | Live, sourced research saved to the library. Fresh research is reused, not repeated. |
| `aios market "market"` / `aios cto "topic"` | Market analysis / technology review. |
| `aios plan "objective"` / `aios priorities` | Structured plans; what matters most, what to kill, what is blocked, contradictions. |
| `aios finance --import bank.csv` | Validate, categorize and import transactions, then revenue, expenses, burn, runway, recurring costs, anomalies, AI costs. |
| `aios audit` / `aios improve` | Audit the whole company from measured data; improvements with problem, evidence, root cause, change, impact, cost, risk, test and rollback. Nothing changes until you approve. |
| `aios cost` / `aios agents` / `aios status` / `aios memory` | Costs by agent/model/workflow/day, the org chart, the whole company state, founder memory. |
| `aios outcome <decision> --actual ... --assessment GOOD\|MIXED\|POOR --why ...` | Record what really happened so future recommendations learn from it. |
| `aios eval <agent> --model <model>` | Run an agent's benchmark; results steer model routing. |

The same commands exist as Claude Code slash commands in `.claude/commands/` (`/ceo`, `/board`, `/research`, ...).

## How it stays honest

- **Memory has provenance.** EXPLICIT (you said it), CONFIRMED (3+ of your decisions show it), INFERRED, HYPOTHESIS, SUPERSEDED. Agents can only write INFERRED or HYPOTHESIS. Corrections supersede; nothing is deleted.
- **Numbers come from code.** The CFO interprets metrics; it never calculates them. Each metric has one definition (`aios/modules/metrics.py`). Actuals, forecasts and estimates are never mixed.
- **Sources are real.** Research keeps only URLs the search tool actually returned. A "fact" without one is downgraded to interpretation.
- **The auditor is independent.** A BLOCK or REVIEW_REQUIRED from Risk always reaches you, whatever the CEO concludes.
- **Approval gates.** Only you can approve spending, communication, publishing, deletion, system changes and decisions. No agent can grant itself permissions or touch the audit log (the database rejects updates and deletes).
- **Budgets.** Per task, workflow, day, agent and model. When a limit would be crossed the run stops and returns what it finished.
- **Every model call is costed** (`model_usage`), so you can see which agent, workflow or model costs the most.

## Layout

```
aios/                 Python package
  agents/             specs (roles, permissions, prompts) + output schemas
  orchestrator/       engine (plan → DAG → verify → synthesize), agent runner, context retrieval
  llm/                provider abstraction, routing, pricing, validated calls
  modules/            memory, finance, metrics, planning, research, decisions, improvements, evaluations, status
  core/               audit log, events, permissions, approvals, budgets, config
  db/                 schema + migrations (SQLite now, PostgreSQL path in docs/architecture.md)
  api/                FastAPI app serving /api and the dashboard
  web_dist/           built dashboard (source in web/)
tests/                unit, integration and the three required end-to-end tests
docs/architecture.md  design and decisions
```

Run tests with `pytest`. Rebuild the dashboard with `cd web && npm install && npm run build`.
