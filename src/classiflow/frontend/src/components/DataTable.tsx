import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
}

export default function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
}) {
  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-[var(--color-border)] text-left text-[var(--color-text-muted)]">
          {columns.map((col) => (
            <th key={col.header} className="p-2">
              {col.header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr
            key={rowKey(row)}
            onClick={() => onRowClick?.(row)}
            className={`border-b border-[var(--color-border)] ${onRowClick ? "cursor-pointer hover:bg-[var(--color-surface)]" : ""}`}
          >
            {columns.map((col) => (
              <td key={col.header} className="p-2">
                {col.render(row)}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
