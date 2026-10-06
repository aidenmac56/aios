import { useState } from "react";
import { Badge } from "../components/Badge";
import { Callout, Card, Meter, PageHead, Progress } from "../components/Card";
import { EmptyState, Gate } from "../components/EmptyState";
import { FinanceSnapshot } from "../components/FinanceSnapshot";
import { actorLabel, eventText, eventTone } from "../events";
import { dateOnly, relative, usd } from "../format";
import { useApi } from "../hooks";
import { href } from "../router";
import type { CompanyStatus } from "../types";

export function ExecutivePage() {
  const { data, error, reload } = useApi<CompanyStatus>("/api/status", { pollMs: 30000 });
  return (
    <Gate data={data} error={error} retry={reload} what="Loading company status">
      {(st) => <Executive st={st} />}
    </Gate>
  );
}

const ACTIVITY_SHOWN = 10;

function Executive({ st }: { st: CompanyStatus }) {
  const [allActivity, setAllActivity] = useState(false);
  const company = st.companies[0];
  const dn = st.decisions_needed;
  const fin = st.finance;
  const ai = st.ai_costs;

  return (
    <>
      <PageHead
        title={company ? company.name : "Executive"}
        sub={
          company?.mission ?? (
            <>
              No company profile yet. Load the founder seed with <code>aios seed</code>.
            </>
          )
        }
      />

      <div className="stack">
        {st.contradictions.length > 0 && (
          <div>
            {st.contradictions.map((c, i) => (
              <Callout key={i} tone="orange" title="Contradiction">
                {c}
              </Callout>
            ))}
          </div>
        )}

        <Card
          title="Decisions needed"
          sub="Nothing that spends money, commits you or changes the system happens without your approval."
          actions={<a href={href("decisions")}>Open decisions</a>}
        >
          <div className="decision-strip">
            <div className={dn.pending_approvals ? "decision-count" : "decision-count zero"} aria-label={`${dn.pending_approvals} pending approvals`}>
              {dn.pending_approvals}
            </div>
            {dn.items.length === 0 ? (
              <p className="muted">Nothing is waiting on you. New approvals appear here when a run recommends an action.</p>
            ) : (
              <ul className="rows">
                {dn.items.map((a) => (
                  <li key={a.id}>
                    <div className="row-title">{a.action}</div>
                    <div className="row-meta">
                      <Badge value={a.type} tone="gray" />
                      <span>Requested by {actorLabel(a.requested_by)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </Card>

        <div className="grid">
          <div className="span-7 stack">
            <Card title="Priorities" sub="Open tasks ranked by priority, what they unlock, due date and readiness." actions={<a href={href("projects")}>All projects</a>}>
              {st.priorities.length === 0 ? (
                <EmptyState title="No open tasks">Approve a build decision or run plan to create a project with tasks.</EmptyState>
              ) : (
                <ul className="rows">
                  {st.priorities.map((t) => (
                    <li key={t.task_id}>
                      <div className="row-between">
                        <span className="row-title">{t.title}</span>
                        <Badge value={t.status} />
                      </div>
                      <div className="row-meta">
                        {t.project && <span>{t.project}</span>}
                        <span>Priority {t.priority}</span>
                        {t.owner && <span>Owner {actorLabel(t.owner)}</span>}
                        {t.unlocks > 0 && <span>Unlocks {t.unlocks}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Active projects" actions={<a href={href("projects")}>Projects</a>}>
              {st.projects.length === 0 ? (
                <EmptyState title="No projects yet">Projects are created from approved decisions or the plan command.</EmptyState>
              ) : (
                <ul className="rows">
                  {st.projects.map((p) => (
                    <li key={p.id}>
                      <div className="row-between">
                        <a className="row-title" href={href("projects", p.id)}>
                          {p.name}
                        </a>
                        <Badge value={p.status} />
                      </div>
                      <div className="row mt-8" style={{ flexWrap: "nowrap" }}>
                        <div style={{ flex: 1 }}>
                          <Progress pct={p.progress_pct} label={`${p.name} progress`} />
                        </div>
                        <span className="small tnum nowrap">
                          {p.tasks_done}/{p.tasks_total} tasks
                        </span>
                      </div>
                      <div className="row-meta">
                        <span>Priority {p.priority}</span>
                        <span>Expected cost {p.expected_cost}</span>
                        {p.blocked_tasks > 0 && <span style={{ color: "var(--red)" }}>{p.blocked_tasks} blocked</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Card title="Opportunities" sub="Build decisions under consideration.">
              {st.opportunities.length === 0 ? (
                <EmptyState title="No opportunities evaluated">Run opportunity with an idea to get a build / don't-build brief.</EmptyState>
              ) : (
                <ul className="rows">
                  {st.opportunities.map((o) => (
                    <li key={o.decision_id}>
                      <div className="row-between">
                        <span className="row-title">{o.question}</span>
                        <Badge value={o.status} />
                      </div>
                      {o.recommendation && <div className="small ink-2 mt-8">{o.recommendation}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <div className="span-5 stack">
            <Card title="AI operating cost" sub="Estimated from model list prices." actions={<a href={href("costs")}>Breakdown</a>}>
              <div className="stack-sm">
                <div className="row-between">
                  <span className="muted small">Last 30 days</span>
                  <span className="tnum" style={{ fontSize: 18, fontWeight: 620 }}>
                    {usd(ai.last_30d_usd)}
                  </span>
                </div>
                <div className="row-between">
                  <span className="muted small">Today vs daily limit</span>
                  <span className="tnum small">
                    {usd(ai.today_usd)} of {usd(ai.daily_limit_usd, { precise: false })}
                  </span>
                </div>
                <Meter value={ai.today_usd} max={ai.daily_limit_usd} label="Today's AI spend against the daily limit" />
              </div>
            </Card>

            <Card title="Major risks" sub="Latest independent audits." actions={<a href={href("audits")}>Audits</a>}>
              {st.risks.length === 0 ? (
                <EmptyState title="No audits yet">Every decision run is audited by the risk agent; run audit to review the whole system.</EmptyState>
              ) : (
                <ul className="rows">
                  {st.risks.map((r) => (
                    <li key={r.audit_id}>
                      <div className="row-between">
                        <Badge value={r.verdict ?? "UNKNOWN"} kind="verdict" label={r.verdict ? undefined : "No verdict"} />
                        <span className="small muted">{relative(r.at)}</span>
                      </div>
                      {r.summary && <p className="small ink-2 mt-8">{r.summary.length > 260 ? r.summary.slice(0, 260) + "…" : r.summary}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            {st.improvements.length > 0 && (
              <Card title="Proposed improvements" actions={<a href={href("audits")}>Review</a>}>
                <ul className="rows">
                  {st.improvements.map((i) => (
                    <li key={i.id} className="row-between">
                      <span>{i.title}</span>
                      <Badge value={i.status} />
                    </li>
                  ))}
                </ul>
              </Card>
            )}
          </div>
        </div>

        <Card
          title="Finance"
          sub={fin.has_data && fin.period ? `Records from ${dateOnly(fin.period.from)} to ${dateOnly(fin.period.to)}` : undefined}
          actions={<a href={href("finance")}>Finance</a>}
        >
          {fin.has_data ? (
            <div className="stack-sm">
              <FinanceSnapshot totals={fin.totals} burn={fin.burn} cash={fin.cash} runway={fin.runway} />
              {fin.recurring && fin.recurring.items.length > 0 && (
                <p className="small muted">
                  Recurring costs {fin.recurring.display} per month across {fin.recurring.items.length} subscription{fin.recurring.items.length === 1 ? "" : "s"}.
                </p>
              )}
            </div>
          ) : (
            <EmptyState title="No financial records" action={<a className="btn btn-sm" href={href("finance")}>Import a CSV</a>}>
              {fin.note ?? "No transactions yet."} Revenue, burn, cash and runway stay unknown until you import a bank CSV.
            </EmptyState>
          )}
        </Card>

        <div className="grid">
          <div className="span-6">
            <Card title="Recent workflows" actions={<a href={href("runs")}>All runs</a>} flush>
              {st.recent_workflows.length === 0 ? (
                <EmptyState title="No runs yet">Use the command line above to start one, for example ceo with a question.</EmptyState>
              ) : (
                <ul className="rows pad">
                  {st.recent_workflows.map((w) => (
                    <li key={w.id}>
                      <div className="row-between">
                        <a href={href("runs", w.id)} className="row-title">
                          <span className="mono">{w.command}</span>
                        </a>
                        <Badge value={w.status} />
                      </div>
                      {w.request && <div className="small ink-2 mt-8">{w.request}</div>}
                      <div className="row-meta">
                        <span>{relative(w.at)}</span>
                        <span>{usd(w.cost_usd)}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          <div className="span-6">
            <Card
              title="Recent activity"
              flush
              actions={
                st.recent_activity.length > ACTIVITY_SHOWN ? (
                  <button className="link-btn small" onClick={() => setAllActivity((v) => !v)} aria-expanded={allActivity}>
                    {allActivity ? "Show fewer" : `Show all ${st.recent_activity.length}`}
                  </button>
                ) : undefined
              }
            >
              {st.recent_activity.length === 0 ? (
                <EmptyState title="No activity yet">Imports, runs, approvals and decisions are logged here as they happen.</EmptyState>
              ) : (
                <ul className="rows pad">
                  {(allActivity ? st.recent_activity : st.recent_activity.slice(0, ACTIVITY_SHOWN)).map((e, i) => (
                    <li key={i} className="row-between" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
                      <span className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap", gap: 9 }}>
                        <span className={`dot`} style={{ marginTop: 7, background: `var(--${eventTone(e.type, e.payload)})` }} />
                        <span>
                          <span>{eventText(e.type, e.payload)}</span>
                          <span className="muted small" style={{ display: "block" }}>
                            {actorLabel(e.actor)}
                          </span>
                        </span>
                      </span>
                      <span className="small muted nowrap">{relative(e.at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </>
  );
}
