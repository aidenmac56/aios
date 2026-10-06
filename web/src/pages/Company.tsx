import { Badge } from "../components/Badge";
import { Card, PageHead } from "../components/Card";
import { EmptyState, Gate } from "../components/EmptyState";
import { humanize } from "../format";
import { useApi } from "../hooks";
import { href } from "../router";
import type { CompanyRow, CompanyStatus, Principle } from "../types";

function asText(v: unknown): string {
  if (typeof v === "string") return v;
  if (v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    if (typeof o.name === "string") return o.name + (typeof o.description === "string" ? `: ${o.description}` : "");
    return JSON.stringify(v);
  }
  return String(v);
}

export function CompanyPage() {
  const { data, error, reload } = useApi<CompanyStatus>("/api/status");
  return (
    <Gate data={data} error={error} retry={reload} what="Loading company">
      {(st) => (
        <>
          <PageHead title="Company" sub="What the agents are told the company is for. Edit it by reloading the founder seed." />
          <div className="stack">
            {st.companies.length === 0 ? (
              <EmptyState title="No company profile">
                Load the reviewed founder seed with <code>aios seed</code> to record the company name, mission, strategy and products.
              </EmptyState>
            ) : (
              st.companies.map((c) => <CompanyProfile key={c.id} c={c} />)
            )}
            <div className="grid">
              <div className="span-6">
                <Card title="Founder focus" sub="The memories agents weigh most: goals, priorities, principles." actions={<a href={href("memory")}>All memory</a>} flush>
                  {st.founder_focus.length === 0 ? (
                    <EmptyState title="No founder memory yet">Add what you want the company to optimize for on the Memory page.</EmptyState>
                  ) : (
                    <div>
                      {st.founder_focus.map((m) => (
                        <div className="mem-item" key={m.id}>
                          <div className="row-between">
                            <span className="row-title">{humanize(m.subject)}</span>
                            <Badge value={m.status} kind="memory" />
                          </div>
                          <p className="ink-2 mt-8">{m.content}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </Card>
              </div>
              <div className="span-6">
                <Card title="Principles" sub="Plans are checked against these; conflicts need your approval." flush>
                  {st.principles.length === 0 ? (
                    <EmptyState title="No principles set">
                      Add a memory tagged <code>principle:&lt;key&gt;</code>, or set founder.principles in Settings (for example a preserve_cash ceiling).
                    </EmptyState>
                  ) : (
                    <div>
                      {st.principles.map((p, i) => (
                        <PrincipleRow key={i} p={p} />
                      ))}
                    </div>
                  )}
                </Card>
              </div>
            </div>
          </div>
        </>
      )}
    </Gate>
  );
}

function PrincipleRow({ p }: { p: Principle }) {
  const extra = Object.entries(p).filter(([k]) => !["key", "text", "memory_id"].includes(k));
  return (
    <div className="mem-item">
      <div className="row-between">
        <span className="row-title">{p.key ? humanize(p.key) : "Principle"}</span>
        <span className="small muted">{p.memory_id ? "From memory" : "From settings"}</span>
      </div>
      {p.text && <p className="ink-2 mt-8">{p.text}</p>}
      {extra.length > 0 && (
        <div className="row-meta">
          {extra.map(([k, v]) => (
            <span key={k}>
              {humanize(k)}: {typeof v === "object" ? JSON.stringify(v) : String(v)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function CompanyProfile({ c }: { c: CompanyRow }) {
  const products = (c.products ?? []).map(asText);
  const customers = (c.customers ?? []).map(asText);
  return (
    <Card title={c.name}>
      <div className="stack">
        {c.mission && (
          <div>
            <h3 className="subhead">Mission</h3>
            <p className="conclusion" style={{ fontSize: 16 }}>
              {c.mission}
            </p>
          </div>
        )}
        <div className="grid">
          <div className="span-6">
            <h3 className="subhead">Strategy</h3>
            <p className="ink-2 prose">{c.strategy || <span className="muted">Not recorded.</span>}</p>
          </div>
          <div className="span-6">
            <h3 className="subhead">Business model</h3>
            <p className="ink-2 prose">{c.business_model || <span className="muted">Not recorded.</span>}</p>
          </div>
          <div className="span-6">
            <h3 className="subhead">Products</h3>
            {products.length ? (
              <ul className="bullets">
                {products.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : (
              <p className="muted small">None recorded.</p>
            )}
          </div>
          <div className="span-6">
            <h3 className="subhead">Customers</h3>
            {customers.length ? (
              <ul className="bullets">
                {customers.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            ) : (
              <p className="muted small">None recorded.</p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}
