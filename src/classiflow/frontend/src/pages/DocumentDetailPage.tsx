import { useState } from "react";
import { useParams } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchJobDetail, documentFileUrl } from "../api/documents";
import PdfViewer from "../components/PdfViewer";
import ReclassifyPanel from "../components/ReclassifyPanel";

type Tab = "extraction" | "enrichment" | "classification" | "audit";

const TABS: Tab[] = ["extraction", "enrichment", "classification", "audit"];

export default function DocumentDetailPage() {
  const { jobId } = useParams<{ jobId: string }>();
  const [tab, setTab] = useState<Tab>("classification");
  const queryClient = useQueryClient();

  const { data } = useQuery({
    queryKey: ["job-detail", jobId],
    queryFn: () => fetchJobDetail(jobId!),
    enabled: !!jobId,
  });

  if (!data) {
    return <p className="p-6">Loading...</p>;
  }

  return (
    <div className="flex h-screen">
      <div className="w-1/2 border-r border-[var(--color-border)]">
        <PdfViewer fileUrl={documentFileUrl(jobId!)} />
      </div>
      <div className="w-1/2 overflow-y-auto p-4">
        <div className="mb-4 flex gap-2">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`rounded-md px-3 py-1 text-sm ${
                tab === t ? "bg-[var(--color-accent)] text-white" : "text-[var(--color-text-muted)]"
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {tab === "extraction" && (
          <pre className="whitespace-pre-wrap text-sm">
            {data.enriched?.rawText ?? "No extraction data"}
          </pre>
        )}

        {tab === "enrichment" && (
          <pre className="whitespace-pre-wrap text-sm">
            {JSON.stringify(data.enriched?.entities, null, 2)}
          </pre>
        )}

        {tab === "classification" && (
          <div>
            <pre className="whitespace-pre-wrap text-sm">
              {JSON.stringify(data.classification, null, 2)}
            </pre>
            {data.classification?.reviewRoute === "human_review" && (
              <div className="mt-4">
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

        {tab === "audit" && (
          <div className="flex flex-col gap-2">
            {data.audit.map((entry, i) => (
              <div key={i} className="text-sm">
                <span className="font-semibold">{entry.node}</span> — {entry.event} —{" "}
                {new Date(entry.timestamp).toLocaleString()}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
