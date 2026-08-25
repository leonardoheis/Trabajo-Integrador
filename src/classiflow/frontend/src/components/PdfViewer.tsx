import { useEffect, useMemo, useState } from "react";
import { Document, Page } from "react-pdf";
import "react-pdf/dist/esm/Page/TextLayer.css";
import "react-pdf/dist/esm/Page/AnnotationLayer.css";
import { apiFetch } from "../api/auth";

// <Document>'s file prop, given a bare URL, fetches it via pdf.js's own internal
// networking -- entirely bypassing apiFetch(). pdf.js itself supports an
// httpHeaders option for exactly this case, but react-pdf's own TypeScript types
// don't expose it (its Source type only allows { data }/{ range }/{ url }), so
// fetching the bytes ourselves through the same apiFetch wrapper every other
// request in this app already uses is the properly-typed fix, not a runtime-only
// escape hatch.
export default function PdfViewer({ fileUrl }: { fileUrl: string }) {
  const [numPages, setNumPages] = useState(0);
  const [data, setData] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(false);

    apiFetch(fileUrl)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`GET ${fileUrl} failed: ${response.status}`);
        }
        return response.arrayBuffer();
      })
      .then((buffer) => {
        if (!cancelled) {
          setData(buffer);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setError(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fileUrl]);

  // <Document>'s file prop is compared by reference, not content -- a fresh { data }
  // object literal on every render (e.g. any parent re-render unrelated to the PDF
  // itself, like a sibling tab switch) reads to react-pdf as "the file changed" and
  // reloads/reparses the whole document from scratch. Memoized on the underlying
  // ArrayBuffer's own identity, which only changes when a new fetch actually
  // completes, so it's stable across unrelated re-renders. Declared before any early
  // return so this hook always runs in the same order (Rules of Hooks).
  const file = useMemo(() => (data ? { data } : undefined), [data]);

  if (error) {
    return <p className="p-4 text-sm text-[var(--color-danger)]">Failed to load the document.</p>;
  }

  if (!file) {
    return <p className="p-4 text-sm text-[var(--color-text-muted)]">Loading document…</p>;
  }

  return (
    <div className="h-full overflow-y-auto bg-[var(--color-surface)] p-6">
      <Document
        file={file}
        onLoadSuccess={({ numPages: n }) => setNumPages(n)}
        className="flex flex-col items-center gap-4"
      >
        {Array.from({ length: numPages }, (_, i) => (
          <Page key={i} pageNumber={i + 1} width={480} className="shadow-lg" />
        ))}
      </Document>
    </div>
  );
}
