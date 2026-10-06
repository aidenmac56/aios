import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Bullets, Callout, Card, KV, PageHead, Progress } from "../components/Card";
import { EmptyState, ErrorBox, Gate } from "../components/EmptyState";
import { Table } from "../components/Table";
import { dateOnly, humanize, usd } from "../format";
import { useAction, useApi } from "../hooks";
import { href, navigate } from "../router";
import type { PlanningState, ProjectDetail, TaskRow } from "../types";

export function ProjectsPage({ id }: { id: string | null }) {
  return id ? <ProjectDetailPage id={id} /> : <ProjectList />;
}

function ProjectList() {
  const { data, error, reload } = useApi<PlanningState>("/api/projects");
  return (
    <>
      <PageHead title="Projects" sub="Plans built from approved decisions: projects, milestones and tasks with completion criteria." />
      <Gate data={data} error={error} retry={reload} what="Loading projects">
        {(st) => (
          <div className="stack">
            {st.contradictions.map((c, i) => (
              <Callout key={i} tone="orange" title="Contradiction">
                {c}
              </Callout>
            ))}
            <Card flush>
              <Table
                rows={st.projects}
                rowKey={(p) => p.id}
                onRowClick={(p) => navigate("projects", p.id)}
                empty={<EmptyState title="No projects yet">Approve a build decision, or run plan with a goal, to create the first project.</EmptyState>}
                columns={[
                  { key: "n", header: "Project", className: "cell-mid", render: (p) => <span className="row-title">{p.name}</span> },
                  { key: "s", header: "Status", render: (p) => <Badge value={p.status} /> },
                  { key: "p", header: "Priority", num: true, render: (p) => p.priority },
                  {
                    key: "prog",
                    header: "Progress",
                    render: (p) => (
                      <div style={{ minWidth: 140 }}>
                        <Progress pct={p.progress_pct} label={`${p.name} progress`} />
                        <div className="small muted mt-8 tnum">
                          {p.tasks_done}/{p.tasks_total} tasks{p.blocked_tasks ? `, ${p.blocked_tasks} blocked` : ""}
                        </div>
                      </div>
                    ),
                  },
                  { key: "c", header: "Expected cost", num: true, render: (p) => p.expected_cost },
                ]}
              />
            </Card>
            <div className="grid">
              <div className="span-7">
                <Card title="Top tasks" sub="Ranked across all projects." flush>
                  <Table
                    dense
                    rows={st.top_tasks}
                    rowKey={(t) => t.task_id}
                    empty={<EmptyState title="No open tasks">Tasks appear when a plan is created.</EmptyState>}
                    columns={[
                      { key: "t", header: "Task", className: "cell-mid", render: (t) => t.title },
                      { key: "p", header: "Project", render: (t) => <span className="small ink-2">{t.project ?? "—"}</span> },
                      { key: "s", header: "Status", render: (t) => <Badge value={t.status} /> },
                      { key: "o", header: "Owner", render: (t) => t.owner ?? "—" },
                      { key: "sc", header: "Score", num: true, render: (t) => t.score },
                    ]}
                  />
                </Card>
              </div>
              <div className="span-5 stack">
                <Card title="Waiting on you" actions={<a href={href("decisions")}>Decisions</a>}>
                  {st.pending_approvals.length === 0 && st.decisions_waiting.length === 0 ? (
                    <p className="muted small">No approvals or decisions are waiting.</p>
                  ) : (
                    <ul className="rows">
                      {st.pending_approvals.map((a) => (
                        <li key={a.id}>
                          <div>{a.action}</div>
                          <div className="row-meta">
                            <Badge tone="amber" label={humanize(a.type.toLowerCase())} />
                          </div>
                        </li>
                      ))}
                      {st.decisions_waiting
                        .filter((d) => !st.pending_approvals.some((a) => a.action.includes(d.question)))
                        .map((d) => (
                          <li key={d.id}>
                            <div>{d.question}</div>
                            <div className="row-meta">
                              <Badge value="PENDING_APPROVAL" />
                            </div>
                          </li>
                        ))}
                    </ul>
                  )}
                </Card>
              </div>
            </div>
          </div>
        )}
      </Gate>
    </>
  );
}

const STATUS_ACTIONS = ["READY", "RUNNING", "BLOCKED", "COMPLETED", "CANCELLED"] as const;

function ProjectDetailPage({ id }: { id: string }) {
  const { data, error, reload } = useApi<ProjectDetail>(`/api/projects/${encodeURIComponent(id)}`);
  return (
    <Gate data={data} error={error} retry={reload} what="Loading project">
      {(p) => <Project p={p} reload={reload} />}
    </Gate>
  );
}

