import { useState } from "react";
import { Badge, sentence } from "../components/Badge";
import { Bullets, Card, PageHead } from "../components/Card";
import { EmptyState, Gate } from "../components/EmptyState";
import { ImprovementCard } from "../components/ImprovementCard";
import { Table } from "../components/Table";
import { dateTime, usd } from "../format";
import { useApi } from "../hooks";
import { href } from "../router";
import type { AuditLogEntry, AuditRow, ChainVerify, Improvement, Issue } from "../types";

const IMP_FILTERS = [
  { id: "open", label: "Open", match: (s: string) => s === "PROPOSED" || s === "TESTING" || s === "TESTED" },
  { id: "applied", label: "Applied", match: (s: string) => s === "APPROVED" || s === "IMPLEMENTED" || s === "VERIFIED" },
  { id: "closed", label: "Closed", match: (s: string) => s === "REJECTED" || s === "ROLLED_BACK" },
  { id: "all", label: "All", match: () => true },
];

export function AuditsPage() {
  const audits = useApi<AuditRow[]>("/api/audits");
  const imps = useApi<Improvement[]>("/api/improvements");
  const log = useApi<AuditLogEntry[]>("/api/audit-log?limit=200");
  const verify = useApi<ChainVerify>("/api/audit-log/verify");
  const [filter, setFilter] = useState("open");
  // Cards acted on during this visit stay visible even if their new status leaves the filter,
  // so the confirmation (approval requested, rolled back) is not yanked away.
  const [touched, setTouched] = useState<string[]>([]);
  const f = IMP_FILTERS.find((x) => x.id === filter) ?? IMP_FILTERS[0];

  return (
    <>
      <PageHead title="Audits" sub="Independent reviews, the improvement loop, and the tamper-evident action log." />
      <div className="stack">
        <Card title="Improvements" sub="Every proposal cites measured evidence. Nothing is applied until you approve it." flush
          actions={
            <div className="segmented" role="group" aria-label="Filter improvements">
              {IMP_FILTERS.map((x) => (
                <button key={x.id} aria-pressed={filter === x.id} onClick={() => setFilter(x.id)}>
                  {x.label}
                </button>
              ))}
            </div>
          }
        >
          <div style={{ padding: "0 16px 12px" }}>
            <Gate data={imps.data} error={imps.error} retry={imps.reload} what="Loading improvements">
              {(list) => {
                const shown = list.filter((i) => f.match(i.status) || touched.includes(i.id));
                return shown.length === 0 ? (
                  <EmptyState title={list.length === 0 ? "No improvements proposed yet" : `No ${f.label.toLowerCase()} improvements`}>
                    {list.length === 0 ? "Run audit or improve from the command line; proposals backed by measurements appear here." : "Choose another filter."}
                  </EmptyState>
                ) : (
                  <div className="stack">
                    {shown.map((i) => (
                      <ImprovementCard
                        key={i.id}
                        imp={i}
                        onChanged={() => {
                          setTouched((t) => (t.includes(i.id) ? t : [...t, i.id]));
                          imps.reload();
                        }}
                      />
                    ))}
                  </div>
                );
              }}
            </Gate>
          </div>
        </Card>

        <Card title="Audits" sub="System audits and the risk agent's review of each decision run." flush>
          <Gate data={audits.data} error={audits.error} retry={audits.reload} what="Loading audits">
            {(list) =>
              list.length === 0 ? (
                <EmptyState title="No audits yet">Run audit to review the whole AI company, or any decision command to get a per-run risk audit.</EmptyState>
              ) : (
                <div>
                  {list.map((a) => (
                    <AuditItem key={a.id} a={a} />
                  ))}
                </div>
              )
            }
          </Gate>
        </Card>

        <Card
          title="Audit log"
          sub="Append-only and hash-chained: each entry includes the previous entry's hash, so any edit breaks the chain."
          actions={
            verify.data ? (
              verify.data.ok ? (
                <Badge tone="green" label={`Chain intact, ${verify.data.entries} entries`} />
              ) : (
                <Badge tone="red" label={`Chain broken at #${verify.data.first_bad_seq}`} />
              )
            ) : verify.error ? (
              <Badge tone="red" label="Could not verify" />
            ) : (
              <span className="muted small">Verifying…</span>
            )
          }
          flush
        >
          <Gate data={log.data} error={log.error} retry={log.reload} what="Loading audit log">
            {(rows) => (
              <Table
                dense
                rows={rows}
                rowKey={(e) => String(e.seq)}
                empty={<EmptyState title="The log is empty">Every consequential action (imports, approvals, config changes, agent runs) is recorded here.</EmptyState>}
                columns={[
                  { key: "seq", header: "#", num: true, render: (e) => e.seq },
                  { key: "at", header: "When", render: (e) => <span className="nowrap small">{dateTime(e.at)}</span> },
                  { key: "who", header: "Who", render: (e) => <span className="small nowrap">{e.who}</span> },
                  { key: "what", header: "What", render: (e) => <span className="mono small nowrap">{e.what}</span> },
                  { key: "why", header: "Why", className: "cell-wide", render: (e) => <span className="small ink-2">{e.why ? (e.why.length > 200 ? e.why.slice(0, 200) + "…" : e.why) : "—"}</span> },
                  {
                    key: "res",
                    header: "Result",
                    render: (e) =>
                      e.error ? (
                        <span title={e.error}>
                          <Badge tone="red" label={e.result ?? "Error"} />
                        </span>
                      ) : e.result ? (
                        <Badge value={e.result === "OK" ? "COMPLETED" : e.result} label={e.result === "OK" ? "OK" : sentence(e.result)} />
                      ) : (
                        <span className="muted">—</span>
                      ),
                  },
                  { key: "cost", header: "Cost", num: true, render: (e) => (e.cost_usd ? usd(e.cost_usd) : "—") },
                ]}
              />
            )}
          </Gate>
        </Card>
      </div>
    </>
  );
}

function isIssue(x: unknown): x is Issue {
  return !!x && typeof x === "object" && "problem" in x && "severity" in x;
}

function AuditItem({ a }: { a: AuditRow }) {
  const findings = a.findings ?? [];
  return (
    <div className="mem-item">
      <div className="row-between">
        <span className="row" style={{ gap: 8 }}>
          <Badge value={a.verdict ?? undefined} kind="verdict" label={a.verdict ? undefined : "No verdict"} />
          <span className="row-title">{a.scope === "workflow" ? "Decision run audit" : `${sentence(a.scope)} audit`}</span>
        </span>
        <span className="small muted">{dateTime(a.created_at)}</span>
      </div>
      {a.summary && <p className="ink-2 mt-8 prose">{a.summary.length > 600 ? a.summary.slice(0, 600) + "…" : a.summary}</p>}
      {findings.length > 0 && (
        <details className="disclose mt-8">
          <summary>
            {findings.length} finding{findings.length === 1 ? "" : "s"}
          </summary>
          <div className="mt-8">
            <Bullets
              items={findings.map((x, i) =>
                isIssue(x) ? (
                  <span key={i}>
                    <Badge value={x.severity} kind="severity" /> <b>{x.target}</b>: {x.problem} <span className="muted">Fix: {x.fix}</span>
                  </span>
                ) : typeof x === "string" ? (
                  x
                ) : (
                  JSON.stringify(x)
                ),
              )}
            />
          </div>
        </details>
      )}
      <div className="row-meta">
        {a.auditor && <span>Auditor {a.auditor}</span>}
        {a.workflow_run_id && <a href={href("runs", a.workflow_run_id)}>Open run</a>}
      </div>
    </div>
  );
}
