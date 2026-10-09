import { useEffect, useMemo, useRef, useState } from "react";
import { ApprovalActions } from "../components/ApprovalActions";
import { Badge, sentence } from "../components/Badge";
import { BriefView, ResearchOutputView, RiskAuditView, TwinView, UnitEconomicsView } from "../components/BriefView";
import { Bullets, Callout, Card, KV, Meter, PageHead } from "../components/Card";
import { EmptyState, ErrorBox, Loading } from "../components/EmptyState";
import { FindingView } from "../components/FindingView";
import { FinanceSnapshot } from "../components/FinanceSnapshot";
import { ImprovementCard } from "../components/ImprovementCard";
import { Table } from "../components/Table";
import { DraftView, TestView, TrendsView } from "../components/TestAndTrends";
import { dateTime, duration, humanize, parseDate, shortId, usd } from "../format";
import { useApi } from "../hooks";
import { href } from "../router";
import type { AgentFindingLike, AgentRunRow, Approval, PlannedTask, PrioritiesOutput, RiskAudit, RunDetail, RunResult } from "../types";

const ACTIVE = new Set(["PENDING", "RUNNING"]);

export function RunDetailPage({ id }: { id: string }) {
  // Poll every 2 s while the run is PENDING/RUNNING; stop as soon as it settles.
  const [polling, setPolling] = useState(true);
  const { data: run, error, reload } = useApi<RunDetail>(`/api/runs/${encodeURIComponent(id)}`, { pollMs: polling ? 2000 : null });
  useEffect(() => {
    if (run) setPolling(ACTIVE.has(run.status));
  }, [run]);

  if (!run) {
    if (error) return <ErrorBox error={error} retry={reload} />;
    return <Loading what="Loading run" />;
  }
  return (
    <Run
      run={run}
      active={ACTIVE.has(run.status)}
      reload={() => {
        // approving can start follow-up work and change this run's status
        setPolling(true);
        reload();
      }}
    />
  );
}

/** The agent-run row from the API has no agent_id; infer it from the run's own records. */
function inferAgents(run: RunDetail): Map<string, string> {
  const map = new Map<string, string>();
  const res = run.result;
  if (res?.agents) {
    for (const a of Object.values(res.agents)) if (a.run_id) map.set(a.run_id, a.agent);
  }
  const walk = (v: unknown, depth: number) => {
    if (!v || typeof v !== "object" || depth > 4) return;
    if (Array.isArray(v)) {
      v.forEach((x) => walk(x, depth + 1));
      return;
    }
    const o = v as Record<string, unknown>;
    if (typeof o._run_id === "string" && typeof o._agent === "string") map.set(o._run_id, o._agent);
    for (const x of Object.values(o)) walk(x, depth + 1);
  };
  walk(res, 0);
  const starts = (run.progress ?? [])
    .map((p) => /^([a-z_]+) started \(([^)]+)\): (.*)$/s.exec(p.msg))
    .filter((m): m is RegExpExecArray => !!m);
  for (const r of run.agent_runs) {
    if (r.agent_id) map.set(r.id, r.agent_id);
    if (map.has(r.id)) continue;
    const hit = starts.find((m) => m[2] === r.model && !!r.objective && r.objective.startsWith(m[3].slice(0, 80)));
    if (hit) map.set(r.id, hit[1]);
  }
  return map;
}

