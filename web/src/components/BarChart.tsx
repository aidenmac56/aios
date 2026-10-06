import { useEffect, useLayoutEffect, useRef, useState } from "react";

// Hand-rolled SVG bar chart: one or two series, grouped; hover tooltip per category; optional
// dashed reference line; legend for 2+ series; a table view for accessibility.

export interface Series {
  name: string;
  /** CSS color, normally a var(--series-n) token. */
  color: string;
  values: number[];
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const exp = Math.pow(10, Math.floor(Math.log10(v)));
  const f = v / exp;
  const nf = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nf * exp;
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(0);
  useLayoutEffect(() => {
    if (ref.current) setW(ref.current.getBoundingClientRect().width);
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setW(e.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w];
}

/** Rect with only the top corners rounded (data end), anchored flat on the baseline. */
function barPath(x: number, y: number, w: number, h: number, r: number): string {
  if (h <= 0) return "";
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

export function BarChart({
  categories,
  series,
  format,
  height = 220,
  refLine,
  label,
}: {
  categories: string[];
  series: Series[];
  format: (n: number) => string;
  height?: number;
  refLine?: { value: number; label: string } | null;
  label: string;
}) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const n = categories.length;
  const left = 64;
  const right = 8;
  const top = 10;
  const bottom = 26;
  const plotW = Math.max(0, width - left - right);
  const plotH = height - top - bottom;

  const dataMax = Math.max(0, ...series.flatMap((s) => s.values), refLine ? refLine.value : 0);
  const yMax = niceMax(dataMax * 1.05);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const y = (v: number) => top + plotH - (Math.max(0, v) / yMax) * plotH;

  const groupW = n > 0 ? plotW / n : 0;
  const sc = series.length;
  const gap = 2;
  const barW = Math.max(2, Math.min(26, (groupW * 0.72 - gap * (sc - 1)) / sc));
  const clusterW = barW * sc + gap * (sc - 1);

  // label thinning so x labels never collide (~56px per label)
  const every = Math.max(1, Math.ceil((n * 56) / Math.max(plotW, 1)));

  const tipX = hover !== null ? left + groupW * hover + groupW / 2 : 0;

  return (
    <div className="chart">
      {sc > 1 && (
        <div className="chart-legend" aria-hidden="true">
          {series.map((s) => (
            <span key={s.name}>
              <i className="swatch" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      )}
      <div ref={ref} style={{ position: "relative" }} onMouseLeave={() => setHover(null)}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={label}>
            {ticks.map((t, i) => (
              <g key={i}>
                <line x1={left} x2={width - right} y1={y(t)} y2={y(t)} stroke={i === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
                <text x={left - 8} y={y(t)} dy="0.32em" textAnchor="end" className="chart-tick">
                  {format(t)}
                </text>
              </g>
            ))}
            {categories.map((c, i) => {
              const gx = left + groupW * i;
              const cx = gx + (groupW - clusterW) / 2;
              return (
                <g key={c + i}>
                  {hover === i && <rect x={gx} y={top} width={groupW} height={plotH} fill="var(--panel-2)" />}
                  {series.map((s, si) => {
                    const v = s.values[i] ?? 0;
                    const by = y(v);
                    const h = top + plotH - by;
                    return <path key={s.name} d={barPath(cx + si * (barW + gap), by, barW, h, 3)} fill={s.color} />;
                  })}
                  {i % every === 0 && (
                    <text x={gx + groupW / 2} y={height - 8} textAnchor="middle" className="chart-tick">
                      {c}
                    </text>
                  )}
                  <rect
                    x={gx}
                    y={top}
                    width={groupW}
                    height={plotH}
                    fill="transparent"
                    onMouseEnter={() => setHover(i)}
                    onFocus={() => setHover(i)}
                    onBlur={() => setHover(null)}
                    tabIndex={0}
                    aria-label={`${c}: ${series.map((s) => `${s.name} ${format(s.values[i] ?? 0)}`).join(", ")}`}
                  />
                </g>
              );
            })}
            {refLine && refLine.value > 0 && (
              <g>
                <line x1={left} x2={width - right} y1={y(refLine.value)} y2={y(refLine.value)} stroke="var(--muted)" strokeDasharray="4 4" strokeWidth={1} />
                <text x={width - right} y={y(refLine.value) - 5} textAnchor="end" className="chart-tick">
                  {refLine.label} {format(refLine.value)}
                </text>
              </g>
            )}
          </svg>
        )}
        {hover !== null && width > 0 && (
          <div
            className="chart-tip"
            style={{
              left: Math.min(Math.max(tipX - 80, 0), Math.max(width - 180, 0)),
              top: 4,
            }}
          >
            <div className="chart-tip-title">{categories[hover]}</div>
            {series.map((s) => (
              <div className="chart-tip-row" key={s.name}>
                <span className="row" style={{ gap: 6 }}>
                  <i className="swatch" style={{ background: s.color }} />
                  {s.name}
                </span>
                <b>{format(s.values[hover] ?? 0)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
      <details className="chart-table">
        <summary>Show as table</summary>
        <div className="table-wrap">
          <table className="table table-dense">
            <thead>
              <tr>
                <th scope="col">Period</th>
                {series.map((s) => (
                  <th scope="col" className="num" key={s.name}>
                    {s.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {categories.map((c, i) => (
                <tr key={c + i}>
                  <td>{c}</td>
                  {series.map((s) => (
                    <td className="num" key={s.name}>
                      {format(s.values[i] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
