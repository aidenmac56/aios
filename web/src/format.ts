// Formatting helpers. API cents → "$1,234.56"; *_usd values are dollars.

const usd2 = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function cents(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unknown";
  return usd2.format(value / 100);
}

/** Dollar amounts. Small AI costs keep more precision so $0.0042 does not read as $0.00. */
export function usd(value: number | null | undefined, opts: { precise?: boolean } = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unknown";
  const abs = Math.abs(value);
  if (opts.precise !== false && abs > 0 && abs < 1) {
    const digits = abs < 0.01 ? 4 : 3;
    return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
  }
  return usd2.format(value);
}

export function num(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "unknown";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

/** The API stores naive UTC timestamps (no zone suffix). Treat them as UTC. */
export function parseDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  let v = value;
  if (/^\d{4}-\d{2}-\d{2}T[\d:.]+$/.test(v)) v += "Z";
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function dateTime(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", year: sameYear(d) ? undefined : "numeric", hour: "numeric", minute: "2-digit" });
}

export function dateOnly(value: string | null | undefined): string {
  if (!value) return "—";
  // Plain dates (YYYY-MM-DD) are calendar dates, not instants: format without zone shifting.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (m) {
    const d = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  }
  const d = parseDate(value);
  return d ? d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : value;
}

function sameYear(d: Date): boolean {
  return d.getFullYear() === new Date().getFullYear();
}

export function relative(value: string | null | undefined): string {
  const d = parseDate(value);
  if (!d) return "—";
  const s = Math.round((Date.now() - d.getTime()) / 1000);
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const days = Math.round(h / 24);
  if (days < 14) return `${days} d ago`;
  return dateOnly(value);
}

export function duration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  return `${m} m ${Math.round(s % 60)} s`;
}

export function monthLabel(ym: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(ym);
  if (!m) return ym;
  return new Date(Number(m[1]), Number(m[2]) - 1, 1).toLocaleDateString(undefined, { month: "short", year: "numeric" });
}

export function dayLabel(ymd: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(ymd);
  if (!m) return ymd;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function humanize(key: string): string {
  const s = key.replace(/[._]+/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}

export function isHttp(s: string | null | undefined): boolean {
  return !!s && /^https?:\/\//i.test(s);
}

export function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}
