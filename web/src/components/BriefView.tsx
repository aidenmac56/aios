import type { ReactNode } from "react";
import { hostOf, isHttp, num, usd } from "../format";
import { href } from "../router";
import type {
  ClaimSource,
  Evidence,
  ExecutiveBrief,
  ResearchClaimAny,
  ResearchOutput,
  RiskAudit,
  TwinAlignment,
  UnitEconomics,
} from "../types";
import { Badge, sentence } from "./Badge";
import { Bullets, Callout } from "./Card";
import { Table } from "./Table";


/** Render a source reference: URLs become links; internal refs (memory:, research:, decision:) link in-app. */
export function SourceRef({ source }: { source: string | null | undefined }) {
  if (!source) return <span className="muted">no source</span>;
  if (isHttp(source)) {
    return (
      <a href={source} target="_blank" rel="noreferrer noopener" title={source}>
        {hostOf(source)}
      </a>
    );
  }
  const m = /^(research|decision|memory):([A-Za-z0-9]+)/.exec(source);
  if (m) {
    const page = m[1] === "research" ? "research" : m[1] === "decision" ? "decisions" : "memory";
    return (
      <a href={m[1] === "research" ? href(page, m[2]) : href(page)} className="mono small">
        {source}
      </a>
    );
  }
  return <span className="mono small ink-2">{source}</span>;
}

function Section({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <div>
      <h3 className="subhead">
        {title} {note && <span className="muted small" style={{ fontWeight: 400 }}>{note}</span>}
      </h3>
      {children}
    </div>
  );
}

function EvidenceTable({ items }: { items: Evidence[] }) {
  return (
    <Table
      dense
      rows={items}
      rowKey={(e) => e.claim + e.source}
      columns={[
        { key: "claim", header: "Claim", render: (e) => e.claim, className: "cell-wide" },
        { key: "src", header: "Source", render: (e) => <SourceRef source={e.source} /> },
        { key: "type", header: "Type", render: (e) => <span className="small ink-2">{sentence(e.source_type)}</span> },
        { key: "conf", header: "Confidence", render: (e) => <Badge value={e.confidence} kind="confidence" /> },
      ]}
    />
  );
}

const SCORE_LABELS: Record<string, string> = {
  customer_pain: "Customer pain",
  market_size: "Market size",
  market_growth: "Market growth",
  competition: "Competition",
  differentiation: "Differentiation",
  willingness_to_pay: "Willingness to pay",
  distribution: "Distribution",
  technical_feasibility: "Technical feasibility",
  capital_requirement: "Capital requirement",
  time_to_market: "Time to market",
  defensibility: "Defensibility",
  regulatory_risk: "Regulatory risk",
};

export function Scorecard({ lines }: { lines: ExecutiveBrief["scorecard"] }) {
  const total = lines.reduce((a, l) => a + l.score, 0);
  return (
    <div>
      <div className="score">
        {lines.map((l) => (
          <div key={l.dimension} style={{ display: "contents" }}>
            <span>{SCORE_LABELS[l.dimension] ?? sentence(l.dimension)}</span>
            <span className="score-cells" role="img" aria-label={`${l.score} of 5`}>
              {[1, 2, 3, 4, 5].map((i) => (
                <i key={i} className={i <= l.score ? "on" : ""} />
              ))}
            </span>
            <span className="score-note small muted">
              <b className="tnum" style={{ color: "var(--ink)", marginRight: 6 }}>
                {l.score}/5
              </b>
              {l.note}
            </span>
          </div>
        ))}
      </div>
      <p className="small muted mt-8">
        Total {total} of {lines.length * 5}. 5 is most favorable for building.
      </p>
    </div>
  );
}

