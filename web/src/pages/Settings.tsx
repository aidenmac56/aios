import { useState } from "react";
import { api } from "../api";
import { Badge } from "../components/Badge";
import { Callout, Card, PageHead } from "../components/Card";
import { EmptyState, ErrorBox, Gate } from "../components/EmptyState";
import { Table } from "../components/Table";
import { dateTime } from "../format";
import { useAction, useApi } from "../hooks";
import type { ConfigEntry, MetricDef, SettingsView } from "../types";

export function SettingsPage() {
  const settings = useApi<SettingsView>("/api/settings");
  const metrics = useApi<MetricDef[]>("/api/metrics");
  return (
    <>
      <PageHead title="Settings" sub="Server status, configuration, and the metric registry. Every change is written to the audit log." />
      <div className="stack">
        <Gate data={settings.data} error={settings.error} retry={settings.reload} what="Loading settings">
          {(s) => (
            <>
              <ServerStatus s={s} />
              <ConfigList config={s.config} onSaved={settings.reload} />
            </>
          )}
        </Gate>
        <Card title="Metric registry" sub="One definition per metric; every number on the Finance page is computed through these." flush>
          <Gate data={metrics.data} error={metrics.error} retry={metrics.reload} what="Loading metrics">
            {(rows) => (
              <Table
                dense
                rows={rows}
                rowKey={(m) => m.key}
                empty={<EmptyState title="No metrics registered">They are synced from code when the server starts.</EmptyState>}
                columns={[
                  { key: "k", header: "Key", render: (m) => <span className="mono small nowrap">{m.key}</span> },
                  { key: "n", header: "Name", render: (m) => m.name },
                  { key: "f", header: "Formula", className: "cell-wide", render: (m) => <span className="mono small ink-2">{m.formula}</span> },
                  { key: "u", header: "Unit", render: (m) => <span className="small">{m.unit}</span> },
                  { key: "d", header: "Description", className: "cell-mid", render: (m) => <span className="small ink-2">{m.description}</span> },
                ]}
              />
            )}
          </Gate>
        </Card>
      </div>
    </>
  );
}

function ServerStatus({ s }: { s: SettingsView }) {
  return (
    <Card title="Server">
      <div className="stack-sm">
        <div className="stats">
          <div className="stat">
            <div className="stat-label">Model credentials</div>
            <div className="stat-value" style={{ fontSize: 15 }}>
              {s.llm_credentials ? <Badge tone="green" label="Present" /> : <Badge tone="red" label="Missing" />}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Web search</div>
            <div className="stat-value" style={{ fontSize: 15 }}>
              {s.web_search ? <Badge tone="green" label="Enabled" /> : <Badge tone="gray" label="Disabled" />}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">Database</div>
            <div className="stat-value mono" style={{ fontSize: 15 }}>
              {s.database}
            </div>
          </div>
          <div className="stat">
            <div className="stat-label">API token</div>
            <div className="stat-value" style={{ fontSize: 15 }}>
              {s.api_token_required ? <Badge tone="green" label="Required" /> : <Badge tone="amber" label="Not required" />}
            </div>
          </div>
        </div>
        {!s.llm_credentials && (
          <Callout tone="amber" title="Agents cannot run">
            Add <code>ANTHROPIC_API_KEY=...</code> to the <code>.env</code> file in the project root and restart <code>aios serve</code>. Finance, memory, projects and settings work without it.
          </Callout>
        )}
        {!s.web_search && (
          <Callout tone="gray" title="Research runs without live search">
            Research confidence is capped at low until web search is enabled on the server.
          </Callout>
        )}
        {!s.api_token_required && (
          <p className="small muted">Anyone who can reach this server can use it. Set AIOS_API_TOKEN in .env to require a token.</p>
        )}
      </div>
    </Card>
  );
}

