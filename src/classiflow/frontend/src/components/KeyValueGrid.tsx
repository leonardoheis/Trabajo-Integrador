import { Fragment } from "react";

export default function KeyValueGrid({ pairs }: { pairs: [string, React.ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-3 text-base">
      {pairs.map(([label, value]) => (
        <Fragment key={label}>
          <dt className="pt-0.5 font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
            {label}
          </dt>
          <dd className="m-0 text-[var(--color-text)]">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}
