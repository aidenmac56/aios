import type { ReactNode } from "react";

export function Card({
  title,
  sub,
  actions,
  children,
  flush,
  className,
  id,
}: {
  title?: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
  /** Remove body padding so tables and row lists run edge to edge. */
  flush?: boolean;
  className?: string;
  id?: string;
}) {
  return (
    <section className={["panel", className].filter(Boolean).join(" ")} id={id}>
      {(title || actions) && (
        <header className="panel-head">
          <div>
            {title && <h2 className="panel-title">{title}</h2>}
            {sub && <div className="panel-sub">{sub}</div>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      <div className={flush ? "panel-body flush" : "panel-body"}>{children}</div>
    </section>
  );
}

export function PageHead({ title, sub, crumb, actions }: { title: ReactNode; sub?: ReactNode; crumb?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div style={{ minWidth: 0 }}>
        {crumb && <div className="crumb">{crumb}</div>}
        <h1 className="page-title">{title}</h1>
        {sub && <div className="page-sub">{sub}</div>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export interface StatItem {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
  unknown?: boolean;
}

export function Stats({ items }: { items: StatItem[] }) {
  return (
    <div className="stats">
      {items.map((s, i) => (
        <div className="stat" key={i}>
          <div className="stat-label">{s.label}</div>
          <div className={s.unknown ? "stat-value unknown" : "stat-value"}>{s.value}</div>
          {s.note && <div className="stat-note">{s.note}</div>}
        </div>
      ))}
    </div>
  );
}

export function KV({ items }: { items: [ReactNode, ReactNode][] }) {
  const shown = items.filter(([, v]) => v !== null && v !== undefined && v !== "");
  return (
    <dl className="kv">
      {shown.map(([k, v], i) => (
        <div key={i} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export function Callout({ tone = "gray", title, children }: { tone?: string; title?: ReactNode; children?: ReactNode }) {
  return (
    <div className={`callout tone-${tone}`} role={tone === "red" ? "alert" : undefined}>
      {title && <div className="callout-title">{title}</div>}
      {children}
    </div>
  );
}

export function Bullets({ items, empty }: { items: ReactNode[] | null | undefined; empty?: ReactNode }) {
  if (!items || items.length === 0) return empty ? <p className="muted small">{empty}</p> : null;
  return (
    <ul className="bullets">
      {items.map((x, i) => (
        <li key={i}>{x}</li>
      ))}
    </ul>
  );
}

export function Chips({ items, mono }: { items: string[] | null | undefined; mono?: boolean }) {
  if (!items || items.length === 0) return <span className="muted small">None</span>;
  return (
    <div className="chips">
      {items.map((x) => (
        <span key={x} className={mono ? "chip mono" : "chip"}>
          {x}
        </span>
      ))}
    </div>
  );
}

export function Progress({ pct, label }: { pct: number; label?: string }) {
  const p = Math.max(0, Math.min(100, pct));
  return (
    <div className="progress" role="progressbar" aria-valuenow={p} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <span style={{ width: `${p}%` }} />
    </div>
  );
}

export function Meter({ value, max, tone, label }: { value: number; max: number; tone?: string; label?: string }) {
  const p = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  const t = tone ?? (p >= 90 ? "var(--red)" : p >= 70 ? "var(--amber)" : "var(--blue)");
  return (
    <div className="meter" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max} aria-label={label}>
      <span style={{ width: `${p}%`, ["--tone" as string]: t }} />
    </div>
  );
}
