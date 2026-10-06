import { Badge, sentence } from "../components/Badge";
import { ClaimsTable } from "../components/BriefView";
import { Bullets, Callout, Card, PageHead } from "../components/Card";
import { EmptyState, Gate } from "../components/EmptyState";
import { Table } from "../components/Table";
import { dateOnly, dateTime } from "../format";
import { useApi } from "../hooks";
import { href, navigate } from "../router";
import type { ResearchReport } from "../types";

export function ResearchPage({ id }: { id: string | null }) {
  return id ? <ReportDetail id={id} /> : <ReportList />;
}

function ReportList() {
  const { data, error, reload } = useApi<ResearchReport[]>("/api/research");
  return (
    <>
      <PageHead title="Research" sub="Reusable reports. Fresh reports answering the same question are reused instead of re-searched." />
      <Gate data={data} error={error} retry={reload} what="Loading research">
        {(rows) => (
          <Card flush>
            <Table
              rows={rows}
              rowKey={(r) => r.id}
              onRowClick={(r) => navigate("research", r.id)}
              empty={<EmptyState title="No research yet">Run research with a question, or run opportunity or market; reports are saved here with their sources.</EmptyState>}
              columns={[
                { key: "q", header: "Question", className: "cell-wide", render: (r) => <span className="row-title">{r.question}</span> },
                { key: "c", header: "Confidence", render: (r) => <Badge value={r.confidence} kind="confidence" /> },
                { key: "l", header: "Search", render: (r) => (r.live_search_used ? <Badge tone="green" label="Live" /> : <Badge tone="amber" label="None" />) },
                { key: "s", header: "Freshness", render: (r) => (r.stale ? <Badge tone="orange" label="Stale" /> : <Badge tone="gray" label={`Fresh for ${r.freshness_days} d`} />) },
                { key: "d", header: "Date", render: (r) => <span className="nowrap small">{dateOnly(r.created_at.slice(0, 10))}</span> },
              ]}
            />
          </Card>
        )}
      </Gate>
    </>
  );
}

function ReportDetail({ id }: { id: string }) {
  const { data, error, reload } = useApi<ResearchReport>(`/api/research/${encodeURIComponent(id)}`);
  return (
    <Gate data={data} error={error} retry={reload} what="Loading report">
      {(r) => {
        const claims = r.claims ?? [];
        const facts = claims.filter((c) => c.is_fact).length;
        return (
          <>
            <PageHead
              crumb={<a href={href("research")}>Research</a>}
              title={r.question}
              sub={r.decision_supported ? `Supports: ${r.decision_supported}` : undefined}
              actions={
                <>
                  <Badge value={r.confidence} kind="confidence" label={`${sentence(r.confidence)} confidence`} />
                  {r.live_search_used ? <Badge tone="green" label="Live search used" /> : <Badge tone="amber" label="No live search" />}
                  {r.stale && <Badge tone="orange" label="Stale" />}
                </>
              }
            />
            <div className="stack">
              {r.stale && (
                <Callout tone="orange" title="This report is stale">
                  It was due for a re-check {r.freshness_days} days after {dateTime(r.created_at)}. Run research again with the same question to refresh it.
                </Callout>
              )}
              {!r.live_search_used && (
                <Callout tone="amber" title="Written without live search">
                  Confidence is capped at low. Enable web search on the server for sourced facts.
                </Callout>
              )}
              <Card title="Answer" sub={`By ${r.created_by_agent ?? "research"} on ${dateTime(r.created_at)}`}>
                <p className="prose pre-line" style={{ fontSize: 15 }}>
                  {r.answer}
                </p>
              </Card>
              <Card title="Claims" sub={`${facts} sourced fact${facts === 1 ? "" : "s"}, ${claims.length - facts} interpretation${claims.length - facts === 1 ? "" : "s"}`} flush>
                {claims.length === 0 ? <EmptyState title="No claims recorded" /> : <ClaimsTable claims={claims} />}
              </Card>
              <div className="grid">
                <div className="span-6">
                  <Card title="Where sources disagree">
                    <Bullets items={r.disagreements ?? []} empty="No disagreements recorded." />
                  </Card>
                </div>
                <div className="span-6">
                  <Card title="What would change the conclusion">
                    <Bullets items={r.what_would_change ?? []} empty="Not stated." />
                  </Card>
                </div>
                <div className="span-6">
                  <Card title="Assumptions">
                    <Bullets items={r.assumptions ?? []} empty="None stated." />
                  </Card>
                </div>
                <div className="span-6">
                  <Card title="Sub-questions">
                    <Bullets items={r.subquestions ?? []} empty="None." />
                  </Card>
                </div>
              </div>
            </div>
          </>
        );
      }}
    </Gate>
  );
}