export function BriefView({ brief }: { brief: ExecutiveBrief }) {
  return (
    <div className="stack">
      <div className="row" style={{ gap: 10 }}>
        <Badge value={brief.verdict} kind="verdict" size="lg" />
        <Badge value={brief.confidence} kind="confidence" label={`${sentence(brief.confidence)} confidence`} />
        {brief.requires_approval && <Badge tone="amber" label="Needs your decision" />}
        <span className="small muted">
          {sentence(brief.decision_type)} decision, {sentence(brief.reversibility).toLowerCase()} to reverse
        </span>
      </div>
      <p className="conclusion">{brief.conclusion}</p>

      {brief.recommended_action && (
        <div className="action-block">
          <div className="label">Recommended action</div>
          <div>{brief.recommended_action}</div>
        </div>
      )}

      <div className="grid">
        <div className="span-6 stack-sm">
          <Section title="Why">
            <Bullets items={brief.why} empty="No reasons given." />
          </Section>
        </div>
        <div className="span-6 stack-sm">
          <Section title="Opposing arguments">
            <Bullets items={brief.opposing_arguments} empty="None raised." />
          </Section>
        </div>
      </div>

      {brief.next_steps.length > 0 && (
        <Section title="Next steps">
          <ol className="bullets">
            {brief.next_steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
        </Section>
      )}

      {brief.options.length > 0 && (
        <Section title="Options">
          <div className="options">
            {brief.options.map((o) => (
              <div key={o.label} className={o.recommended ? "option recommended" : "option"}>
                <div className="row-between">
                  <h4>{o.label}</h4>
                  {o.recommended && <Badge tone="accent" label="Recommended" />}
                </div>
                {o.description && <p className="small ink-2">{o.description}</p>}
                <div className="row-meta">
                  <span>Expected value: {o.expected_value || "—"}</span>
                  <span>Risk: {o.risk || "—"}</span>
                </div>
                {(o.pros.length > 0 || o.cons.length > 0) && (
                  <div className="pc">
                    <div>
                      <div className="muted">Pros</div>
                      <Bullets items={o.pros} empty="None" />
                    </div>
                    <div>
                      <div className="muted">Cons</div>
                      <Bullets items={o.cons} empty="None" />
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </Section>
      )}

      {brief.evidence.length > 0 && (
        <Section title="Evidence">
          <div className="panel" style={{ background: "var(--inset)" }}>
            <EvidenceTable items={brief.evidence} />
          </div>
        </Section>
      )}

      {brief.risks.length > 0 && (
        <Section title="Risks">
          <div className="panel" style={{ background: "var(--inset)" }}>
            <Table
              dense
              rows={brief.risks}
              rowKey={(r) => r.risk}
              columns={[
                { key: "risk", header: "Risk", render: (r) => r.risk, className: "cell-wide" },
                { key: "l", header: "Likelihood", render: (r) => <Badge value={r.likelihood} kind="severity" /> },
                { key: "i", header: "Impact", render: (r) => <Badge value={r.impact} kind="severity" /> },
                { key: "m", header: "Mitigation", render: (r) => <span className="ink-2">{r.mitigation}</span>, className: "cell-mid" },
              ]}
            />
          </div>
        </Section>
      )}

      {brief.costs.length > 0 && (
        <Section title="Costs" note="All figures are estimates, not actuals.">
          <div className="panel" style={{ background: "var(--inset)" }}>
            <Table
              dense
              rows={brief.costs}
              rowKey={(c) => c.item}
              columns={[
                { key: "item", header: "Item", render: (c) => c.item, className: "cell-mid" },
                {
                  key: "range",
                  header: "Estimate",
                  num: true,
                  render: (c) => (
                    <span>
                      {c.low_usd === c.high_usd ? usd(c.low_usd, { precise: false }) : `${usd(c.low_usd, { precise: false })} – ${usd(c.high_usd, { precise: false })}`}
                    </span>
                  ),
                },
                { key: "rec", header: "Recurs", render: (c) => sentence(c.recurring) },
                { key: "kind", header: "", render: () => <Badge tone="gray" label="Estimate" /> },
                { key: "basis", header: "Basis", render: (c) => <span className="ink-2">{c.basis}</span>, className: "cell-mid" },
              ]}
            />
          </div>
        </Section>
      )}

      <div className="grid">
        {brief.upside && (
          <div className="span-6">
            <Section title="Upside">
              <p className="ink-2 pre-line">{brief.upside}</p>
            </Section>
          </div>
        )}
        {brief.uncertainty && (
          <div className="span-6">
            <Section title="Uncertainty">
              <p className="ink-2 pre-line">{brief.uncertainty}</p>
            </Section>
          </div>
        )}
      </div>

      {brief.disagreements.length > 0 && (
        <Section title="Disagreements between agents">
          <div className="stack-sm">
            {brief.disagreements.map((d, i) => (
              <Callout key={i} tone={d.basis === "unresolved" ? "orange" : "gray"} title={d.topic}>
                <Bullets items={d.positions} />
                <p className="mt-8">
                  <span className="muted">Resolution: </span>
                  {d.resolution}
                </p>
                <p className="small muted">Basis: {d.basis}</p>
              </Callout>
            ))}
          </div>
        </Section>
      )}

      {brief.founder_alignment && (
        <Section title="Fit with your stated preferences">
          <p className="ink-2 prose">{brief.founder_alignment}</p>
        </Section>
      )}

      {brief.scorecard.length > 0 && (
        <Section title="Opportunity scorecard">
          <Scorecard lines={brief.scorecard} />
        </Section>
      )}
    </div>
  );
}

export function RiskAuditView({ audit }: { audit: RiskAudit }) {
  return (
    <div className="stack-sm">
      <div className="row">
        <Badge value={audit.verdict} kind="verdict" size="lg" />
      </div>
      <p className="prose">{audit.summary}</p>
      {audit.issues.length > 0 && (
        <div className="panel mt-8" style={{ background: "var(--inset)" }}>
          <Table
            dense
            rows={audit.issues}
            rowKey={(i) => i.target + i.problem}
            columns={[
              { key: "sev", header: "Severity", render: (i) => <Badge value={i.severity} kind="severity" /> },
              { key: "t", header: "About", render: (i) => <span className="ink-2">{i.target}</span> },
              { key: "p", header: "Problem", render: (i) => i.problem, className: "cell-wide" },
              { key: "f", header: "Fix", render: (i) => <span className="ink-2">{i.fix}</span>, className: "cell-mid" },
            ]}
          />
        </div>
      )}
      {audit.conditions.length > 0 && (
        <>
          <h3 className="subhead">Conditions</h3>
          <Bullets items={audit.conditions} />
        </>
      )}
      {audit.unsupported_claims.length > 0 && (
        <>
          <h3 className="subhead">Unsupported claims</h3>
          <Bullets items={audit.unsupported_claims} />
        </>
      )}
      {audit.calculation_checks.length > 0 && (
        <>
          <h3 className="subhead">Calculation checks</h3>
          <Bullets items={audit.calculation_checks} />
        </>
      )}
      {audit.strongest_counterargument && (
        <>
          <h3 className="subhead">Strongest counterargument</h3>
          <p className="ink-2 prose">{audit.strongest_counterargument}</p>
        </>
      )}
    </div>
  );
}

export function UnitEconomicsView({ ue }: { ue: UnitEconomics }) {
  const rows: [string, string][] = [
    ["Contribution per customer / month", usd(ue.contribution_per_customer_monthly_usd, { precise: false })],
    ["Lifetime value (LTV)", usd(ue.ltv_usd, { precise: false })],
    ["LTV to CAC", ue.ltv_to_cac === null ? "unknown" : `${num(ue.ltv_to_cac, 2)}×`],
    ["CAC payback", ue.cac_payback_months === null ? "unknown" : `${num(ue.cac_payback_months, 1)} months`],
    ["Break-even customers", num(ue.breakeven_customers)],
    ["Months to operating break-even", ue.months_to_operating_breakeven === null ? "not within 36 months" : num(ue.months_to_operating_breakeven)],
    ["Peak cash needed", usd(ue.peak_cash_needed_usd, { precise: false })],
    ["Customers after 36 months", num(ue.customers_after_36_months, 1)],
    ["Cumulative cash at 36 months", usd(ue.cumulative_cash_36_months_usd, { precise: false })],
  ];
  return (
    <div className="stack-sm">
      <div className="table-wrap">
        <table className="table table-dense">
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <td className="muted">{k}</td>
                <td className="num">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ue.simulation && <p className="small muted">Simulation: {ue.simulation}</p>}
    </div>
  );
}

function claimSource(c: ResearchClaimAny): ClaimSource | { url: string } | null {
  if (c.source) return c.source;
  if (c.source_url) return { url: c.source_url };
  return null;
}

export function ClaimsTable({ claims }: { claims: ResearchClaimAny[] }) {
  return (
    <Table
      dense
      rows={claims}
      rowKey={(c) => c.text}
      columns={[
        {
          key: "kind",
          header: "Kind",
          render: (c) => (c.is_fact ? <Badge tone="blue" label="Fact" /> : <Badge tone="gray" label="Interpretation" />),
        },
        { key: "text", header: "Claim", render: (c) => c.text, className: "cell-wide" },
        {
          key: "src",
          header: "Source",
          render: (c) => {
            const s = claimSource(c);
            if (!s) return <span className="muted small">Unsourced</span>;
            const full = "title" in s ? s : null;
            return (
              <div>
                <SourceRef source={s.url} />
                {full && (full.publisher || full.published) && (
                  <div className="small muted">
                    {[full.publisher, full.published].filter(Boolean).join(", ")}
                  </div>
                )}
              </div>
            );
          },
          className: "cell-mid",
        },
        {
          key: "cred",
          header: "Credibility",
          render: (c) => (c.source && "credibility" in c.source ? <Badge value={c.source.credibility} kind="confidence" /> : <span className="muted">—</span>),
        },
        { key: "conf", header: "Confidence", render: (c) => <Badge value={c.confidence} kind="confidence" /> },
      ]}
    />
  );
}

export function ResearchOutputView({ r }: { r: ResearchOutput }) {
  const reportId = r.report_id ?? r.reused_report_id;
  return (
    <div className="stack-sm">
      <div className="row">
        {r.confidence && <Badge value={r.confidence} kind="confidence" label={`${sentence(r.confidence)} confidence`} />}
        {r.live_search_used ? <Badge tone="green" label="Live search used" /> : <Badge tone="amber" label="No live search" />}
        {r.reused_report_id && <Badge tone="gray" label="Reused an existing report" />}
        {reportId && (
          <a className="small" href={href("research", reportId)}>
            Open report
          </a>
        )}
      </div>
      {r.question && <p className="muted small">Question: {r.question}</p>}
      {r.answer && <p className="prose pre-line">{r.answer}</p>}
      {r.search_error && !r.live_search_used && <Callout tone="amber">Search unavailable: {r.search_error}</Callout>}
      {r.source_problems && r.source_problems.length > 0 && (
        <Callout tone="orange" title="Source rules enforced">
          <Bullets items={r.source_problems} />
        </Callout>
      )}
      {r.claims && r.claims.length > 0 && (
        <div className="panel mt-8" style={{ background: "var(--inset)" }}>
          <ClaimsTable claims={r.claims} />
        </div>
      )}
      {r.disagreements && r.disagreements.length > 0 && (
        <>
          <h3 className="subhead">Where sources disagree</h3>
          <Bullets items={r.disagreements} />
        </>
      )}
      {r.what_would_change && r.what_would_change.length > 0 && (
        <>
          <h3 className="subhead">What would change the conclusion</h3>
          <Bullets items={r.what_would_change} />
        </>
      )}
    </div>
  );
}

export function TwinView({ twin }: { twin: TwinAlignment }) {
  return (
    <div className="stack-sm">
      <p className="prose">{twin.alignment_summary}</p>
      {twin.aligned_with.length > 0 && (
        <>
          <h3 className="subhead">Aligned with</h3>
          <Bullets
            items={twin.aligned_with.map((m) => (
              <span key={m.memory_id}>
                <Badge value={m.status} kind="memory" /> {m.note} <span className="mono small muted">memory:{m.memory_id.slice(0, 8)}</span>
              </span>
            ))}
          />
        </>
      )}
      {twin.conflicts_with.length > 0 && (
        <>
          <h3 className="subhead">Conflicts with</h3>
          <Bullets
            items={twin.conflicts_with.map((m) => (
              <span key={m.memory_id}>
                <Badge value={m.status} kind="memory" /> {m.note}
              </span>
            ))}
          />
        </>
      )}
      {twin.unknowns.length > 0 && (
        <>
          <h3 className="subhead">Unknown preferences</h3>
          <Bullets items={twin.unknowns} />
        </>
      )}
      {twin.proposed_inferences.length > 0 && (
        <>
          <h3 className="subhead">Proposed inferences (not facts)</h3>
          <Bullets
            items={twin.proposed_inferences.map((p) => (
              <span key={p.subject}>
                <Badge value={p.status} kind="memory" /> <b>{p.subject}</b>: {p.content} <span className="muted small">({p.evidence})</span>
              </span>
            ))}
          />
        </>
      )}
    </div>
  );
}
