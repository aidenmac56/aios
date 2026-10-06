import { useRef, useState } from "react";
import { api } from "../api";
import { Badge } from "../components/Badge";
import { BarChart } from "../components/BarChart";
import { Callout, Card, PageHead, Stats } from "../components/Card";
import { EmptyState, ErrorBox, Gate } from "../components/EmptyState";
import { FinanceSnapshot } from "../components/FinanceSnapshot";
import { Table } from "../components/Table";
import { cents, dateOnly, humanize, monthLabel, usd } from "../format";
import { useAction, useApi } from "../hooks";
import type { FinanceSummary, ImportResult, Transaction } from "../types";

export function FinancePage() {
  const summary = useApi<FinanceSummary>("/api/finance/summary");
  const [category, setCategory] = useState("");
  const txns = useApi<Transaction[]>(`/api/finance/transactions?limit=500${category ? `&category=${encodeURIComponent(category)}` : ""}`);
  const refresh = () => {
    summary.reload();
    txns.reload();
  };

  return (
    <>
      <PageHead title="Finance" sub="Computed from imported bank transactions. Nothing is estimated here unless it says so." />
      <div className="stack">
        <Gate data={summary.data} error={summary.error} retry={summary.reload} what="Loading financial summary">
          {(s) => (s.has_data ? <Summary s={s} /> : <NoData s={s} />)}
        </Gate>

        <div className="grid">
          <div className="span-7">
            <ImportForm onImported={refresh} />
          </div>
          <div className="span-5">
            <OpeningBalanceForm onSaved={refresh} />
          </div>
        </div>

        <Card
          title="Transactions"
          sub="Newest first, up to 500."
          actions={
            summary.data?.by_category && summary.data.by_category.length > 0 ? (
              <label className="row small" style={{ gap: 6 }}>
                <span className="muted">Category</span>
                <select className="select" style={{ width: "auto" }} value={category} onChange={(e) => setCategory(e.target.value)}>
                  <option value="">All</option>
                  {summary.data.by_category.map((c) => (
                    <option key={c.category} value={c.category}>
                      {humanize(c.category)}
                    </option>
                  ))}
                </select>
              </label>
            ) : undefined
          }
          flush
        >
          <Gate data={txns.data} error={txns.error} retry={txns.reload} what="Loading transactions">
            {(rows) => (
              <Table
                dense
                rows={rows}
                rowKey={(t) => t.id}
                empty={<EmptyState title={category ? "No transactions in this category" : "No transactions yet — import a CSV"}>{category ? "Choose another category." : "Use the import form above with a CSV exported from your bank."}</EmptyState>}
                columns={[
                  { key: "d", header: "Date", render: (t) => <span className="nowrap">{dateOnly(t.date)}</span> },
                  { key: "desc", header: "Description", className: "cell-wide", render: (t) => t.description },
                  { key: "v", header: "Vendor", render: (t) => <span className="ink-2">{t.vendor ?? "—"}</span> },
                  {
                    key: "cat",
                    header: "Category",
                    render: (t) => (
                      <span className="row" style={{ gap: 6 }}>
                        <span className="nowrap">{t.category ? humanize(t.category) : "—"}</span>
                        {t.is_transfer && <Badge tone="gray" label="Transfer" />}
                        {t.is_revenue && <Badge tone="green" label="Revenue" />}
                      </span>
                    ),
                  },
                  { key: "st", header: "Status", render: (t) => <Badge value={t.status} /> },
                  {
                    key: "amt",
                    header: "Amount",
                    num: true,
                    render: (t) => <span style={{ color: t.amount_cents > 0 ? "var(--green)" : undefined }}>{cents(t.amount_cents)}</span>,
                  },
                ]}
              />
            )}
          </Gate>
        </Card>
      </div>
    </>
  );
}