function ConfigList({ config, onSaved }: { config: Record<string, ConfigEntry>; onSaved: () => void }) {
  const entries = Object.entries(config).sort(([a], [b]) => a.localeCompare(b));
  const groups = new Map<string, [string, ConfigEntry][]>();
  for (const e of entries) {
    const g = e[0].split(".")[0];
    groups.set(g, [...(groups.get(g) ?? []), e]);
  }
  return (
    <>
      {[...groups.entries()].map(([g, items]) => (
        <Card key={g} title={`${g.charAt(0).toUpperCase()}${g.slice(1)}`} flush>
          {items.map(([k, v]) => (
            <ConfigItem key={k} k={k} entry={v} onSaved={onSaved} />
          ))}
        </Card>
      ))}
    </>
  );
}

function ConfigItem({ k, entry, onSaved }: { k: string; entry: ConfigEntry; onSaved: () => void }) {
  const pretty = JSON.stringify(entry.value, null, 2);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(pretty);
  const [why, setWhy] = useState("");
  const [saved, setSaved] = useState(false);
  const { busy, error, run, setError } = useAction();
  const long = pretty.length > 80 || pretty.includes("\n");

  async function save(e: React.FormEvent) {
    e.preventDefault();
    let value: unknown;
    try {
      value = JSON.parse(text);
    } catch (err) {
      setError(new Error(`Not valid JSON: ${(err as Error).message}`));
      return;
    }
    if (!why.trim()) {
      setError(new Error("Say why you are changing this; it is recorded in the audit log."));
      return;
    }
    const r = await run(() => api.put<{ key: string; value: unknown }>(`/api/settings/${encodeURIComponent(k)}`, { value, why: why.trim() }));
    if (r) {
      setEditing(false);
      setSaved(true);
      setWhy("");
      onSaved();
    }
  }

  return (
    <div className="mem-item">
      <div className="row-between" style={{ alignItems: "flex-start" }}>
        <div style={{ minWidth: 0 }}>
          <div className="mono" style={{ fontWeight: 600, fontSize: 13 }}>
            {k}
          </div>
          {entry.description && <div className="small ink-2">{entry.description}</div>}
        </div>
        <div className="row" style={{ gap: 6 }}>
          {entry.source === "database" ? <Badge tone="blue" label="Changed" /> : <Badge tone="gray" label="Default" />}
          {!editing && (
            <button
              className="btn btn-sm"
              onClick={() => {
                setText(pretty);
                setEditing(true);
                setSaved(false);
              }}
            >
              Edit
            </button>
          )}
        </div>
      </div>
      {!editing &&
        (long ? (
          <details className="disclose mt-8">
            <summary>Show value</summary>
            <pre className="codeblock">{pretty}</pre>
          </details>
        ) : (
          <div className="mt-8">
            <code className="chip mono">{pretty}</code>
          </div>
        ))}
      {entry.source === "database" && (entry.updated_by || entry.updated_at) && (
        <div className="row-meta">
          {entry.updated_by && <span>Changed by {entry.updated_by}</span>}
          {entry.updated_at && <span>{dateTime(entry.updated_at)}</span>}
        </div>
      )}
      {saved && !editing && <p className="small mt-8" style={{ color: "var(--green)" }}>Saved and recorded in the audit log.</p>}
      {editing && (
        <form className="inline-form" onSubmit={save}>
          <div className="field">
            <label htmlFor={`v-${k}`}>Value (JSON)</label>
            <textarea id={`v-${k}`} className="textarea code" rows={Math.min(16, Math.max(3, text.split("\n").length + 1))} value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          </div>
          <div className="field">
            <label htmlFor={`w-${k}`}>Why (required)</label>
            <input id={`w-${k}`} className="input" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="e.g. tighten spend while testing" />
          </div>
          <div className="row">
            <button className="btn btn-primary" type="submit" disabled={busy}>
              Save change
            </button>
            <button className="btn btn-ghost" type="button" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
          <ErrorBox error={error} />
        </form>
      )}
    </div>
  );
}
