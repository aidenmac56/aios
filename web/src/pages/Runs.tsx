import { Badge } from "../components/Badge";
import { Card, PageHead } from "../components/Card";
import { EmptyState, Gate } from "../components/EmptyState";
import { Table } from "../components/Table";
import { dateTime, duration, parseDate, usd } from "../format";
import { useApi } from "../hooks";
import { navigate } from "../router";
import type { RunListRow } from "../types";

export function RunsPage() {
  const { data, error, reload } = useApi<RunListRow[]>("/api/runs?limit=100", { pollMs: 10000 });
  return (
    <>
      <PageHead title="Runs" sub="Every workflow you or an approval started, newest first." />
      <Gate data={data} error={error} retry={reload} what="Loading runs">
        {(runs) => (
          <Card flush>
            <Table
              rows={runs}
              rowKey={(r) => r.id}
              onRowClick={(r) => navigate("runs", r.id)}
              empty={<EmptyState title="No runs yet">Pick a command in the bar above, describe what you want, and press Run.</EmptyState>}
              columns={[
                { key: "cmd", header: "Command", render: (r) => <span className="mono">{r.command}</span> },
                { key: "status", header: "Status", render: (r) => <Badge value={r.status} /> },
                { key: "req", header: "Request", className: "cell-wide", render: (r) => (r.request ? <span className="ink-2">{r.request.length > 180 ? r.request.slice(0, 180) + "…" : r.request}</span> : <span className="muted">—</span>) },
                { key: "cost", header: "Cost", num: true, render: (r) => usd(r.cost_usd) },
                {
                  key: "dur",
                  header: "Duration",
                  num: true,
                  render: (r) => {
                    const a = parseDate(r.created_at);
                    const b = parseDate(r.finished_at);
                    return a && b ? duration(b.getTime() - a.getTime()) : "—";
                  },
                },
                { key: "at", header: "Started", render: (r) => <span className="nowrap small">{dateTime(r.created_at)}</span> },
              ]}
            />
          </Card>
        )}
      </Gate>
    </>
  );
}
