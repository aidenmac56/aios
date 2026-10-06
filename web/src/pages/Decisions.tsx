import { useState } from "react";
import { api } from "../api";
import { ApprovalActions } from "../components/ApprovalActions";
import { Badge, sentence } from "../components/Badge";
import { SourceRef } from "../components/BriefView";
import { Bullets, Callout, Card, KV, PageHead } from "../components/Card";
import { EmptyState, ErrorBox, Gate } from "../components/EmptyState";
import { actorLabel } from "../events";
import { dateTime, relative, usd } from "../format";
import { useAction, useApi } from "../hooks";
import { href } from "../router";
import type { Approval, Decision, Evidence } from "../types";

export function DecisionsPage() {
  const approvals = useApi<Approval[]>("/api/approvals?status=PENDING");
  const decisions = useApi<Decision[]>("/api/decisions");
  // Approvals decided on this visit stay on screen (keyed by id) so their result and follow-up links remain visible.
  const [decided, setDecided] = useState<Approval[]>([]);
  const onDecided = (a: Approval) => {
    setDecided((d) => (d.some((x) => x.id === a.id) ? d : [...d, a]));
    approvals.reload();
    decisions.reload();
  };
  const shown = approvals.data ? [...approvals.data, ...decided.filter((d) => !approvals.data!.some((a) => a.id === d.id))] : null;

  return (
    <>
      <PageHead title="Decisions" sub="Approvals waiting on you, then every decision with its outcome." />
      <div className="stack">
        <section className="stack">
          <h2 className="panel-title">Waiting on you</h2>
          <Gate data={shown} error={approvals.error} retry={approvals.reload} what="Loading approvals">
            {(list) =>
              list.length === 0 ? (
                <EmptyState title="Nothing to approve">When a run recommends spending, building, or changing the system, it stops here until you decide.</EmptyState>
              ) : (
                <div className="stack">
                  {list.map((a) => (
                    <ApprovalCard key={a.id} a={a} onDone={() => onDecided(a)} />
                  ))}
                </div>
              )
            }
          </Gate>
        </section>

        <section className="stack">
          <h2 className="panel-title mt-8">History</h2>
          <Gate data={decisions.data} error={decisions.error} retry={decisions.reload} what="Loading decisions">
            {(list) =>
              list.length === 0 ? (
                <EmptyState title="No decisions recorded">Run decision or opportunity to get a recommendation you can approve or reject.</EmptyState>
              ) : (
                <div className="stack">
                  {list.map((d) => (
                    <DecisionCard key={d.id} d={d} onChanged={decisions.reload} />
                  ))}
                </div>
              )
            }
          </Gate>
        </section>
      </div>
    </>
  );
}

function ApprovalCard({ a, onDone }: { a: Approval; onDone: () => void }) {
  return (
    <Card
      title={a.action}
      className="tone-edge tone-amber"
      sub={
        <span className="row" style={{ gap: 10 }}>
          <span>{sentence(a.type)}</span>
          <span>Requested by {actorLabel(a.requested_by)}</span>
          <span>{relative(a.created_at)}</span>
        </span>
      }
    >
      <div className="stack-sm">
        <KV
          items={[
            ["Reason", a.reason],
            ["Expected effect", a.expected_effect],
            ["Estimated cost", a.cost_usd !== null ? `${usd(a.cost_usd, { precise: false })} (estimate)` : null],
            ["Risks", a.risks && a.risks.length ? <Bullets items={a.risks} /> : null],
          ]}
        />
        <ApprovalActions approvalId={a.id} onDone={onDone} compact />
      </div>
    </Card>
  );
}

function isEvidence(e: unknown): e is Evidence {
  return !!e && typeof e === "object" && "claim" in e && "source" in e;
}