function Run({ run, active, reload }: { run: RunDetail; active: boolean; reload: () => void }) {
  const res: RunResult = run.result ?? {};
  const agentOf = useMemo(() => inferAgents(run), [run]);
  const approvalId = res.approval_id ?? res.created?.approval_id ?? null;
  const elapsed = (() => {
    const a = parseDate(run.created_at);
    return a ? Date.now() - a.getTime() : null;
  })();

  return (
    <>
      <PageHead
        crumb={
          <a href={href("runs")}>Runs</a>
        }
        title={
          <span className="row" style={{ gap: 10 }}>
            <span className="mono">{run.command}</span>
            <Badge value={run.status} size="lg" />
          </span>
        }
        sub={run.request ? run.request : <span className="muted">No request text</span>}
      />

      <div className="stack">
        <div className="stats">
          <div className="stat">
            <div className="stat-label">Cost vs budget</div>
            <div className="stat-value">
              {usd(run.cost_usd)} <span className="muted" style={{ fontSize: 13, fontWeight: 400 }}>of {usd(run.budget_usd, { precise: false })}</span>
            </div>
            <div className="mt-8">
              <Meter value={run.cost_usd} max={run.budget_usd} label="Run cost against budget" />
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Started</div>
            <div className="stat-value" style={{ fontSize: 15 }}>
              {dateTime(run.created_at)}
            </div>
            <div className="stat-note">{active && elapsed !== null ? `Running for ${duration(elapsed)}` : `Importance ${run.importance}`}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Agent runs</div>
            <div className="stat-value">{run.agent_runs.length}</div>
            <div className="stat-note">{run.agent_runs.filter((a) => a.status === "FAILED").length} failed</div>
          </div>
          {run.decision_id && (
            <div className="stat">
              <div className="stat-label">Decision</div>
              <div className="stat-value" style={{ fontSize: 15 }}>
                <a href={href("decisions")} className="mono">
                  {shortId(run.decision_id)}
                </a>
              </div>
              <div className="stat-note">Recorded in decision history</div>
            </div>
          )}
        </div>

        {run.error && (
          <Callout tone={run.status === "PARTIAL" ? "orange" : "red"} title={run.status === "PARTIAL" ? "Stopped early" : "Run failed"}>
            {run.error}
          </Callout>
        )}

        {approvalId && <ApprovalPanel approvalId={approvalId} onDone={reload} />}

        {active && !res.brief && (
          <Callout tone="blue" title="Working">
            Agents are running. This page updates every two seconds.
          </Callout>
        )}

        <ResultSections res={res} run={run} />

        <div className="grid">
          <div className={run.understanding || run.plan ? "span-5" : "span-12"}>
            <ProgressLog run={run} active={active} />
          </div>
          <div className={run.understanding || run.plan ? "span-7" : "sr-only"}>
            {run.understanding && (
              <Card title="How the CEO understood the request">
                <KV
                  items={[
                    ["Intent", run.understanding.intent],
                    ["Type", sentence(run.understanding.request_type)],
                    ["Decision question", run.understanding.decision_question || null],
                    ["Key questions", run.understanding.key_questions.length ? <Bullets items={run.understanding.key_questions} /> : null],
                    ["Missing information", run.understanding.missing_information.length ? <Bullets items={run.understanding.missing_information} /> : null],
                  ]}
                />
              </Card>
            )}
            {run.plan && run.plan.tasks && (
              <Card title="Work plan" sub={run.plan.rationale} className={run.understanding ? "mt-16" : undefined}>
                <PlannedTasks tasks={run.plan.tasks} />
                {run.plan.skipped_agents.length > 0 && (
                  <p className="small muted mt-8">Skipped: {run.plan.skipped_agents.join("; ")}</p>
                )}
              </Card>
            )}
          </div>
        </div>

        {run.result && (
          <details className="disclose">
            <summary>Raw result JSON{res.observations ? ", including the measured observations the auditors used" : ""}</summary>
            <pre className="codeblock">{JSON.stringify(run.result, null, 2)}</pre>
          </details>
        )}

        <Card title="Agent runs" sub="Every model call is routed by tier; the reason is recorded." flush>
          <Table<AgentRunRow>
            rows={run.agent_runs}
            rowKey={(r) => r.id}
            empty={<EmptyState title={active ? "No agent has started yet" : "No agents ran"}>{active
                  ? "Agent runs appear here as they start."
                  : run.cost_usd > 0
                    ? "This workflow called models directly (for example benchmark cases) rather than through agents; its model calls are on the AI costs page."
                    : "This workflow computed its result without a model."}</EmptyState>}
            columns={[
              {
                key: "agent",
                header: "Agent",
                render: (r) => {
                  const a = agentOf.get(r.id);
                  return a ? (
                    <a href={href("agents", a)} className="nowrap">
                      {a.toUpperCase().length <= 3 ? a.toUpperCase() : humanize(a)}
                    </a>
                  ) : (
                    <span className="muted mono small" title="The API does not return the agent id for this row">
                      {shortId(r.id)}
                    </span>
                  );
                },
              },
              { key: "status", header: "Status", render: (r) => <Badge value={r.status} /> },
              {
                key: "model",
                header: "Model",
                render: (r) => (
                  <div>
                    <div className="mono small nowrap">{r.model ?? "—"}</div>
                    <div className="small muted">{r.tier ?? ""}</div>
                  </div>
                ),
              },
              { key: "why", header: "Routing reason", render: (r) => <span className="small ink-2">{r.routing_reason ?? "—"}</span>, className: "cell-mid" },
              { key: "cost", header: "Cost", num: true, render: (r) => usd(r.cost_usd) },
              { key: "dur", header: "Duration", num: true, render: (r) => duration(r.duration_ms) },
              {
                key: "summary",
                header: "Summary",
                className: "cell-wide",
                render: (r) =>
                  r.error ? (
                    <span style={{ color: "var(--red)" }}>{r.error}</span>
                  ) : (
                    <span className="small ink-2">{r.summary ?? (r.objective ? r.objective.slice(0, 160) : "—")}</span>
                  ),
              },
            ]}
          />
        </Card>
      </div>
    </>
  );
}

