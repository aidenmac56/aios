import { useState } from "react";
import { api, ApiError } from "../api";
import { navigate } from "../router";
import type { CommandStarted, Health } from "../types";
import { ErrorBox } from "./EmptyState";

export const COMMANDS: { id: string; hint: string; placeholder: string; needsText: boolean }[] = [
  { id: "ceo", hint: "Ask the CEO anything; it plans which agents to use", placeholder: "Should I start with a YouTube channel or a newsletter?", needsText: true },
  { id: "board", hint: "CFO, CTO, CMO, Product and COO review a proposal in parallel", placeholder: "Offer a $497 AI audit to local service businesses", needsText: true },
  { id: "research", hint: "Sourced research with live search when available", placeholder: "How are small service businesses adopting AI receptionists in 2026?", needsText: true },
  { id: "market", hint: "Market research, positioning and customer problems", placeholder: "AI automation consulting for San Diego service businesses", needsText: true },
  { id: "draft", hint: "Write content in your voice: topics, scripts, positioning, emails. Drafts only", placeholder: "10 YouTube topics for San Diego service business owners", needsText: true },
  { id: "trends", hint: "Which trends have real evidence and matter to this company, and which are just buzz", placeholder: "AI tools for local service businesses", needsText: false },
  { id: "opportunity", hint: "Full build / don't-build evaluation with a 12-point scorecard", placeholder: "An AI receptionist for dental offices", needsText: true },
  { id: "decision", hint: "Options, trade-offs and a recommendation that you approve or reject", placeholder: "Should I charge $497 or $997 for the AI audit?", needsText: true },
  { id: "cto", hint: "Technology review scored on 10 dimensions", placeholder: "Which stack should the automation builds standardize on?", needsText: true },
  { id: "plan", hint: "Turn a goal into a project with milestones and tasks", placeholder: "Launch the weekly AI news YouTube channel", needsText: true },
  { id: "priorities", hint: "What to do next, what to pause, what is blocked", placeholder: "Optional focus, e.g. this week", needsText: false },
  { id: "finance", hint: "Financial state from imported transactions; works without a model key", placeholder: "Optional question for the CFO", needsText: false },
  { id: "audit", hint: "Audit the AI company and propose measured improvements", placeholder: "Optional focus, e.g. model costs", needsText: false },
  { id: "improve", hint: "Improvements backed only by measured data", placeholder: "Optional focus", needsText: false },
];

export function CommandBar({ health }: { health: Health | null }) {
  const [command, setCommand] = useState("ceo");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const spec = COMMANDS.find((c) => c.id === command) ?? COMMANDS[0];
  const noModel = health !== null && !health.llm_credentials && command !== "finance";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (spec.needsText && !text.trim()) {
      setError(new ApiError(0, "empty", `Type what you want ${command} to work on.`, null));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await api.post<CommandStarted>(`/api/commands/${encodeURIComponent(command)}`, { request: text.trim(), options: {} });
      setText("");
      navigate("runs", res.run_id);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="commandbar">
      <form className="cmd-form" onSubmit={submit} aria-label="Run a command">
        <span className="cmd-prompt" aria-hidden="true">
          aios
        </span>
        <label htmlFor="cmd-select" className="sr-only">
          Command
        </label>
        <select id="cmd-select" className="cmd-select" value={command} onChange={(e) => setCommand(e.target.value)}>
          {COMMANDS.map((c) => (
            <option key={c.id} value={c.id}>
              {c.id}
            </option>
          ))}
        </select>
        <label htmlFor="cmd-input" className="sr-only">
          Request
        </label>
        <input
          id="cmd-input"
          className="cmd-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={spec.placeholder}
          maxLength={8000}
          autoComplete="off"
        />
        <button className="cmd-run" type="submit" disabled={busy}>
          {busy ? "Starting…" : "Run"}
        </button>
      </form>
      <div className="cmd-hint">
        <span>{spec.hint}</span>
        {noModel && <span style={{ color: "var(--amber)" }}>No model key on the server: only finance runs. Add ANTHROPIC_API_KEY to .env and restart.</span>}
      </div>
      {error ? (
        <div className="cmd-error">
          <ErrorBox error={error} />
        </div>
      ) : null}
    </div>
  );
}