function DecisionCard({ d, onChanged }: { d: Decision; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const canRecord = d.status === "APPROVED" && !d.outcome_assessment;
  const evidence = (d.evidence ?? []).filter(isEvidence);
  return (
    <Card
      title={d.question}
      sub={
        <span className="row" style={{ gap: 10 }}>
          {d.decision_type && <span>{sentence(d.decision_type)}</span>}
          {d.decision_maker && <span>Decided by {d.decision_maker === "founder" ? "you" : d.decision_maker}</span>}
          <span>{dateTime(d.decided_at ?? d.created_at)}</span>
        </span>
      }
      actions={
        <>
          {d.outcome_assessment && <Badge value={d.outcome_assessment} label={`Outcome: ${sentence(d.outcome_assessment)}`} />}
          <Badge value={d.status} />
        </>
      }
    >
      <div className="stack-sm">
        {d.decision_maker?.startsWith("delegated") && (
          <Callout tone="amber">Made on your behalf when you asked for a starting point. Not yet confirmed by you.</Callout>
        )}
        <KV
          items={[
            ["Recommendation", d.recommendation],
            ["Final decision", d.final_decision],
            ["Confidence", d.confidence ? <Badge value={d.confidence} kind="confidence" /> : null],
            ["Reversibility", d.reversibility ? sentence(d.reversibility) : null],
            ["Expected result", d.expected_result],
          ]}
        />
        {d.outcome_assessment && (
          <Callout tone={d.outcome_assessment === "GOOD" ? "green" : d.outcome_assessment === "POOR" ? "red" : "amber"} title={`Outcome recorded: ${sentence(d.outcome_assessment)}`}>
            <div>{d.actual_result}</div>
            {d.outcome_why && <div className="small mt-8">Why: {d.outcome_why}</div>}
          </Callout>
        )}

        {(d.options.length > 0 || d.reasoning || evidence.length > 0) && (
          <button className="link-btn small" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
            {open ? "Hide details" : `Show reasoning${d.options.length ? `, ${d.options.length} options` : ""}${evidence.length ? `, ${evidence.length} evidence` : ""}`}
          </button>
        )}
        {open && (
          <div className="stack-sm">
            {d.reasoning && (
              <div>
                <div className="subhead">Reasoning</div>
                <p className="ink-2 pre-line prose">{d.reasoning}</p>
              </div>
            )}
            {d.options.length > 0 && (
              <div>
                <div className="subhead">Options</div>
                <div className="options">
                  {d.options.map((o) => (
                    <div key={o.label} className={o.recommended ? "option recommended" : "option"}>
                      <div className="row-between">
                        <h4>{o.label}</h4>
                        {o.recommended && <Badge tone="accent" label="Recommended" />}
                      </div>
                      {o.description && <p className="small ink-2">{o.description}</p>}
                      <div className="row-meta">
                        <span>Expected value: {o.expected_value || "—"}</span>
                        <span>Risk: {o.risk || "—"}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {evidence.length > 0 && (
              <div>
                <div className="subhead">Evidence</div>
                <ul className="bullets">
                  {evidence.map((e, i) => (
                    <li key={i}>
                      {e.claim} <SourceRef source={e.source} />
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="row">
          {d.workflow_run_id && (
            <a className="small" href={href("runs", d.workflow_run_id)}>
              Open the run that produced this
            </a>
          )}
        </div>
        {canRecord && <OutcomeForm decisionId={d.id} onSaved={onChanged} />}
      </div>
    </Card>
  );
}

function OutcomeForm({ decisionId, onSaved }: { decisionId: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [actual, setActual] = useState("");
  const [assessment, setAssessment] = useState<"GOOD" | "MIXED" | "POOR">("GOOD");
  const [why, setWhy] = useState("");
  const { busy, error, run, setError } = useAction();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!actual.trim() || !why.trim()) {
      setError(new Error("Describe what actually happened and why you judge it that way."));
      return;
    }
    const r = await run(() => api.post<Decision>(`/api/decisions/${encodeURIComponent(decisionId)}/outcome`, { actual_result: actual.trim(), assessment, why: why.trim() }));
    if (r) onSaved();
  }

  if (!open) {
    return (
      <div>
        <button className="btn btn-sm" onClick={() => setOpen(true)}>
          Record outcome
        </button>
      </div>
    );
  }
  return (
    <form className="inline-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor={`actual-${decisionId}`}>What actually happened</label>
        <textarea id={`actual-${decisionId}`} className="textarea" value={actual} onChange={(e) => setActual(e.target.value)} />
      </div>
      <div className="field">
        <span className="label">Assessment</span>
        <div className="segmented" role="group" aria-label="Assessment">
          {(["GOOD", "MIXED", "POOR"] as const).map((a) => (
            <button type="button" key={a} aria-pressed={assessment === a} onClick={() => setAssessment(a)}>
              {sentence(a)}
            </button>
          ))}
        </div>
      </div>
      <div className="field">
        <label htmlFor={`why-${decisionId}`}>Why</label>
        <input id={`why-${decisionId}`} className="input" value={why} onChange={(e) => setWhy(e.target.value)} />
      </div>
      <div className="row">
        <button className="btn btn-primary" type="submit" disabled={busy}>
          Save outcome
        </button>
        <button className="btn btn-ghost" type="button" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      <ErrorBox error={error} />
    </form>
  );
}