function ProgressLog({ run, active }: { run: RunDetail; active: boolean }) {
  const ref = useRef<HTMLOListElement>(null);
  const entries = run.progress ?? [];
  useEffect(() => {
    if (active && ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [entries.length, active]);
  return (
    <Card title="Progress" sub={active ? "Live" : undefined} flush>
      {entries.length === 0 ? (
        <EmptyState title={active ? "Waiting for the first step" : "No progress was logged"}>
          {active ? "Steps appear as each agent starts and finishes." : "This run did not report intermediate steps."}
        </EmptyState>
      ) : (
        <ol className="log" ref={ref} aria-live={active ? "polite" : undefined}>
          {entries.map((p, i) => (
            <li key={i}>
              <time dateTime={p.at}>{parseDate(p.at)?.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) ?? ""}</time>
              <span>{p.msg}</span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

function PlannedTasks({ tasks }: { tasks: PlannedTask[] }) {
  return (
    <ul className="rows">
      {tasks.map((t) => (
        <li key={t.key}>
          <div className="row-between">
            <span className="row-title">
              <span className="mono">{t.key}</span> <span className="muted">by</span> {t.agent.toUpperCase().length <= 3 ? t.agent.toUpperCase() : humanize(t.agent)}
            </span>
            <span className="small muted">{t.complexity} complexity</span>
          </div>
          <div className="small ink-2 mt-8">{t.objective}</div>
          {t.depends_on.length > 0 && <div className="row-meta">After {t.depends_on.join(", ")}</div>}
        </li>
      ))}
    </ul>
  );
}

function ApprovalPanel({ approvalId, onDone }: { approvalId: string; onDone: () => void }) {
  const { data, error } = useApi<Approval[]>("/api/approvals");
  const appr = data?.find((a) => a.id === approvalId) ?? null;
  return (
    <Card title="Your decision" sub={appr ? appr.action : undefined} className="tone-edge" >
      {error ? (
        <ErrorBox error={error} />
      ) : !data ? (
        <Loading what="Checking approval" />
      ) : appr && appr.status !== "PENDING" ? (
        <p>
          <Badge value={appr.status} kind="approval" /> <span className="ink-2">by {appr.approver ?? "founder"} on {dateTime(appr.decided_at)}.</span>
        </p>
      ) : (
        <div className="stack-sm">
          {appr && (
            <KV
              items={[
                ["Reason", appr.reason],
                ["Expected effect", appr.expected_effect],
                ["Estimated cost", appr.cost_usd !== null ? `${usd(appr.cost_usd, { precise: false })} (estimate)` : null],
                ["Risks", appr.risks && appr.risks.length ? <Bullets items={appr.risks} /> : null],
              ]}
            />
          )}
          <ApprovalActions approvalId={approvalId} onDone={onDone} />
        </div>
      )}
    </Card>
  );
}

function isRiskAudit(v: unknown): v is RiskAudit {
  return !!v && typeof v === "object" && "verdict" in v && "summary" in v;
}

function ResultSections({ res, run }: { res: RunResult; run: RunDetail }) {
  const planOut = res.plan && !Array.isArray(res.plan) && typeof res.plan === "object" && "project" in (res.plan as object) ? (res.plan as { project: { name: string; objective: string; expected_cost_usd: number; estimated_effort_hours: number }; milestones: { key: string; title: string; due_in_days: number }[]; tasks: { key: string }[] }) : null;
  const plannedList = Array.isArray(res.plan) ? (res.plan as PlannedTask[]) : null;
  const prio = res.priorities && !("error" in res.priorities) ? (res.priorities as PrioritiesOutput) : null;

  return (
    <>
      {res.error && (
        <Callout tone="red" title={`Error: ${res.error.code}`}>
          {res.error.message}
        </Callout>
      )}

      {res.stopped === "budget" && (
        <Callout tone="orange" title="Stopped at the budget limit">
          Completed work is kept. {res.remaining && res.remaining.length > 0 ? `Not finished: ${res.remaining.join(", ")}.` : ""} Raise budget.workflow_limit_usd in Settings or rerun with a narrower request.
        </Callout>
      )}

      {res.draft && <DraftView draft={res.draft} />}

      {res.test && <TestView test={res.test} />}

      {res.trends && <TrendsView report={res.trends} />}

      {res.brief && (
        <Card title="Executive brief" sub="Synthesized by the CEO after an independent risk audit.">
          <BriefView brief={res.brief} />
        </Card>
      )}

      {(res.unit_economics || res.risk_audit) && (
        <div className="grid">
          {res.unit_economics && (
            <div className={res.risk_audit ? "span-5" : "span-12"}>
              <Card title="Unit economics" sub="Computed from CFO assumptions — estimates.">
                <UnitEconomicsView ue={res.unit_economics} />
              </Card>
            </div>
          )}
          {res.risk_audit && (
            <div className={res.unit_economics ? "span-7" : "span-12"}>
              <Card title="Independent risk audit">
                <RiskAuditView audit={res.risk_audit} />
              </Card>
            </div>
          )}
        </div>
      )}

      {res.founder_alignment && (
        <Card title="Digital twin: fit with your preferences">
          <TwinView twin={res.founder_alignment} />
        </Card>
      )}

      {res.agents && Object.keys(res.agents).length > 0 && (
        <Card title="Specialist findings" flush>
          <Table
            rows={Object.entries(res.agents)}
            rowKey={([k]) => k}
            columns={[
              { key: "task", header: "Task", render: ([k]) => <span className="mono small">{k}</span> },
              { key: "agent", header: "Agent", render: ([, a]) => <a href={href("agents", a.agent)}>{a.agent.length <= 3 ? a.agent.toUpperCase() : humanize(a.agent)}</a> },
              { key: "stance", header: "Stance", render: ([, a]) => (a.ok ? (a.stance ? sentence(a.stance) : "—") : <Badge value="FAILED" />) },
              {
                key: "summary",
                header: "Summary",
                className: "cell-wide",
                render: ([, a]) => (a.ok ? <span className="small ink-2">{a.summary ?? "—"}</span> : <span style={{ color: "var(--red)" }}>{a.error}</span>),
              },
            ]}
          />
        </Card>
      )}

      {res.disagreements && res.disagreements.length > 0 && !res.brief?.disagreements.length && (
        <Card title="Disagreements detected">
          {res.disagreements.map((d, i) => (
            <Callout key={i} tone="orange" title={d.topic}>
              {d.support && d.support.length > 0 && <p>Support: {d.support.map((s) => `${s.task} (${s.conclusion})`).join("; ")}</p>}
              {d.oppose && d.oppose.length > 0 && <p>Oppose: {d.oppose.map((s) => `${s.task} (${s.conclusion})`).join("; ")}</p>}
            </Callout>
          ))}
        </Card>
      )}

      {res.research && (
        <Card title="Research">
          <ResearchOutputView r={res.research} />
        </Card>
      )}

      {res.cto && (
        <Card title="CTO review">
          <FindingView f={res.cto as AgentFindingLike} />
        </Card>
      )}

      {res.created && (
        <Card title="Plan created" className="tone-edge">
          <div className="stack-sm">
            <div className="row">
              <Badge value={res.created.status} />
              <a href={href("projects", res.created.project_id)}>Open project</a>
              <span className="small muted">
                {res.created.task_ids.length} tasks, {res.created.milestone_ids.length} milestones
              </span>
            </div>
            {planOut && (
              <KV
                items={[
                  ["Project", planOut.project.name],
                  ["Objective", planOut.project.objective],
                  ["Expected cost", `${usd(planOut.project.expected_cost_usd, { precise: false })} (estimate)`],
                  ["Effort", `${planOut.project.estimated_effort_hours} hours (estimate)`],
                  ["Milestones", <Bullets key="m" items={planOut.milestones.map((m) => `${m.title} (in ${m.due_in_days} days)`)} />],
                ]}
              />
            )}
            {res.created.contradictions.map((c, i) => (
              <Callout key={i} tone="orange" title="Contradiction">
                {c}
              </Callout>
            ))}
            {res.created.warnings.map((w, i) => (
              <Callout key={i} tone="amber">
                {w}
              </Callout>
            ))}
          </div>
        </Card>
      )}

      {plannedList && !run.plan && (
        <Card title="Work plan">
          <PlannedTasks tasks={plannedList} />
        </Card>
      )}

      {prio && (
        <Card title="Priorities" sub={prio.summary}>
          <div className="grid">
            <div className="span-6">
              <h3 className="subhead">Do next</h3>
              {prio.do_next.length === 0 ? (
                <p className="muted small">Nothing ranked.</p>
              ) : (
                <ol className="bullets">
                  {prio.do_next.map((r) => (
                    <li key={r.item_id + r.title}>
                      <b>{r.title}</b> <Badge value={r.expected_value} kind="confidence" label={`${sentence(r.expected_value)} value`} />
                      <div className="small ink-2">{r.why}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
            <div className="span-6 stack-sm">
              {prio.kill_or_pause.length > 0 && (
                <>
                  <h3 className="subhead">Kill or pause</h3>
                  <Bullets items={prio.kill_or_pause.map((r) => `${r.title}: ${r.why}`)} />
                </>
              )}
              {prio.blocked.length > 0 && (
                <>
                  <h3 className="subhead">Blocked</h3>
                  <Bullets items={prio.blocked} />
                </>
              )}
              {prio.decisions_waiting_on_founder.length > 0 && (
                <>
                  <h3 className="subhead">Waiting on you</h3>
                  <Bullets items={prio.decisions_waiting_on_founder} />
                </>
              )}
              {prio.contradictions.map((c, i) => (
                <Callout key={i} tone="orange" title="Contradiction">
                  {c}
                </Callout>
              ))}
            </div>
          </div>
        </Card>
      )}
      {res.priorities && "error" in res.priorities && <Callout tone="red" title="Priorities failed">{String(res.priorities.error)}</Callout>}

      {res.financials && (
        <Card title="Financials" actions={<a href={href("finance")}>Finance page</a>}>
          {res.financials.has_data ? (
            <div className="stack-sm">
              <FinanceSnapshot totals={res.financials.totals} burn={res.financials.burn} cash={res.financials.cash} runway={res.financials.runway} />
              {res.reconciliation && (
                <p className="small">
                  Reconciliation: {res.reconciliation.ok ? <Badge tone="green" label="All checks pass" /> : <Badge tone="red" label="Mismatch found" />}
                </p>
              )}
            </div>
          ) : (
            <EmptyState title="No financial records" action={<a className="btn btn-sm" href={href("finance")}>Import a CSV</a>}>
              {res.financials.note ?? "No transactions yet."}
            </EmptyState>
          )}
        </Card>
      )}

      {res.cfo && (
        <Card title="CFO commentary">
          <FindingView f={res.cfo} />
        </Card>
      )}

      {res.findings && Object.keys(res.findings).length > 0 && (
        <Card title="Audit findings" actions={res.audit_id ? <a href={href("audits")}>Audits</a> : undefined}>
          <div className="grid">
            {Object.entries(res.findings).map(([k, items]) => (
              <div key={k} className="span-4">
                <h3 className="subhead">{humanize(k)}</h3>
                <Bullets items={items ?? []} empty="No findings, or this reviewer failed." />
              </div>
            ))}
          </div>
        </Card>
      )}

      {res.risk_review && (
        <Card title="Risk review of the proposals">
          {isRiskAudit(res.risk_review) ? <RiskAuditView audit={res.risk_review} /> : <Callout tone="red">{String((res.risk_review as { error: string }).error)}</Callout>}
        </Card>
      )}

      {res.improvements && (
        <div className="stack">
          <h2 className="panel-title">Improvements proposed</h2>
          {res.improvements.length === 0 ? (
            <EmptyState title="No improvements proposed">The auditors found nothing the measurements support changing.</EmptyState>
          ) : (
            res.improvements.map((i) => <ImprovementCard key={i.id} imp={i} />)
          )}
        </div>
      )}

      {res.measured_candidates && res.measured_candidates.length > 0 && (
        <div className="stack">
          <h2 className="panel-title">Measured candidates</h2>
          {res.measured_candidates.map((i) => (
            <ImprovementCard key={i.id} imp={i} />
          ))}
        </div>
      )}

      {res.alignment && (
        <Card title="What the twin learned from your decision">
          <TwinView twin={res.alignment} />
          <p className="small muted mt-8">
            {res.memories_created?.length ?? 0} new inferred memories, {res.memories_promoted?.length ?? 0} promoted to confirmed. <a href={href("memory")}>Review memory</a>
          </p>
        </Card>
      )}
    </>
  );
}
