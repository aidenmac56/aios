import { href } from "../router";
import type { DraftOutput, TestArm, TestResult, TrendReport } from "../types";
import { Badge } from "./Badge";
import { Bullets, Callout, Card, KV } from "./Card";
import { Table } from "./Table";

function armLabel(a: TestArm): string {
  return `${a.model}, prompt v${a.config_version}`;
}

/** TEST → COMPARE result for one improvement: both arms per benchmark case, then the verdict. */
export function TestView({ test }: { test: TestResult }) {
  const cases = test.baseline.cases.map((b) => ({
    id: b.case,
    base: b.score,
    cand: test.candidate.cases.find((c) => c.case === b.case)?.score ?? null,
    err: b.error || test.candidate.cases.find((c) => c.case === b.case)?.error || null,
  }));
  const tone = test.verdict === "WORSE" ? "red" : test.verdict === "BETTER" ? "green" : "blue";
  return (
    <Card
      title="Benchmark comparison"
      sub="The same benchmark cases, run on the current setup and on the proposed change."
      actions={<Badge value={test.verdict === "WORSE" ? "FAILED" : "COMPLETED"} label={test.verdict} />}
    >
      <div className="stack-sm">
        <Callout tone={tone} title={`Verdict: ${test.verdict}`}>
          {test.conclusion}
        </Callout>
        <KV
          items={[
            ["Current setup", `${armLabel(test.baseline)}: score ${test.baseline.avg_score.toFixed(3)}, $${test.baseline.total_cost_usd.toFixed(4)}`],
            ["Proposed change", `${armLabel(test.candidate)}: score ${test.candidate.avg_score.toFixed(3)}, $${test.candidate.total_cost_usd.toFixed(4)}`],
            ["Improvement", <a href={href("audits")}>{test.improvement_id.slice(0, 8)} on the Audits page</a>],
          ]}
        />
        <Table
          rows={cases}
          rowKey={(r) => r.id}
          columns={[
            { key: "case", header: "Case", render: (r) => <span className="mono small">{r.id}</span> },
            { key: "base", header: "Current", num: true, render: (r) => r.base.toFixed(2) },
            { key: "cand", header: "Proposed", num: true, render: (r) => (r.cand === null ? "—" : r.cand.toFixed(2)) },
            { key: "err", header: "Error", render: (r) => (r.err ? <span className="small">{r.err}</span> : <span className="muted">—</span>) },
          ]}
        />
        <p className="small muted">
          Testing changes nothing live. If you want this change, request implementation on the Audits page and approve it on the
          Decisions page; it can be rolled back afterwards.
        </p>
      </div>
    </Card>
  );
}

const RELEVANCE_ORDER = { HIGH: 0, MEDIUM: 1, LOW: 2 } as const;

export function TrendsView({ report }: { report: TrendReport }) {
  const trends = [...report.trends].sort(
    (a, b) => RELEVANCE_ORDER[a.relevance] - RELEVANCE_ORDER[b.relevance] || Number(a.mostly_viral_discussion) - Number(b.mostly_viral_discussion),
  );
  return (
    <Card title="Trend intelligence" sub="Ranked by relevance to this company; evidence is judged separately from popularity.">
      <div className="stack-sm">
        <p className="prose">{report.summary}</p>
        {report.note && (
          <Callout tone="amber" title="Limited evidence">
            {report.note}
          </Callout>
        )}
        {trends.length === 0 ? (
          <p className="muted">No trends were identified.</p>
        ) : (
          trends.map((t) => (
            <div key={t.name} className="trend">
              <div className="row" style={{ gap: 8, alignItems: "baseline", flexWrap: "wrap" }}>
                <strong>{t.name}</strong>
                <Badge value={t.relevance} label={`relevance ${t.relevance.toLowerCase()}`} tone={t.relevance === "HIGH" ? "green" : t.relevance === "MEDIUM" ? "amber" : "gray"} />
                <Badge value={t.trajectory} label={t.trajectory.toLowerCase()} tone="blue" />
                <Badge value={t.evidence_strength} label={`evidence ${t.evidence_strength.toLowerCase()}`} tone={t.evidence_strength === "STRONG" ? "green" : t.evidence_strength === "MODERATE" ? "amber" : "red"} />
                {t.mostly_viral_discussion && <Badge value="VIRAL" label="mostly buzz" tone="red" />}
                <span className="small muted">
                  {t.category} · confidence {t.confidence.toLowerCase()}
                </span>
              </div>
              <KV
                items={[
                  ["Signal", t.signal],
                  ["Market impact", t.market_impact],
                  ["Why it matters here", t.relevance_why],
                  ["Opportunity", t.business_opportunity ? `${t.business_opportunity} (test cost $${t.cost_to_test_usd.toLocaleString()})` : null],
                  ["Risks", t.risks.length ? <Bullets items={t.risks} /> : null],
                  [
                    "Evidence",
                    t.evidence.length ? (
                      <ul className="bullets">
                        {t.evidence.map((e, i) => (
                          <li key={i}>
                            {e.claim}{" "}
                            {/^https?:\/\//.test(e.source) ? (
                              <a href={e.source} target="_blank" rel="noreferrer">
                                source
                              </a>
                            ) : (
                              <span className="muted small">({e.source})</span>
                            )}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="muted">none cited</span>
                    ),
                  ],
                ]}
              />
            </div>
          ))
        )}
        {report.ignore.length > 0 && (
          <div>
            <div className="subhead">Deliberately ranked low</div>
            <Bullets items={report.ignore} />
          </div>
        )}
        {report.experiments.length > 0 && (
          <div>
            <div className="subhead">Cheap tests</div>
            <Table
              rows={report.experiments}
              rowKey={(e) => e.hypothesis}
              columns={[
                { key: "h", header: "Hypothesis", render: (e) => e.hypothesis },
                { key: "m", header: "Metric", render: (e) => `${e.metric} (${e.success_threshold})` },
                { key: "b", header: "Budget", num: true, render: (e) => `$${e.budget_usd.toLocaleString()}` },
                { key: "d", header: "Days", num: true, render: (e) => e.duration_days },
              ]}
            />
          </div>
        )}
      </div>
    </Card>
  );
}

export function DraftView({ draft }: { draft: DraftOutput }) {
  return (
    <Card title="Drafts" sub="Written in your voice for your review. Nothing is published.">
      <div className="stack-sm">
        <p className="prose">{draft.summary}</p>
        {draft.items.map((it) => (
          <div key={it.label} className="trend">
            <strong>{it.label}</strong>
            <p className="prose" style={{ whiteSpace: "pre-wrap", margin: 0 }}>{it.text}</p>
            {it.why && <span className="small muted">{it.why}</span>}
          </div>
        ))}
        {draft.recommended.length > 0 && (
          <div>
            <div className="subhead">Use first</div>
            <Bullets items={draft.recommended} />
          </div>
        )}
      </div>
    </Card>
  );
}
