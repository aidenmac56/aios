import { useState } from "react";
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Bullets, Card, Chips, KV, PageHead } from "../components/Card";
import { EmptyState, ErrorBox, Gate } from "../components/EmptyState";
import { Table } from "../components/Table";
import { dateTime, duration, relative, usd } from "../format";
import { useAction, useApi } from "../hooks";
import { href, navigate } from "../router";
import type { AgentDetail, AgentView } from "../types";

const TIER_TONE: Record<string, "green" | "blue" | "accent"> = { FAST: "green", BALANCED: "blue", DEEP: "accent" };

export function AgentsPage({ id }: { id: string | null }) {
  return id ? <AgentDetailPage id={id} /> : <AgentList />;
}

function AgentList() {
  const { data, error, reload } = useApi<AgentView[]>("/api/agents");
  return (
    <>
      <PageHead title="Agents" sub="The organization. Each agent has a job, limits, and measurable performance." />
      <Gate data={data} error={error} retry={reload} what="Loading agents">
        {(agents) =>
          agents.length === 0 ? (
            <EmptyState title="No agents registered">Start the server once; agents are synced from code on startup.</EmptyState>
          ) : (
            <div className="agent-cards">
              {agents.map((a) => (
                <a key={a.id} className="panel agent-card" href={href("agents", a.id)}>
                  <div className="row-between" style={{ alignItems: "flex-start" }}>
                    <div>
                      <h3>{a.title}</h3>
                      <div className="small muted mono">{a.id}</div>
                    </div>
                    <div className="row" style={{ gap: 6 }}>
                      {!a.enabled && <Badge tone="gray" label="Disabled" />}
                      <Badge tone={TIER_TONE[a.default_tier] ?? "gray"} label={a.default_tier} title="Default model tier" />
                    </div>
                  </div>
                  <p className="small ink-2">{a.purpose}</p>
                  <div className="agent-figs">
                    <span>
                      <b>{a.runs}</b>runs
                    </span>
                    <span>
                      <b style={a.failed ? { color: "var(--red)" } : undefined}>{a.failed}</b>failed
                    </span>
                    <span>
                      <b>{usd(a.total_cost_usd)}</b>cost
                    </span>
                    <span>
                      <b>{a.runs ? `${a.avg_duration_s}s` : "—"}</b>avg time
                    </span>
                  </div>
                  <Chips items={a.permissions} mono />
                  <div className="row-meta" style={{ marginTop: 0 }}>
                    <span>Config v{a.config_version}</span>
                    <span>{a.last_run ? `Last run ${relative(a.last_run.at)}` : "Never run"}</span>
                    {a.last_run && <Badge value={a.last_run.status} />}
                  </div>
                </a>
              ))}
            </div>
          )
        }
      </Gate>
    </>
  );
}

