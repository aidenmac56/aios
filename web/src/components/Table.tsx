import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  num?: boolean;
  className?: string;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  dense,
  selectedKey,
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  dense?: boolean;
  selectedKey?: string | null;
  caption?: string;
}) {
  if (rows.length === 0 && empty) return <>{empty}</>;
  return (
    <div className="table-wrap">
      <table className={dense ? "table table-dense" : "table"}>
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={[c.num ? "num" : "", c.className ?? ""].join(" ").trim() || undefined} scope="col">
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const k = rowKey(r);
            const cls = [onRowClick ? "clickable" : "", selectedKey === k ? "selected" : ""].join(" ").trim() || undefined;
            return (
              <tr
                key={k}
                className={cls}
                onClick={onRowClick ? () => onRowClick(r) : undefined}
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter") onRowClick(r);
                      }
                    : undefined
                }
                tabIndex={onRowClick ? 0 : undefined}
              >
                {columns.map((c) => (
                  <td key={c.key} className={[c.num ? "num" : "", c.className ?? ""].join(" ").trim() || undefined}>
                    {c.render(r)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
