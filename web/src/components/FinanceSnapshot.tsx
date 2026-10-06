import { cents, num } from "../format";
import type { Burn, Cash, FinanceTotals, Runway } from "../types";
import { Stats, type StatItem } from "./Card";

/** Revenue, expenses, net burn, cash, runway. Null values read "unknown" with the API's note. */
export function financeStats(totals: FinanceTotals | null | undefined, burn: Burn | null | undefined, cash: Cash | null | undefined, runway: Runway | null | undefined): StatItem[] {
  const netBurn = burn?.net_burn_monthly ?? null;
  const burnMonths = burn?.months_used ?? 0;
  return [
    { label: "Revenue", value: totals ? cents(totals.revenue.cents) : "unknown", unknown: !totals, note: "All imported months" },
    { label: "Expenses", value: totals ? cents(totals.expenses.cents) : "unknown", unknown: !totals, note: "Excludes transfers" },
    {
      label: "Net burn / month",
      value: netBurn === null ? "unknown" : cents(netBurn),
      unknown: netBurn === null,
      note: netBurn === null ? burn?.note ?? "No complete months yet." : netBurn <= 0 ? `Cash-flow positive, ${burnMonths} mo avg` : `Average of ${burnMonths} complete month${burnMonths === 1 ? "" : "s"}`,
    },
    {
      label: "Cash",
      value: cash?.cash_balance === null || cash?.cash_balance === undefined ? "unknown" : cents(cash.cash_balance),
      unknown: cash?.cash_balance === null || cash?.cash_balance === undefined,
      note: cash?.note ?? (cash?.cash_balance !== null && cash?.cash_balance !== undefined ? "From opening balances" : undefined),
    },
    {
      label: "Runway",
      value: runway?.runway_months === null || runway?.runway_months === undefined ? "unknown" : `${num(runway.runway_months, 1)} months`,
      unknown: runway?.runway_months === null || runway?.runway_months === undefined,
      note: runway?.note ?? undefined,
    },
  ];
}

export function FinanceSnapshot(props: { totals: FinanceTotals | null | undefined; burn: Burn | null | undefined; cash: Cash | null | undefined; runway: Runway | null | undefined }) {
  return <Stats items={financeStats(props.totals, props.burn, props.cash, props.runway)} />;
}
