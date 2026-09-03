import { useQuery } from "@tanstack/react-query";
import { fetchAccuracyMetrics, type AccuracyReport, type CategoryMetrics } from "../api/metrics";

function Kpi({
  label,
  value,
  detail,
  emphasis = false,
}: {
  label: string;
  value: string;
  detail?: string;
  emphasis?: boolean;
}) {
  return (
    <div
      className={`rounded-md border px-4 py-3 ${
        emphasis
          ? "border-[var(--color-accent)] bg-[var(--color-accent-subtle)]"
          : "border-[var(--color-border)] bg-[var(--color-surface)]"
      }`}
    >
      <p className="font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-[var(--color-text)]">{value}</p>
      {detail && <p className="mt-0.5 text-sm text-[var(--color-text-muted)]">{detail}</p>}
    </div>
  );
}

// The accuracy rates below only count classified documents, so the drop from "ingested"
// needs accounting for -- otherwise a reader comparing this page against the
// Classification table sees a smaller number here and assumes documents went missing.
function Funnel({ report }: { report: AccuracyReport }) {
  // ?? {} so a server still running an older build (no funnel fields) degrades to a
  // plain count instead of crashing the whole page on Object.entries(undefined).
  const statuses = Object.entries(report.neverClassifiedByStatus ?? {});
  return (
    <div className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-4 py-2 font-mono text-sm">
      <span className="text-[var(--color-text)]">
        {report.totalJobs ?? report.totalClassified} ingested
      </span>
      {report.neverClassified > 0 && (
        <>
          <span className="text-[var(--color-text-faint)]">−</span>
          <span className="text-[var(--color-text-muted)]">
            {report.neverClassified} never classified
            {statuses.length > 0 && (
              <span className="text-[var(--color-text-faint)]">
                {" ("}
                {statuses.map(([status, count]) => `${status} ${count}`).join(", ")}
                {")"}
              </span>
            )}
          </span>
        </>
      )}
      <span className="text-[var(--color-text-faint)]">=</span>
      <span className="font-semibold text-[var(--color-text)]">
        {report.totalClassified} classified
      </span>
      <span className="ml-1 text-[var(--color-text-faint)]">
        · rejected duplicates and extraction failures are not classification errors, so they are
        excluded from the rates below
      </span>
    </div>
  );
}

// Recall and precision share a scale, so one colour ramp serves both. Below 0.7 is where
// a category stops being trustworthy on its own.
function rateColor(rate: number): string {
  if (rate >= 0.9) return "var(--color-status-pass)";
  if (rate >= 0.7) return "var(--color-status-review)";
  return "var(--color-status-escalate)";
}

function RateCell({ rate, support }: { rate: number; support: number }) {
  if (support === 0) return <span className="text-[var(--color-text-faint)]">—</span>;
  return (
    <span className="font-mono tabular-nums" style={{ color: rateColor(rate) }}>
      {rate.toFixed(2)}
    </span>
  );
}