function Project({ p, reload }: { p: ProjectDetail; reload: () => void }) {
  const titleOf = new Map(p.tasks.map((t) => [t.id, t.title]));
  const depsOf = new Map<string, string[]>();
  for (const d of p.dependencies) depsOf.set(d.task_id, [...(depsOf.get(d.task_id) ?? []), d.depends_on_id]);
  const done = p.tasks.filter((t) => t.status === "COMPLETED").length;
  const unassigned = p.tasks.filter((t) => !t.milestone_id || !p.milestones.some((m) => m.id === t.milestone_id));

  return (
    <>
      <PageHead
        crumb={<a href={href("projects")}>Projects</a>}
        title={p.name}
        sub={p.objective ?? undefined}
        actions={
          <>
            <Badge value={p.status} size="lg" />
            <Badge tone="gray" label={`Priority ${p.priority}`} />
          </>
        }
      />
      <div className="stack">
        {p.status === "PROPOSED" && (
          <Callout tone="amber" title="Waiting for your approval">
            This plan conflicts with a principle or budget. Its tasks stay on hold until you approve it on the <a href={href("decisions")}>Decisions page</a>.
          </Callout>
        )}
        <div className="grid">
          <div className="span-7">
            <Card title="Overview">
              <div className="stack-sm">
                <div className="row" style={{ flexWrap: "nowrap" }}>
                  <div style={{ flex: 1 }}>
                    <Progress pct={p.tasks.length ? (done / p.tasks.length) * 100 : 0} label="Project progress" />
                  </div>
                  <span className="small tnum nowrap">
                    {done}/{p.tasks.length} tasks done
                  </span>
                </div>
                <KV
                  items={[
                    ["Why", p.reason],
                    ["Expected impact", p.expected_impact],
                    ["Expected cost", `${usd(p.expected_cost_usd, { precise: false })} (estimate)`],
                    ["Effort", p.estimated_effort_hours !== null ? `${p.estimated_effort_hours} hours (estimate)` : null],
                    ["Success criteria", p.success_criteria && p.success_criteria.length ? <Bullets items={p.success_criteria} /> : null],
                    ["Decision", p.decision_id ? <a href={href("decisions")} className="mono small">{p.decision_id.slice(0, 8)}</a> : null],
                  ]}
                />
              </div>
            </Card>
          </div>
          <div className="span-5 stack">
            <Card title="Risks">
              <Bullets items={p.risks ?? []} empty="No risks recorded." />
            </Card>
            {p.blockers && p.blockers.length > 0 && (
              <Card title="Blockers">
                <Bullets items={p.blockers.map((b) => (typeof b === "string" ? b : JSON.stringify(b)))} />
              </Card>
            )}
          </div>
        </div>

        {p.milestones.length === 0 && p.tasks.length === 0 && <EmptyState title="This project has no milestones or tasks">Run plan again for this goal to create them.</EmptyState>}

        {p.milestones.map((m) => {
          const tasks = p.tasks.filter((t) => t.milestone_id === m.id);
          return (
            <Card
              key={m.id}
              title={m.title}
              sub={
                <span className="row" style={{ gap: 10 }}>
                  {m.due_date && <span>Due {dateOnly(m.due_date)}</span>}
                  {m.success_criteria && <span>Done when: {m.success_criteria}</span>}
                </span>
              }
              actions={<Badge value={m.status} />}
              flush
            >
              {tasks.length === 0 ? (
                <EmptyState title="No tasks in this milestone" />
              ) : (
                tasks.map((t) => <TaskLine key={t.id} t={t} deps={(depsOf.get(t.id) ?? []).map((d) => titleOf.get(d) ?? d)} onChanged={reload} />)
              )}
            </Card>
          );
        })}
        {unassigned.length > 0 && (
          <Card title="Other tasks" flush>
            {unassigned.map((t) => (
              <TaskLine key={t.id} t={t} deps={(depsOf.get(t.id) ?? []).map((d) => titleOf.get(d) ?? d)} onChanged={reload} />
            ))}
          </Card>
        )}
      </div>
    </>
  );
}

function TaskLine({ t, deps, onChanged }: { t: TaskRow; deps: string[]; onChanged: () => void }) {
  const { busy, error, run } = useAction();
  const [row, setRow] = useState<TaskRow>(t);
  // A change to another task can change this one (dependents become READY), so follow reloaded props.
  useEffect(() => setRow(t), [t]);

  async function patch(body: { status?: string; criteria_met?: boolean }) {
    const r = await run(() => api.patch<TaskRow>(`/api/tasks/${encodeURIComponent(t.id)}`, body));
    if (r) {
      setRow(r);
      onChanged();
    }
  }

  const closed = row.status === "COMPLETED" || row.status === "CANCELLED";
  return (
    <div className="task-line">
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <div className={row.status === "CANCELLED" ? "row-title strike" : "row-title"}>{row.title}</div>
          {row.description && <div className="small ink-2">{row.description}</div>}
        </div>
        <Badge value={row.status} />
      </div>
      <div className="row-meta" style={{ marginTop: 0 }}>
        <span>Owner {row.owner === "founder" ? "you" : row.owner ?? "unassigned"}</span>
        <span>Priority {row.priority}</span>
        {row.due_date && <span>Due {dateOnly(row.due_date)}</span>}
        {row.estimated_effort_hours !== null && <span>{row.estimated_effort_hours} h est.</span>}
        {row.estimated_cost_usd > 0 && <span>{usd(row.estimated_cost_usd, { precise: false })} est.</span>}
        {deps.map((d) => (
          <span key={d}>After: {d}</span>
        ))}
      </div>
      <div className="small">
        <span className="muted">Done when: </span>
        {row.completion_criteria ?? "—"}{" "}
        {row.criteria_met ? <Badge tone="green" label="Criteria met" /> : <Badge tone="gray" label="Not yet met" />}
      </div>
      {!closed && (
        <div className="row">
          {!row.criteria_met && (
            <button className="btn btn-sm" disabled={busy} onClick={() => patch({ criteria_met: true })}>
              Mark criteria met
            </button>
          )}
          <label className="row small" style={{ gap: 6 }}>
            <span className="muted">Set status</span>
            <select
              className="select"
              style={{ width: "auto", padding: "3px 6px", fontSize: 12.5 }}
              value=""
              disabled={busy}
              onChange={(e) => e.target.value && patch({ status: e.target.value })}
            >
              <option value="">Choose…</option>
              {STATUS_ACTIONS.filter((s) => s !== row.status).map((s) => (
                <option key={s} value={s}>
                  {humanize(s.toLowerCase())}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
      <ErrorBox error={error} />
    </div>
  );
}
