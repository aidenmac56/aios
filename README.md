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
aios doctor --live            # confirms the key, model access and web search work (a few cents)
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
| `aios trends "topic"` | Which trends have real evidence and matter to this company, and which are just buzz. |
| `aios improvement test --id <id>` | Benchmark the current setup against a proposed routing or prompt change. Changes nothing live. |
| `aios agent versions <agent>` / `aios agent activate <agent> <v>` | See an agent's prompt versions; switch the live one (you only). |
| `aios eval <agent> --model <model>` | Run an agent's benchmark; results feed improvement proposals. |
| `aios doctor [--live]` | Check the installation; `--live` makes one tiny real model call and one web search (a few cents). |
| `aios db export DIR` / `aios db import DIR --url URL` | Move everything to a new database (e.g. PostgreSQL) with ids and the audit chain intact. |

The same commands exist as Claude Code slash commands in `.claude/commands/` (`/ceo`, `/board`, `/research`, ...).

## Your to-do list (Mac menu bar)

Things only you can do, outside the system: tasks plans assign to you (`founder`) plus anything you add.

```bash
pip install rumps                 # once
aios menubar --install            # shows ☐ N in the top-right; starts at login
aios todo add "Record a 30-second voice clip" --priority 1
aios todo                         # same list in the terminal;  aios todo done <id>
```

Click an item to check it off. That completes the task in AIOS (criteria met, event, audit log) and
unlocks anything that was waiting on it, so `priorities`, `status` and the agents see it as done.
Click a checked item to undo. The list re-reads the database every 20 seconds.

The menu also shows **approvals waiting on you** (click to copy the `aios approve` command) and the
**system's list**: plan tasks assigned to agents. Those run only when you click **▶ Run system tasks**
(or `aios work run`): up to 3 at a time, each as the fitting workflow (research, draft, finance…),
budget-checked like any command. A finished run completes its task with the run as evidence;
`aios work reopen <id>` sends one back if the output wasn't good enough. `aios work` lists the queue.

## Studio: your voice and face (replaces ElevenLabs + HeyGen)

Open-source models instead of subscriptions:

| Instead of | Uses | Runs | Cost |
|---|---|---|---|
| ElevenLabs voice clone | [Chatterbox](https://github.com/resemble-ai/chatterbox) (MIT) | on your Mac | free |
| HeyGen avatar | [LatentSync](https://github.com/bytedance/LatentSync) (Apache-2.0) | Replicate GPU (a MacBook can't run it) | ~$0.10 per short video, measured and recorded |

One-time setup:

```bash
./scripts/setup_studio.sh                 # ffmpeg + Chatterbox in .venv-tts (free, ~2–3 GB)
# avatar only: make a token at https://replicate.com/account/api-tokens, add a card, then put
# REPLICATE_API_TOKEN=r8_... in .env
aios voice setup ~/Desktop/me-talking.m4a --mine      # 10–30 s of you talking, quiet room
aios avatar setup ~/Desktop/me-on-camera.mov --mine   # 15–60 s facing the camera, steady, good light
aios doctor                                           # Studio lines should say ready
```

Use it:

```bash
aios voice say "Missed calls are costing you jobs."      # WAV in your voice
aios voice say --from-run <draft run id> --item 2        # speak a script from `aios draft`
aios video make --file script.txt                        # talking-head MP4 of you
aios media list
```

Rules: only your own voice and face (`--mine`); agents can't use any of it; nothing is published.
Outputs are DRAFT files marked synthetic. When you upload one to YouTube, answer **Yes** to
"Altered or synthetic content". Chatterbox also adds an inaudible watermark to its audio.

## How it stays honest

- **Memory has provenance.** EXPLICIT (you said it), CONFIRMED (3+ of your decisions show it), INFERRED, HYPOTHESIS, SUPERSEDED. Agents can only write INFERRED or HYPOTHESIS. Corrections supersede; nothing is deleted.
- **Numbers come from code.** The CFO interprets metrics; it never calculates them. Each metric has one definition (`aios/modules/metrics.py`). Actuals, forecasts and estimates are never mixed.
- **Sources are real.** Research keeps only URLs the search tool actually returned. A "fact" without one is downgraded to interpretation.
- **The auditor is independent.** A BLOCK or REVIEW_REQUIRED from Risk always reaches you, whatever the CEO concludes.
- **Approval gates.** Only you can approve spending, communication, publishing, deletion, system changes and decisions. No agent can grant itself permissions or touch the audit log (the database rejects updates and deletes).
- **Budgets.** Per task, workflow, day, agent and model. When a limit would be crossed the run stops and returns what it finished.
- **Every model call is costed** (`model_usage`), so you can see which agent, workflow or model costs the most.
- **Improvements are tested before you decide.** A proposed routing or prompt change is benchmarked against the current setup; prompt changes become new versions that go live only when you approve and roll back in one step.

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
