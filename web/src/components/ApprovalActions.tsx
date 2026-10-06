import { useState } from "react";
import { api } from "../api";
import { useAction } from "../hooks";
import { href } from "../router";
import type { ApprovalDecision } from "../types";
import { ErrorBox } from "./EmptyState";

/** Approve / Reject with an optional note. After deciding, shows follow-up runs the server started. */
export function ApprovalActions({ approvalId, onDone, compact }: { approvalId: string; onDone?: (r: ApprovalDecision) => void; compact?: boolean }) {
  const [note, setNote] = useState("");
  const [result, setResult] = useState<ApprovalDecision | null>(null);
  // `status` is the approval's own status; handler results use their own keys
  // (improvement_status, decision_status, project_status).
  const [taken, setTaken] = useState<"approve" | "reject" | null>(null);
  const { busy, error, run } = useAction();

  async function decide(action: "approve" | "reject") {
    const r = await run(() => api.post<ApprovalDecision>(`/api/approvals/${encodeURIComponent(approvalId)}/${action}`, { note: note.trim() || null }));
    if (r) {
      setTaken(action);
      setResult(r);
      onDone?.(r);
    }
  }

  if (result) {
    const applied =
      result.applied && typeof result.applied === "object" ? (result.applied as { key: string; old: unknown; new: unknown }) : null;
    return (
      <div className="stack-sm">
        <div className={`callout tone-${taken === "approve" ? "green" : "red"}`}>
          <div className="callout-title">{taken === "approve" ? "Approved" : "Rejected"}</div>
          {result.improvement_id && result.improvement_status && (
            <div>Improvement is now {String(result.improvement_status).replace(/_/g, " ").toLowerCase()}.</div>
          )}
          {applied && (
            <div className="mono small">
              {applied.key}: {JSON.stringify(applied.old)} → {JSON.stringify(applied.new)}
            </div>
          )}
          {result.decision_status && <div>Decision is now {result.decision_status.replace(/_/g, " ").toLowerCase()}.</div>}
          {result.project_status && (
            <div>
              Project is now {result.project_status.toLowerCase()}.{" "}
              {result.project_id && <a href={href("projects", result.project_id)}>Open project</a>}
            </div>
          )}
          {typeof result.note === "string" && <div>{result.note}</div>}
          {result.follow_up_runs.length > 0 ? (
            <div className="mt-8">
              Started:{" "}
              {result.follow_up_runs.map((f, i) => (
                <span key={f.run_id}>
                  {i > 0 && ", "}
                  <a href={href("runs", f.run_id)}>{f.workflow} run</a>
                </span>
              ))}
            </div>
          ) : (
            (result.follow_up?.length ?? 0) > 0 && (
              <div className="mt-8 small muted">
                Follow-up workflows ({result.follow_up!.map((f) => f.workflow).join(", ")}) were not started: the server has no model key.
              </div>
            )
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="stack-sm">
      <div className={compact ? "row" : "stack-sm"}>
        <label className="sr-only" htmlFor={`note-${approvalId}`}>
          Note
        </label>
        <input
          id={`note-${approvalId}`}
          className="input"
          placeholder="Note (optional): why you decided this way"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          style={compact ? { flex: 1, minWidth: 180 } : undefined}
        />
        <div className="row">
          <button className="btn btn-approve" disabled={busy} onClick={() => decide("approve")}>
            Approve
          </button>
          <button className="btn btn-reject" disabled={busy} onClick={() => decide("reject")}>
            Reject
          </button>
        </div>
      </div>
      <ErrorBox error={error} />
    </div>
  );
}