function NoData({ s }: { s: FinanceSummary }) {
  return (
    <>
      <EmptyState title="No financial records yet">
        {s.note ?? "No transactions."} Revenue, expenses, burn, cash and runway are computed only from transactions you import; nothing is assumed. Import a CSV below, then set an opening balance to know cash and runway.
      </EmptyState>
      {s.ai_operating_cost && (
        <Card title="AI system operating cost" sub="What running the agents has cost so far. Estimated from list prices.">
          <Stats items={[{ label: "Estimated cost", value: usd(s.ai_operating_cost.usd), note: `${s.ai_operating_cost.calls} model calls` }]} />
        </Card>
      )}
    </>
  );
}

const RECON_LABELS: Record<string, string> = {
  net_cash_flow_equals_sum_of_records: "Net cash flow equals the sum of records",
  monthly_sums_to_total: "Monthly figures add up to the total",
  categories_sum_to_total_including_transfers: "Categories add up to the total, including transfers",
};

function Summary({ s }: { s: FinanceSummary }) {
  const monthly = s.monthly ?? [];
  const ai = s.ai;
  return (
    <div className="stack">
      <div className="row-between">
        <span className="small muted">
          {s.transactions} transactions from {dateOnly(s.period?.from)} to {dateOnly(s.period?.to)}
        </span>
        {s.reconciliation && (
          <span className="row small" style={{ gap: 6 }}>
            <span className="muted">Reconciliation</span>
            {s.reconciliation.ok ? <Badge tone="green" label="All checks pass" /> : <Badge tone="red" label="Mismatch found" />}
          </span>
        )}
      </div>

      <FinanceSnapshot totals={s.totals} burn={s.burn} cash={s.cash} runway={s.runway} />

      <Stats
        items={[
          {
            label: "Gross burn / month",
            value: s.burn?.gross_burn_monthly === null || s.burn?.gross_burn_monthly === undefined ? "unknown" : cents(s.burn.gross_burn_monthly),
            unknown: s.burn?.gross_burn_monthly === null || s.burn?.gross_burn_monthly === undefined,
            note: s.burn?.months?.length ? `Months: ${s.burn.months.map(monthLabel).join(", ")}` : s.burn?.note,
          },
          { label: "Other inflows", value: s.totals ? cents(s.totals.other_inflows.cents) : "unknown", note: "Refunds and non-revenue money in" },
          { label: "Net cash flow", value: s.totals ? cents(s.totals.net_cash_flow.cents) : "unknown", note: "Revenue + other inflows − expenses" },
          {
            label: "Gross margin",
            value: s.gross_margin?.gross_margin_pct === null || s.gross_margin?.gross_margin_pct === undefined ? "unknown" : `${s.gross_margin.gross_margin_pct}%`,
            unknown: s.gross_margin?.gross_margin_pct === null || s.gross_margin?.gross_margin_pct === undefined,
            note: s.gross_margin?.note ?? undefined,
          },
          { label: "Recurring / month", value: s.recurring?.display ?? "unknown", note: `${s.recurring?.items.length ?? 0} detected subscriptions` },
        ]}
      />

      {s.not_actual && s.not_actual.cents !== 0 && (
        <Callout tone="amber" title={`${s.not_actual.display} not counted`}>
          {s.not_actual.note}
        </Callout>
      )}

      {s.anomalies && s.anomalies.length > 0 && (
        <Card title="Unusual spending" sub="Flagged by rule, not by a model." flush>
          <Table
            dense
            rows={s.anomalies}
            rowKey={(a) => a.transaction_id}
            columns={[
              { key: "d", header: "Date", render: (a) => <span className="nowrap">{dateOnly(a.date)}</span> },
              { key: "desc", header: "Description", className: "cell-mid", render: (a) => a.description },
              { key: "amt", header: "Amount", num: true, render: (a) => <span style={{ color: "var(--amber)" }}>{a.amount}</span> },
              { key: "why", header: "Why flagged", className: "cell-wide", render: (a) => <span className="ink-2">{a.reason}</span> },
            ]}
          />
        </Card>
      )}

      <Card title="Revenue and expenses by month" sub="Calendar months of actual transactions. Transfers excluded.">
        {monthly.length === 0 ? (
          <EmptyState title="No actual transactions to chart">Pending and committed transactions are excluded from charts.</EmptyState>
        ) : (
          <BarChart
            label="Revenue and expenses by month"
            categories={monthly.map((m) => monthLabel(m.month))}
            series={[
              { name: "Revenue", color: "var(--series-1)", values: monthly.map((m) => m.revenue) },
              { name: "Expenses", color: "var(--series-2)", values: monthly.map((m) => m.expenses) },
            ]}
            format={(n) => compactCents(n)}
          />
        )}
      </Card>

      {ai && (
        <Card title="AI spend, two ways" sub="Bank records and the system's own usage meter measure different things; they are never added together.">
          <div className="stats">
            <div className="stat">
              <div className="stat-label">AI vendor spend (bank)</div>
              <div className="stat-value">{ai.vendor_spend_bank.display}</div>
              <div className="stat-note">Actual payments in the ai_tools category</div>
            </div>
            <div className="stat">
              <div className="stat-label">AI system operating cost (estimated)</div>
              <div className="stat-value">{usd(ai.system_operating_cost.usd)}</div>
              <div className="stat-note">
                {ai.system_operating_cost.calls} model calls, {ai.system_operating_cost.basis}
              </div>
            </div>
          </div>
        </Card>
      )}

      <div className="grid">
        <div className="span-6">
          <Card title="By category" flush>
            <Table
              dense
              rows={s.by_category ?? []}
              rowKey={(c) => c.category}
              empty={<EmptyState title="No categories">Categories are assigned on import.</EmptyState>}
              columns={[
                { key: "c", header: "Category", render: (c) => humanize(c.category) },
                { key: "n", header: "Count", num: true, render: (c) => c.count },
                { key: "t", header: "Net total", num: true, render: (c) => <span style={{ color: c.total_cents > 0 ? "var(--green)" : undefined }}>{c.total}</span> },
              ]}
            />
          </Card>
        </div>
        <div className="span-6 stack">
          <Card title="Major vendors" flush>
            <Table
              dense
              rows={s.major_vendors ?? []}
              rowKey={(v) => v.vendor}
              empty={<EmptyState title="No vendor spend">Vendors are derived from transaction descriptions.</EmptyState>}
              columns={[
                {
                  key: "v",
                  header: "Vendor",
                  render: (v) => (
                    <span className="row" style={{ gap: 6 }}>
                      {v.vendor}
                      {v.ai_provider && <Badge tone="accent" label="AI" />}
                    </span>
                  ),
                },
                { key: "c", header: "Charges", num: true, render: (v) => v.charges },
                { key: "s", header: "Spend", num: true, render: (v) => v.spend },
              ]}
            />
          </Card>
          <Card title="Recurring costs" sub={s.recurring ? `${s.recurring.display} per month` : undefined} flush>
            <Table
              dense
              rows={s.recurring?.items ?? []}
              rowKey={(r) => r.name + r.amount}
              empty={<EmptyState title="No recurring costs detected">A vendor charged a similar amount in two or more months is treated as a subscription.</EmptyState>}
              columns={[
                { key: "n", header: "Name", render: (r) => r.name },
                { key: "src", header: "Source", render: (r) => <span className="small muted">{humanize(r.source)}</span> },
                { key: "last", header: "Last charge", render: (r) => <span className="nowrap">{dateOnly(r.last_charge)}</span> },
                { key: "a", header: "Amount", num: true, render: (r) => r.amount },
              ]}
            />
          </Card>
        </div>
      </div>

      {s.reconciliation && (
        <Card title="Reconciliation" sub="Reported totals are recomputed from the underlying records.">
          <ul className="rows">
            {Object.entries(s.reconciliation.checks).map(([k, ok]) => (
              <li key={k} className="row-between">
                <span>{RECON_LABELS[k] ?? humanize(k)}</span>
                {ok ? <Badge tone="green" label="Pass" /> : <Badge tone="red" label="Fail" />}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function compactCents(c: number): string {
  const d = c / 100;
  if (Math.abs(d) >= 1000) return `$${(d / 1000).toFixed(Math.abs(d) >= 10000 ? 0 : 1)}k`;
  return `$${Math.round(d)}`;
}

function ImportForm({ onImported }: { onImported: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [account, setAccount] = useState("Primary");
  const [spendPositive, setSpendPositive] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const { busy, error, run, setError } = useAction();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setError(new Error("Choose a CSV file first."));
      return;
    }
    const fd = new FormData();
    fd.append("file", file);
    fd.append("account", account.trim() || "Primary");
    fd.append("spend_positive", spendPositive ? "true" : "false");
    const r = await run(() => api.post<ImportResult>("/api/finance/import", fd));
    if (r) {
      setResult(r);
      if (fileRef.current) fileRef.current.value = "";
      onImported();
    }
  }

  return (
    <Card title="Import transactions" sub="CSV with date, description and amount (or debit/credit) columns. Bad rows are rejected with a reason; duplicates are skipped.">
      <form className="form" onSubmit={submit}>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="csv-file">CSV file</label>
            <input id="csv-file" ref={fileRef} className="input" type="file" accept=".csv,text/csv" />
          </div>
          <div className="field">
            <label htmlFor="csv-account">Account name</label>
            <input id="csv-account" className="input" value={account} onChange={(e) => setAccount(e.target.value)} />
          </div>
        </div>
        <label className="check">
          <input type="checkbox" checked={spendPositive} onChange={(e) => setSpendPositive(e.target.checked)} />
          Spending is shown as positive numbers in this file
        </label>
        <div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Importing…" : "Import CSV"}
          </button>
        </div>
        <ErrorBox error={error} />
        {result && (
          <div className="stack-sm">
            <div className="stats">
              <div className="stat">
                <div className="stat-label">Accepted</div>
                <div className="stat-value" style={{ color: "var(--green)" }}>
                  {result.accepted}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Rejected</div>
                <div className="stat-value" style={result.rejected ? { color: "var(--red)" } : undefined}>
                  {result.rejected}
                </div>
              </div>
              <div className="stat">
                <div className="stat-label">Duplicates skipped</div>
                <div className="stat-value">{result.duplicates}</div>
              </div>
            </div>
            {result.errors.length > 0 && (
              <div className="panel" style={{ background: "var(--inset)" }}>
                <Table
                  dense
                  rows={result.errors}
                  rowKey={(e) => String(e.line)}
                  columns={[
                    { key: "l", header: "Line", num: true, render: (e) => e.line },
                    { key: "e", header: "Problem", render: (e) => <span style={{ color: "var(--red)" }}>{e.error}</span> },
                    { key: "r", header: "Row", className: "cell-wide", render: (e) => <span className="mono small ink-2">{Object.values(e.row).join(", ")}</span> },
                  ]}
                />
              </div>
            )}
          </div>
        )}
      </form>
    </Card>
  );
}

function OpeningBalanceForm({ onSaved }: { onSaved: () => void }) {
  const [account, setAccount] = useState("Primary");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [saved, setSaved] = useState(false);
  const { busy, error, run, setError } = useAction();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaved(false);
    if (!amount.trim() || !date) {
      setError(new Error("Enter the balance and the date it was true."));
      return;
    }
    const r = await run(() => api.post<{ ok: boolean }>("/api/finance/opening-balance", { account: account.trim() || "Primary", amount: amount.trim(), date }));
    if (r?.ok) {
      setSaved(true);
      onSaved();
    }
  }

  return (
    <Card title="Opening balance" sub="Cash and runway stay unknown until every account has one. Use the balance at the start of the day on that date.">
      <form className="form" onSubmit={submit}>
        <div className="field">
          <label htmlFor="ob-account">Account name</label>
          <input id="ob-account" className="input" value={account} onChange={(e) => setAccount(e.target.value)} />
        </div>
        <div className="form-grid">
          <div className="field">
            <label htmlFor="ob-amount">Balance</label>
            <input id="ob-amount" className="input" inputMode="decimal" placeholder="2,500.00" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="ob-date">As of</label>
            <input id="ob-date" className="input" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
        </div>
        <div>
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Save opening balance"}
          </button>
        </div>
        <ErrorBox error={error} />
        {saved && <Callout tone="green">Opening balance saved. Cash and runway are recomputed.</Callout>}
      </form>
    </Card>
  );
}
