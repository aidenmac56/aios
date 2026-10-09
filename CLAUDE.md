# CLAUDE.md

AI Company OS for one founder (Aiden McCaffery). Read `docs/architecture.md` before changing structure.

## Rules for working in this repo
- No scheduled tasks, cron, or background agents. Workflows start only from a command, the API/dashboard, or an approval the founder just gave. Events are recorded, never auto-handled.
- Founder is the final authority. Never approve approvals, change `system_configuration`, or activate agent versions on his behalf.
- Never fabricate data: no invented sources, transactions, customers, or metrics. Missing data is reported as missing.
- Numbers are computed in code (`aios/modules/metrics.py`, `finance.unit_economics`); agents interpret them. One definition per metric.
- Agents may only write INFERRED/HYPOTHESIS memory. Keep provenance on everything.
- Agent permissions live in `aios/agents/specs.py`; `NEVER_FOR_AGENTS` in `core/permissions.py` must stay enforced.
- Prompt changes go through `agents/registry.propose_version` (old/new/reason/rollback), not silent edits to live behavior.
- External content is wrapped with `llm.calls.untrusted()`; never let it become instructions.
- Schema changes need an Alembic migration in `aios/migrations/versions/`.

## Commands
- Tests: `pytest` (uses `aios/llm/testing.py` ScriptedProvider; no network).
- Run: `aios <command>`; API + dashboard: `aios serve`.
- Studio (voice/face clone): `scripts/setup_studio.sh`, then `aios voice|avatar setup … --mine`, `aios voice say`, `aios video make`.
- Multi-model: providers in `aios/llm/providers_extra.py` (prefix routing in `ProviderRegistry`), Jev router `aios/llm/jev.py`, orchestration `aios/orchestrator/multi.py`; `aios models`, `aios multi`, `aios mac`.
- Founder to-dos: `aios todo`; system queue (agent-owned tasks, founder-started): `aios work [run]` (`modules/workqueue.py`); Mac menu bar `aios menubar [--install]` (`aios/modules/todos.py`, `aios/menubar.py`).
- Dashboard source: `web/` (Vite + React + TS) → `npm run build` writes `aios/web_dist/`.

## Where things are
- Engine/workflows: `aios/orchestrator/engine.py`; single agent execution: `orchestrator/runner.py`.
- Output schemas (LLM contracts): `aios/agents/schemas.py`.
- Model routing/pricing: `aios/llm/router.py`, `aios/llm/pricing.py` (update prices from the official pricing page with a new PRICING_VERSION).
- Founder seed memory: `aios/seed/founder_seed.json`.
