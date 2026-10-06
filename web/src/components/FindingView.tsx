import { humanize } from "../format";
import type { AgentFindingLike, RiskItem } from "../types";
import { Badge, sentence } from "./Badge";
import { Bullets, Callout } from "./Card";
import { Table } from "./Table";

/** Generic renderer for an AgentFinding (cfo, cto, ...) including the CTO's tech dimensions. */
export function FindingView({ f }: { f: AgentFindingLike }) {
  if (f.error) return <Callout tone="red" title="This agent failed">{String(f.error)}</Callout>;
  const tech = f.tech as { feasibility?: string; recommended_stack?: string[]; build_vs_buy?: string; dimensions?: { dimension: string; score: number; note: string }[]; time_to_mvp_weeks_low?: number; time_to_mvp_weeks_high?: number; security_concerns?: string[]; technical_debt_or_lock_in?: string[] } | undefined;
  return (
    <div className="stack-sm">
      <div className="row">
        {f.stance && <Badge tone="gray" label={`Stance: ${sentence(f.stance)}`} />}
        {f.confidence && <Badge value={f.confidence} kind="confidence" label={`${sentence(f.confidence)} confidence`} />}
      </div>
      {f.conclusion && <p className="conclusion" style={{ fontSize: 15 }}>{f.conclusion}</p>}
      {f.summary && <p className="ink-2 prose">{f.summary}</p>}
      {f.key_points && f.key_points.length > 0 && (
        <>
          <h3 className="subhead">Key points</h3>
          <Bullets items={f.key_points} />
        </>
      )}
      {tech && (
        <>
          <h3 className="subhead">Technology assessment</h3>
          <p className="small ink-2">
            Feasibility {tech.feasibility ? sentence(tech.feasibility).toLowerCase() : "unknown"}
            {tech.time_to_mvp_weeks_low !== undefined && `, MVP in ${tech.time_to_mvp_weeks_low}–${tech.time_to_mvp_weeks_high} weeks (estimate)`}
          </p>
          {tech.build_vs_buy && <p className="small">Build vs buy: {tech.build_vs_buy}</p>}
          {tech.recommended_stack && tech.recommended_stack.length > 0 && <p className="small">Stack: {tech.recommended_stack.join(", ")}</p>}
          {tech.dimensions && tech.dimensions.length > 0 && (
            <div className="score mt-8">
              {tech.dimensions.map((d) => (
                <div key={d.dimension} style={{ display: "contents" }}>
                  <span>{humanize(d.dimension)}</span>
                  <span className="score-cells" role="img" aria-label={`${d.score} of 5`}>
                    {[1, 2, 3, 4, 5].map((i) => (
                      <i key={i} className={i <= d.score ? "on" : ""} />
                    ))}
                  </span>
                  <span className="score-note small muted">{d.note}</span>
                </div>
              ))}
            </div>
          )}
          {tech.security_concerns && tech.security_concerns.length > 0 && (
            <>
              <h3 className="subhead">Security concerns</h3>
              <Bullets items={tech.security_concerns} />
            </>
          )}
        </>
      )}
      {f.risks && f.risks.length > 0 && (
        <>
          <h3 className="subhead">Risks</h3>
          <Table
            dense
            rows={f.risks as RiskItem[]}
            rowKey={(r) => r.risk}
            columns={[
              { key: "r", header: "Risk", render: (r) => r.risk, className: "cell-wide" },
              { key: "l", header: "Likelihood", render: (r) => <Badge value={r.likelihood} kind="severity" /> },
              { key: "i", header: "Impact", render: (r) => <Badge value={r.impact} kind="severity" /> },
              { key: "m", header: "Mitigation", render: (r) => <span className="ink-2">{r.mitigation}</span> },
            ]}
          />
        </>
      )}
      {f.recommendation && (
        <div className="action-block mt-8">
          <div className="label">Recommendation</div>
          <div>{f.recommendation}</div>
        </div>
      )}
      {f.open_questions && f.open_questions.length > 0 && (
        <>
          <h3 className="subhead">Open questions</h3>
          <Bullets items={f.open_questions} />
        </>
      )}
    </div>
  );
}
