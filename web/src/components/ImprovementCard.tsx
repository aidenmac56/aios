import { useState } from "react";
import { api } from "../api";
import { dateTime, humanize } from "../format";
import { useAction } from "../hooks";
import { href, navigate } from "../router";
import type { AppliedChange, CommandStarted, Improvement } from "../types";
import { Badge } from "./Badge";
import { Bullets, Card, KV } from "./Card";
import { ErrorBox } from "./EmptyState";

export function ImprovementCard({ imp, onChanged, readOnly }: { imp: Improvement; onChanged?: () => void; readOnly?: boolean }) {
  const { busy, error, run } = useAction();
  const [approvalId, setApprovalId] = useState<string | null>(null);
  const [rolling, setRolling] = useState(false);
  const [note, setNote] = useState("");
  const [restored, setRestored] = useState<string | null>(null);

  const canRequest = imp.status === "PROPOSED" || imp.status === "TESTED";
  const canRollback = imp.status === "IMPLEMENTED";
  const testable = canRequest && (imp.change_spec?.type === "routing_override" || imp.change_spec?.type === "prompt_addendum");
  const applied = imp.test_results?.applied;
  const tr = imp.test_results;

  async function test() {
    const r = await run(() =>
      api.post<CommandStarted>("/api/commands/test", { request: "", options: { improvement_id: imp.id } }),
    );
    if (r) navigate("runs", r.run_id);
  }

  async function request() {
    const r = await run(() => api.post<{ approval_id: string }>(`/api/improvements/${encodeURIComponent(imp.id)}/request`, {}));
    if (r) {
      setApprovalId(r.approval_id);
      onChanged?.();
    }
  }

  async function rollback() {
    const r = await run(() =>
      api.post<{ improvement_id: string; restored: Record<string, unknown> }>(`/api/improvements/${encodeURIComponent(imp.id)}/rollback`, { note: note.trim() || null }),
    );
    if (r) {
      const x = r.restored as { key?: string; value?: unknown; agent?: string; version?: number };
      setRestored(x.agent ? `${x.agent} back on prompt version ${x.version}` : `${x.key} restored to ${JSON.stringify(x.value)}`);
      setRolling(false);
      onChanged?.();
    }
  }

  return (
    <Card
      title={imp.title}
      sub={
        <span className="row" style={{ gap: 8 }}>
          <span>{humanize(imp.area)}</span>
          {imp.proposed_by && <span>Proposed by {imp.proposed_by.replace(/^agent:/, "")}</span>}
          <span>{dateTime(imp.created_at)}</span>
        </span>
      }
      actions={<Badge value={imp.status} />}
    >
      <div className="stack-sm">
        <p className="prose">{imp.problem}</p>
        {imp.evidence && imp.evidence.length > 0 && (
          <div>
            <div className="subhead">Evidence</div>
            <Bullets items={imp.evidence} />
          </div>
        )}
        <KV
          items={[
            ["Root cause", imp.root_cause],
            ["Change", imp.change],
            ["Expected impact", imp.expected_impact],
            ["Cost", imp.cost],
            ["Risk", imp.risk],
            ["Test plan", imp.test_plan],
            ["Rollback", imp.rollback],
            ["Success metric", imp.metric],
            [
              "Automatic change",
              imp.change_spec ? (
                imp.change_spec.type === "prompt_addendum" ? (
                  <span>
                    New prompt version for <strong>{imp.change_spec.key}</strong> adding: <em>{imp.change_spec.value}</em>
                  </span>
                ) : (
                  <span className="mono small">
                    {imp.change_spec.key} = {imp.change_spec.value}
                  </span>
                )
              ) : (
                <span className="muted">None; a human applies this change after approval.</span>
              ),
            ],
            [
              "Test result",
              tr?.verdict ? (
                <span>
                  <Badge value={tr.verdict === "WORSE" ? "FAILED" : "COMPLETED"} label={tr.verdict} />{" "}
                  score {tr.baseline?.avg_score.toFixed(3)} → {tr.candidate?.avg_score.toFixed(3)} (
                  {tr.candidate?.model}
                  {tr.candidate && tr.baseline && tr.candidate.config_version !== tr.baseline.config_version
                    ? `, prompt v${tr.candidate.config_version}`
                    : ""}
                  ), cost {(tr.cost_delta_usd ?? 0) >= 0 ? "+" : "−"}${Math.abs(tr.cost_delta_usd ?? 0).toFixed(4)} on the benchmark
                </span>
              ) : null,
            ],
            ["Applied", applied ? <span className="mono small">{describeApplied(applied)}</span> : null],
          ]}
        />
        {!readOnly && (
          <div className="stack-sm mt-8">
            {approvalId ? (
              <div className="callout tone-amber">
                <div className="callout-title">Approval requested</div>
                It is waiting on the <a href={href("decisions")}>Decisions page</a>.
              </div>
            ) : restored ? (
              <div className="callout tone-green">
                <div className="callout-title">Rolled back</div>
                <span className="mono small">{restored}</span>
              </div>
            ) : (
              <div className="row">
                {testable && (
                  <button className="btn" disabled={busy} onClick={test} title="Benchmark the current setup against this change">
                    {tr?.verdict ? "Re-test" : "Test it"}
                  </button>
                )}
                {canRequest && (
                  <button className="btn btn-primary" disabled={busy} onClick={request}>
                    Request implementation
                  </button>
                )}
                {canRollback && !rolling && (
                  <button className="btn btn-reject" disabled={busy} onClick={() => setRolling(true)}>
                    Roll back
                  </button>
                )}
              </div>
            )}
            {rolling && (
              <div className="inline-form">
                <label className="field">
                  <span className="label">Why roll back?</span>
                  <input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. quality dropped on research tasks" />
                </label>
                <div className="row">
                  <button className="btn btn-reject" disabled={busy} onClick={rollback}>
                    Roll back change
                  </button>
                  <button className="btn btn-ghost" onClick={() => setRolling(false)}>
                    Cancel
                  </button>
                </div>
              </div>
            )}
            <ErrorBox error={error} />
          </div>
        )}
      </div>
    </Card>
  );
}

function describeApplied(a: AppliedChange): string {
  if (a.type === "prompt") return `${a.agent}: prompt v${a.old_version} → v${a.new_version}`;
  return `${a.key}: ${JSON.stringify(a.old)} → ${JSON.stringify(a.new)}`;
}
