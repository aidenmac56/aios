import { useState } from "react";
import { BarChart } from "../components/BarChart";
import { Card, Meter, PageHead, Stats } from "../components/Card";
import { EmptyState, Gate } from "../components/EmptyState";
import { Table } from "../components/Table";
import { dayLabel, num, usd } from "../format";
import { useApi } from "../hooks";
import type { CostRow, Costs } from "../types";

const WINDOWS = [7, 30, 90];

export function CostsPage() {
  const [days, setDays] = useState(30);
  const { data, error, reload } = useApi<Costs>(`/api/costs?days=${days}`);
  return (
    <>
      <PageHead
        title="AI costs"
        sub="What running the agents costs, by agent, model, workflow and purpose."
        actions={
          <div className="segmented" role="group" aria-label="Time window">
            {WINDOWS.map((d) => (
              <button key={d} aria-pressed={days === d} onClick={() => setDays(d)}>
                {d} days
              </button>
            ))}
          </div>
        }
      />
      <Gate data={data} error={error} retry={reload} what="Loading costs">
        {(c) => <CostsBody c={c} />}
      </Gate>
    </>
  );
}

function fillDays(rows: Costs["by_day"], windowDays: number): { day: string; cost: number }[] {
  const by = new Map(rows.map((r) => [r.day.slice(0, 10), r.cost_usd]));
  const out: { day: string; cost: number }[] = [];
  const today = new Date();
  const utc = Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate());
  for (let i = windowDays - 1; i >= 0; i--) {
    const d = new Date(utc - i * 86400000).toISOString().slice(0, 10);
    out.push({ day: d, cost: by.get(d) ?? 0 });
  }
  return out;
}

function CostsBody({ c }: { c: Costs }) {
  const days = fillDays(c.by_day, c.window_days);
  const runs = c.per_run_avg_usd.reduce((a, r) => a + r.runs, 0);
  // Draw the limit only when it is on the same scale as the data; otherwise the bars flatten to nothing.
  const showLimit = Math.max(0, ...days.map((d) => d.cost)) >= c.daily_limit_usd * 0.25;
  return (
    <div className="stack">
      <Stats
        items={[
          { label: `Total, last ${c.window_days} days`, value: usd(c.total_usd), note: `${num(c.calls)} model calls` },
          { label: "Today", value: usd(c.today_usd), note: `Daily limit ${usd(c.daily_limit_usd, { precise: false })}` },
          { label: "Failed calls", value: num(c.failed_calls), note: c.calls ? `${((c.failed_calls / c.calls) * 100).toFixed(1)}% of calls` : undefined },
          { label: "Retry cost", value: usd(c.retry_cost_usd), note: "Second and later attempts" },
          { label: "Web search", value: usd(c.web_search.cost_usd_included), note: `${num(c.web_search.calls)} searches, included in total` },
        ]}
      />
      <Card title="Today against the daily limit">
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <div style={{ flex: 1 }}>
            <Meter value={c.today_usd} max={c.daily_limit_usd} label="Today's AI spend against the daily limit" />
          </div>
          <span className="tnum small nowrap">
            {usd(c.today_usd)} of {usd(c.daily_limit_usd, { precise: false })}
          </span>
        </div>
        <p className="small muted mt-8">Runs stop when the limit is reached. Change budget.daily_limit_usd in Settings.</p>
      </Card>

      <Card
        title="Cost by day"
        sub={
          showLimit
            ? "UTC days. The dashed line is the daily limit."
            : `UTC days. The daily limit (${usd(c.daily_limit_usd, { precise: false })}) is far above these values, so it is not drawn.`
        }
      >
        {c.total_usd === 0 ? (
          <EmptyState title="No model usage in this window">Costs appear after the first command runs.</EmptyState>
        ) : (
          <BarChart
            label={`AI cost by day, last ${c.window_days} days`}
            categories={days.map((d) => dayLabel(d.day))}
            series={[{ name: "Cost", color: "var(--series-1)", values: days.map((d) => d.cost) }]}
            format={(n) => (n === 0 ? "$0" : n < 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(n < 10 ? 1 : 0)}`)}
            refLine={showLimit ? { value: c.daily_limit_usd, label: "Daily limit" } : null}
          />
        )}
      </Card>

      <div className="grid">
        <div className="span-6">
          <Breakdown title="By agent" rows={c.by_agent} />
        </div>
        <div className="span-6">
          <Breakdown title="By model" rows={c.by_model} mono />
        </div>
        <div className="span-6">
          <Breakdown title="By workflow" rows={c.by_workflow} mono />
        </div>
        <div className="span-6">
          <Breakdown title="By purpose" rows={c.by_purpose} />
        </div>
      </div>

      <Card title="Average cost per run" sub={runs ? `${runs} runs in this window` : undefined} flush>
        <Table
          dense
          rows={c.per_run_avg_usd}
          rowKey={(r) => r.command}
          empty={<EmptyState title="No runs in this window" />}
          columns={[
            { key: "c", header: "Command", render: (r) => <span className="mono">{r.command}</span> },
            { key: "n", header: "Runs", num: true, render: (r) => r.runs },
            { key: "a", header: "Average", num: true, render: (r) => usd(r.avg_usd) },
          ]}
        />
      </Card>

      <p className="small muted">{c.basis}</p>
    </div>
  );
}

function Breakdown({ title, rows, mono }: { title: string; rows: CostRow[]; mono?: boolean }) {
  const total = rows.reduce((a, r) => a + r.cost_usd, 0);
  return (
    <Card title={title} flush>
      <Table
        dense
        rows={rows}
        rowKey={(r) => r.key}
        empty={<EmptyState title="No usage in this window" />}
        columns={[
          { key: "k", header: "Name", render: (r) => <span className={mono ? "mono small" : undefined}>{r.key}</span> },
          { key: "calls", header: "Calls", num: true, render: (r) => num(r.calls) },
          { key: "tok", header: "Tokens in / out", num: true, render: (r) => `${compact(r.input_tokens)} / ${compact(r.output_tokens)}` },
          { key: "cost", header: "Cost", num: true, render: (r) => usd(r.cost_usd) },
          { key: "share", header: "Share", num: true, render: (r) => (total ? `${Math.round((r.cost_usd / total) * 100)}%` : "—") },
        ]}
      />
    </Card>
  );
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k`;
  return String(n);
}