function AgentDetailPage({ id }: { id: string }) {
  const { data, error, reload } = useApi<AgentDetail>(`/api/agents/${encodeURIComponent(id)}`);
  return (
    <Gate data={data} error={error} retry={reload} what="Loading agent">
      {(a) => (
        <>
          <PageHead
            crumb={<a href={href("agents")}>Agents</a>}
            title={a.title}
            sub={a.purpose}
            actions={
              <>
                <Badge tone={TIER_TONE[a.default_tier] ?? "gray"} label={`Default tier ${a.default_tier}`} />
                <Badge tone="gray" label={`Config v${a.config_version}`} />
              </>
            }
          />
          <div className="stack">
            <div className="stats">
              <div className="stat">
                <div className="stat-label">Runs</div>
                <div className="stat-value">{a.runs}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Failed</div>
                <div className="stat-value" style={a.failed ? { color: "var(--red)" } : undefined}>
                  {a.failed}
                </div>
                <div className="stat-note">{a.runs ? `${Math.round((a.failed / a.runs) * 100)}% failure rate` : "No runs yet"}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Total cost</div>
                <div className="stat-value">{usd(a.total_cost_usd)}</div>
                <div className="stat-note">Estimated from list prices</div>
              </div>
              <div className="stat">
                <div className="stat-label">Average duration</div>
                <div className="stat-value">{a.runs ? `${a.avg_duration_s} s` : "—"}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Last run</div>
                <div className="stat-value" style={{ fontSize: 15 }}>
                  {a.last_run ? relative(a.last_run.at) : "Never"}
                </div>
                {a.last_run && <div className="stat-note mono">{a.last_run.model}</div>}
              </div>
            </div>

            <div className="grid">
              <div className="span-7 stack">
                <Card title="Role">
                  <KV
                    items={[
                      ["Authority", a.authority],
                      ["Responsibilities", <Bullets key="r" items={a.responsibilities} />],
                      ["Inputs", a.inputs],
                      ["Outputs", a.outputs],
                      ["Escalates when", <Bullets key="e" items={a.escalation_rules} empty="No escalation rules." />],
                      ["Measured by", <Bullets key="p" items={a.performance_measures} />],
                    ]}
                  />
                </Card>
              </div>
              <div className="span-5 stack">
                <Card title="Permissions" sub="Declared in code. No agent can spend money, publish, or change system configuration.">
                  <Chips items={a.permissions} mono />
                  <h3 className="subhead mt-12">Tools</h3>
                  <Chips items={a.tools} mono />
                </Card>
                <Card title="Configuration versions" flush>
                  <Table
                    dense
                    rows={a.versions}
                    rowKey={(v) => String(v.version)}
                    empty={<EmptyState title="No versions stored">The first version is written when the server syncs agents.</EmptyState>}
                    columns={[
                      { key: "v", header: "Version", render: (v) => <span className="nowrap">v{v.version}{v.version === a.config_version && <span className="muted small"> active</span>}</span> },
                      { key: "why", header: "Reason", render: (v) => <span className="small ink-2">{v.reason ?? "—"}{v.rollback_to ? ` (rollback to v${v.rollback_to})` : ""}</span> },
                      { key: "by", header: "By", render: (v) => <span className="small">{v.created_by ?? "—"}</span> },
                      { key: "at", header: "Date", render: (v) => <span className="small nowrap">{dateTime(v.created_at)}</span> },
                      { key: "chars", header: "Prompt", num: true, render: (v) => `${v.prompt_chars.toLocaleString()} ch` },
                    ]}
                  />
                  {a.versions.length > 1 && (
                    <div style={{ padding: "12px 16px" }}>
                      <ActivateVersion agentId={a.id} versions={a.versions.map((v) => v.version)} active={a.config_version} onDone={reload} />
                    </div>
                  )}
                </Card>
              </div>
            </div>

            <Card title="System prompt">
              {a.system_prompt ? (
                <details className="disclose">
                  <summary>Show the prompt this agent runs with</summary>
                  <pre className="codeblock">{a.system_prompt}</pre>
                </details>
              ) : (
                <p className="muted small">No stored prompt version.</p>
              )}
            </Card>

            <Card title="Recent runs" flush>
              <Table
                rows={a.recent_runs}
                rowKey={(r) => r.id}
                onRowClick={(r) => r.workflow_run_id && navigate("runs", r.workflow_run_id)}
                empty={<EmptyState title="This agent has not run yet">It runs when a command needs it, for example ceo or board.</EmptyState>}
                columns={[
                  { key: "st", header: "Status", render: (r) => <Badge value={r.status} /> },
                  { key: "obj", header: "Objective", className: "cell-wide", render: (r) => <span className="small ink-2">{r.objective ? (r.objective.length > 160 ? r.objective.slice(0, 160) + "…" : r.objective) : "—"}</span> },
                  { key: "model", header: "Model", render: (r) => <span className="mono small nowrap">{r.model ?? "—"}</span> },
                  { key: "tier", header: "Tier", render: (r) => r.tier ?? "—" },
                  { key: "cost", header: "Cost", num: true, render: (r) => usd(r.cost_usd) },
                  { key: "dur", header: "Duration", num: true, render: (r) => duration(r.duration_ms) },
                  { key: "retries", header: "Retries", num: true, render: (r) => r.retries ?? 0 },
                  { key: "at", header: "Started", render: (r) => <span className="small nowrap">{dateTime(r.started_at)}</span> },
                ]}
              />
            </Card>
          </div>
        </>
      )}
    </Gate>
  );
}

/** Founder-only: switch the live prompt version (e.g. to roll back by hand). Logged in the audit trail. */
function ActivateVersion({ agentId, versions, active, onDone }: { agentId: string; versions: number[]; active: number; onDone: () => void }) {
  const others = versions.filter((v) => v !== active);
  const [version, setVersion] = useState<number>(others[0]);
  const [why, setWhy] = useState("");
  const { busy, error, run } = useAction();
  if (others.length === 0) return null;

  async function activate(e: React.FormEvent) {
    e.preventDefault();
    const r = await run(() => api.post(`/api/agents/${encodeURIComponent(agentId)}/activate`, { version, why: why.trim() }));
    if (r) {
      setWhy("");
      onDone();
    }
  }

  return (
    <form className="inline-form" onSubmit={activate}>
      <div className="row" style={{ gap: 8, alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="field">
          <span className="label">Switch live version to</span>
          <select className="input" value={version} onChange={(e) => setVersion(Number(e.target.value))}>
            {others.map((v) => (
              <option key={v} value={v}>
                v{v}
              </option>
            ))}
          </select>
        </label>
        <label className="field" style={{ flex: 1, minWidth: 180 }}>
          <span className="label">Why</span>
          <input className="input" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. v3 made research answers worse" />
        </label>
        <button className="btn" type="submit" disabled={busy || why.trim().length < 3}>
          Activate
        </button>
      </div>
      <ErrorBox error={error} />
    </form>
  );
}
