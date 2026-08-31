import { Fragment, useState } from "react";
import { useParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJobDetail, documentFileUrl } from "../api/documents";
import { fetchDocumentKb, indexDocument } from "../api/knowledge";
import type { TimelineEntry } from "../api/jobs";
import PdfViewer from "../components/PdfViewer";
import ReclassifyPanel from "../components/ReclassifyPanel";
import StepTimeline from "../components/StepTimeline";

type Tab = "extraction" | "enrichment" | "classification" | "knowledge" | "audit";

const TABS: Tab[] = ["extraction", "enrichment", "classification", "knowledge", "audit"];

function ConfidenceBar({ value }: { value: number }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-[5px] w-24 overflow-hidden rounded-full bg-[var(--color-border-subtle)]">
        <div
          className="h-full bg-[var(--color-success)]"
          style={{ width: `${Math.round(value * 100)}%` }}
        />
      </div>
      <span className="font-mono text-base text-[var(--color-text-muted)]">{value.toFixed(2)}</span>
    </div>
  );
}

function KeyValueGrid({ pairs }: { pairs: [string, React.ReactNode][] }) {
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

function MoreDetails({ pairs }: { pairs: [string, React.ReactNode][] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-6 border-t border-[var(--color-border-subtle)] pt-4">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)] hover:text-[var(--color-text-muted)]"
      >
        <span className={`transition-transform duration-150 ${open ? "rotate-90" : ""}`}>▸</span>
        More details
      </button>
      {open && (
        <div className="mt-4 transition-all duration-150">
          <KeyValueGrid pairs={pairs} />
        </div>
      )}
    </div>
  );
}

export default function DocumentDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [tab, setTab] = useState<Tab>("classification");
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["job-detail", jobId],
    queryFn: () => fetchJobDetail(jobId!),
    enabled: !!jobId,
  });

  const { data: kbData } = useQuery({
    queryKey: ["document-kb", jobId],
    queryFn: () => fetchDocumentKb(jobId!),
    enabled: !!jobId,
  });

  const indexMutation = useMutation({
    mutationFn: () => indexDocument(jobId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["document-kb", jobId] }),
  });

  if (!data) {
    return <p className="p-6 text-[var(--color-text-muted)]">Loading...</p>;
  }

  const auditEntries: TimelineEntry[] = data.audit.map((a) => ({
    node: a.node,
    status: a.event,
    passed: null,
    detail: a.detail,
    timestamp: a.timestamp,
    durationMs: a.durationMs,
  }));

  return (
    <div className="flex h-full">
      <div className="w-1/2 border-r border-[var(--color-border)]">
        <PdfViewer fileUrl={documentFileUrl(jobId!)} />
      </div>
      <div className="w-1/2 overflow-y-auto p-6">
        <div className="mb-6 flex gap-1 border-b border-[var(--color-border-subtle)]">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-3 py-2 text-base capitalize transition-colors duration-150 ${
                tab === t
                  ? "border-b-2 border-[var(--color-accent)] font-semibold text-[var(--color-text)]"
                  : "text-[var(--color-text-faint)] hover:text-[var(--color-text-muted)]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "extraction" && (
          <pre className="whitespace-pre-wrap font-serif text-base text-[var(--color-text)]">
            {data.enriched?.rawText ?? "No extraction data"}
          </pre>
        )}

        {tab === "enrichment" && data.enriched && (
          <KeyValueGrid
            pairs={Object.entries(data.enriched.entities).map(([key, value]) => [
              key,
              String(value),
            ])}
          />
        )}
        {tab === "enrichment" && !data.enriched && (
          <p className="text-base text-[var(--color-text-muted)]">No enrichment data</p>
        )}

        {tab === "classification" && data.classification && (
          <div>
            <KeyValueGrid
              pairs={[
                ["Label", data.classification.label ?? "—"],
                ["Confidence", <ConfidenceBar key="conf" value={data.classification.confidence} />],
                [
                  "Review route",
                  <span
                    key="route"
                    className="font-mono text-sm uppercase text-[var(--color-warning)]"
                  >
                    {data.classification.reviewRoute}
                  </span>,
                ],
                [
                  "Second opinion",
                  data.classification.secondOpinionLabel
                    ? `${data.classification.secondOpinionLabel} · ${data.classification.classifierDisagreement ? "disagrees" : "agrees"}`
                    : "—",
                ],
                [
                  "Smells",
                  data.classification.smells.length > 0 ? (
                    <span key="smells" className="flex flex-wrap gap-1.5">
                      {data.classification.smells.map((s) => (
                        <span
                          key={s}
                          className="rounded bg-[var(--color-border-subtle)] px-2 py-0.5 font-mono text-[10.5px] text-[var(--color-warning)]"
                        >
                          {s}
                        </span>
                      ))}
                    </span>
                  ) : (
                    "none"
                  ),
                ],
              ]}
            />
            {data.classification.judgeReasoning && (
              <>
                <p className="mb-2 mt-6 font-mono text-[11px] uppercase tracking-wide text-[var(--color-text-faint)]">
                  Judge reasoning
                </p>
                <p className="text-base leading-relaxed text-[var(--color-text-muted)]">
                  {data.classification.judgeReasoning}
                </p>
              </>
            )}
            <MoreDetails
              pairs={[
                [
                  "All scores",
                  <span key="all-scores" className="block whitespace-pre-wrap font-mono text-sm">
                    {Object.entries(data.classification.allScores)
                      .map(([label, score]) => `${label}: ${score}`)
                      .join("\n")}
                  </span>,
                ],
                ["Risk score", String(data.classification.riskScore)],
                ["Smell review suggested", data.classification.smellReviewSuggested ? "Yes" : "No"],
                ["Judged by LLM", data.classification.judgedByLlm ? "Yes" : "No"],
                ["Judge final label", data.classification.judgeFinalLabel ?? "—"],
                ["Foreign municipality", data.classification.foreignMunicipality ?? "—"],
                ["Human overridden", data.classification.humanOverridden ? "Yes" : "No"],
                ["Stored path", data.classification.storedPath ?? "—"],
                [
                  "SVM agrees with prediction",
                  data.classification.svmAgreesWithPrediction ? "Yes" : "No",
                ],
                [
                  "SVM scores",
                  <span key="svm-scores" className="block whitespace-pre-wrap font-mono text-sm">
                    {Object.entries(data.classification.svmScores)
                      .map(([label, score]) => `${label}: ${score}`)
                      .join("\n") || "—"}
                  </span>,
                ],
                [
                  "OOD metrics",
                  <span key="ood-metrics" className="block whitespace-pre-wrap font-mono text-sm">
                    {data.classification.oodMetrics
                      ? JSON.stringify(data.classification.oodMetrics, null, 2)
                      : "—"}
                  </span>,
                ],
              ]}
            />

            {data.classification.reviewRoute === "human_review" && (
              <div className="mt-6">
                <ReclassifyPanel
                  jobId={jobId!}
                  onSubmitted={() =>
                    queryClient.invalidateQueries({ queryKey: ["job-detail", jobId] })
                  }
                />
              </div>
            )}
          </div>
        )}
        {tab === "classification" && !data.classification && (
          <p className="text-base text-[var(--color-text-muted)]">No classification data</p>
        )}

        {tab === "knowledge" && kbData?.documentKb && (
          <KeyValueGrid
            pairs={[
              ["Filename", kbData.documentKb.filename],
              [
                "SHA-256",
                <span key="sha" className="font-mono text-sm">
                  {kbData.documentKb.sha256}
                </span>,
              ],
              ["Doc type", kbData.documentKb.docType ?? "—"],
              ["Number", kbData.documentKb.number ?? "—"],
              ["Year", kbData.documentKb.year ?? "—"],
              ["Chunk count", String(kbData.documentKb.chunkCount)],
              ["Indexed at", new Date(kbData.documentKb.indexedAt).toLocaleString()],
            ]}
          />
        )}
        {tab === "knowledge" &&
          !kbData?.documentKb &&
          data.classification?.reviewRoute === "accept" && (
            <div>
              <p className="mb-3 text-base text-[var(--color-text-muted)]">Not indexed yet</p>
              <button
                onClick={() => indexMutation.mutate()}
                disabled={indexMutation.isPending}
                className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-2 text-base font-semibold text-[var(--color-accent)] disabled:opacity-50"
              >
                {indexMutation.isPending ? "Indexing…" : "Index into Knowledge Base"}
              </button>
              {indexMutation.isError && (
                <p className="mt-2 text-base text-[var(--color-danger)]">
                  Indexing failed. Try again.
                </p>
              )}
            </div>
          )}
        {tab === "knowledge" &&
          !kbData?.documentKb &&
          data.classification?.reviewRoute !== "accept" && (
            <p className="text-base text-[var(--color-text-muted)]">
              Document must be accepted before it can be indexed
            </p>
          )}

        {tab === "audit" && <StepTimeline entries={auditEntries} mode="expanded" />}
      </div>
    </div>
  );
}
