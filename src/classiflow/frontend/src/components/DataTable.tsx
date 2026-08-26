import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  // Opaque sort key this column represents -- interpreted by the caller (e.g. a
  // SortField union), not by DataTable itself. Columns without one aren't sortable.
  sortKey?: string;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  sort,
  onSortChange,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  sort?: SortState;
  onSortChange?: (key: string) => void;
}) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-[var(--color-border)] text-left">
          {columns.map((col) => {
            const isActive = col.sortKey !== undefined && sort?.key === col.sortKey;
            return (
              <th
                key={col.header}
                onClick={() => col.sortKey && onSortChange?.(col.sortKey)}
                className={`p-3 font-mono text-[10.5px] uppercase tracking-wider text-[var(--color-text-faint)] ${
                  col.sortKey ? "cursor-pointer select-none hover:text-[var(--color-text-muted)]" : ""
                }`}
              >
                {col.header}
                {isActive && <span className="ml-1">{sort?.dir === "asc" ? "▲" : "▼"}</span>}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={`border-b border-[var(--color-border-subtle)] text-[var(--color-text)] transition-colors duration-150 ${onRowClick ? "cursor-pointer hover:bg-[var(--color-surface)]" : ""}`}
          >
            {columns.map((col) => (
              <td key={col.header} className="p-3">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