function CategoryTable({ rows, unevaluated }: { rows: CategoryMetrics[]; unevaluated: string[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-[var(--color-border)]">
      <table className="w-full border-collapse text-base">
        <thead>
          <tr className="border-b border-[var(--color-border)] bg-[var(--color-surface)]">
            <th className="px-3 py-2 text-left font-semibold text-[var(--color-text)]">Category</th>
            <th className="px-3 py-2 text-right font-semibold text-[var(--color-text)]">Support</th>
            <th className="px-3 py-2 text-right font-semibold text-[var(--color-text)]">Recall</th>
            <th className="px-3 py-2 text-right font-semibold text-[var(--color-text)]">
              Precision
            </th>
            <th className="px-3 py-2 text-right font-semibold text-[var(--color-text)]">F1</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.category} className="border-b border-[var(--color-border-subtle)]">
              <td className="px-3 py-2 font-mono text-sm text-[var(--color-text)]">
                {row.category}
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums text-[var(--color-text-muted)]">
                {row.support}
              </td>
              <td className="px-3 py-2 text-right">
                <RateCell rate={row.recall} support={row.support} />
              </td>
              <td className="px-3 py-2 text-right">
                <RateCell rate={row.precision} support={row.support} />
              </td>
              <td className="px-3 py-2 text-right">
                <RateCell rate={row.f1} support={row.support} />
              </td>
            </tr>
          ))}
          {unevaluated.map((category) => (
            <tr key={category} className="border-b border-[var(--color-border-subtle)]">
              <td className="px-3 py-2 font-mono text-sm text-[var(--color-text-faint)]">
                {category}
              </td>
              <td className="px-3 py-2 text-right font-mono text-[var(--color-text-faint)]">0</td>
              <td
                colSpan={3}
                className="px-3 py-2 text-right text-sm text-[var(--color-text-faint)]"
              >
                no labelled examples
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConfusionMatrix({ report }: { report: AccuracyReport }) {
  const categories = report.perCategory.map((c) => c.category);
  const max = Math.max(
    1,
    ...categories.flatMap((e) =>
      categories.map((p) => (e === p ? 0 : (report.confusion[e]?.[p] ?? 0))),
    ),
  );

  return (
    <div className="overflow-x-auto rounded-md border border-[var(--color-border)] p-3">
      <table className="border-collapse font-mono text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left text-[var(--color-text-faint)]">expected \ got</th>
            {categories.map((c) => (
              <th
                key={c}
                className="px-2 py-1 text-[var(--color-text-faint)]"
                title={c}
                style={{ writingMode: "vertical-rl" }}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {categories.map((expected) => (
            <tr key={expected}>
              <td className="whitespace-nowrap px-2 py-1 text-[var(--color-text-muted)]">
                {expected}
              </td>
              {categories.map((predicted) => {
                const count = report.confusion[expected]?.[predicted] ?? 0;
                const onDiagonal = expected === predicted;
                return (
                  <td
                    key={predicted}
                    className="px-2 py-1 text-center tabular-nums"
                    style={{
                      background: count
                        ? onDiagonal
                          ? "var(--color-accent-subtle)"
                          : `color-mix(in srgb, var(--color-status-escalate) ${(count / max) * 60}%, transparent)`
                        : "transparent",
                      color: count ? "var(--color-text)" : "var(--color-text-faint)",
                    }}
                  >
                    {count || "·"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MetricsPage() {
  const { data: report, isError } = useQuery({
    queryKey: ["accuracy-metrics"],
    queryFn: fetchAccuracyMetrics,
  });

  if (isError) {
    return <p className="p-6 text-[var(--color-danger)]">Could not load metrics.</p>;
  }
  if (!report) {
    return <p className="p-6 text-[var(--color-text-muted)]">Loading…</p>;
  }

  const uncaught = report.misses.filter((m) => !m.caughtBySafetyNet);

  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="mb-1 text-2xl font-bold text-[var(--color-text)]">Metrics</h1>
      <p className="mb-4 text-base text-[var(--color-text-muted)]">
        Measured over {report.labelled} of {report.totalClassified} classified documents — those
        with a ground-truth label.
      </p>

      <Funnel report={report} />

      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <Kpi
          label="Strict accuracy"
          value={`${(report.strictAccuracy * 100).toFixed(1)}%`}
          detail={`${report.correct} of ${report.labelled} correct`}
        />
        <Kpi
          label="Safeguarded"
          value={`${(report.safeguardedAccuracy * 100).toFixed(1)}%`}
          detail="correct, or sent to review"
          emphasis
        />
        <Kpi
          label="Wrong, escalated"
          value={String(report.wrongCaught)}
          detail="caught before filing"
        />
        <Kpi
          label="Wrong, filed"
          value={String(report.wrongUncaught)}
          detail="reached storage unreviewed"
        />
      </div>

      <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        Per category
      </h2>
      <div className="mb-6">
        <CategoryTable rows={report.perCategory} unevaluated={report.unevaluatedCategories} />
      </div>

      <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-text-faint)]">
        Confusion — rows are the truth, columns what the model said
      </h2>
      <div className="mb-6">
        <ConfusionMatrix report={report} />
      </div>

      {uncaught.length > 0 && (
        <>
          <h2 className="mb-2 font-mono text-[11px] uppercase tracking-wider text-[var(--color-danger)]">
            Wrong labels filed without review — {uncaught.length}
          </h2>
          <div className="flex flex-col gap-2">
            {uncaught.map((miss) => (
              <div
                key={miss.jobId}
                className="rounded-md border border-[var(--color-danger)] bg-[var(--color-surface)] px-3 py-2"
              >
                <p className="font-mono text-sm text-[var(--color-text)]">{miss.filename}</p>
                <p className="text-sm text-[var(--color-text-muted)]">
                  expected <span className="font-mono">{miss.expected}</span>, got{" "}
                  <span className="font-mono">{miss.predicted}</span>
                </p>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
