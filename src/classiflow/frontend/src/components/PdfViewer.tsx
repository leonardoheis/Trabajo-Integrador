import { useEffect, useMemo, useRef, useState } from "react";
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

const BASE_WIDTH = 480;
const ZOOM_STEP = 0.25;
const MIN_ZOOM = 0.5;
const MAX_ZOOM = 3;

export default function PdfViewer({ fileUrl }: { fileUrl: string }) {
  const [numPages, setNumPages] = useState(0);
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [fitToWidth, setFitToWidth] = useState(false);
  const [paneWidth, setPaneWidth] = useState(BASE_WIDTH);
  const [data, setData] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState(false);
  const paneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(false);
    setPageNumber(1);

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

  // Only measured while fitToWidth is on -- a plain resize listener is enough since
  // the sidebar/pane layout only changes via window resize, not element-level content
  // shifts that would need a ResizeObserver.
  useEffect(() => {
    if (!fitToWidth) {
      return;
    }
    function measure(): void {
      if (paneRef.current) {
        setPaneWidth(paneRef.current.clientWidth - 32); // minus the pane's own padding
      }
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [fitToWidth]);

  // <Document>'s file prop is compared by reference, not content -- a fresh { data }
  // object literal on every render (e.g. any parent re-render unrelated to the PDF
  // itself, like a sibling tab switch) reads to react-pdf as "the file changed" and
  // reloads/reparses the whole document from scratch. Memoized on the underlying
  // ArrayBuffer's own identity, which only changes when a new fetch actually
  // completes, so it's stable across unrelated re-renders. Declared before any early
  // return so this hook always runs in the same order (Rules of Hooks).
  const file = useMemo(() => (data ? { data } : undefined), [data]);

  if (error) {
    return <p className="p-4 text-base text-[var(--color-danger)]">Failed to load the document.</p>;
  }

  if (!file) {
    return <p className="p-4 text-base text-[var(--color-text-muted)]">Loading document…</p>;
  }

  const width = fitToWidth ? paneWidth : BASE_WIDTH * zoom;

  return (
    <div className="flex h-full flex-col bg-[var(--color-surface)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--color-border)] px-4 py-2 font-mono text-sm text-[var(--color-text-muted)]">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setPageNumber((p) => Math.max(1, p - 1))}
            disabled={pageNumber <= 1}
            className="rounded border border-[var(--color-border)] px-2 py-0.5 disabled:opacity-40"
          >
            ‹ Prev
          </button>
          <span>
            Page {pageNumber} / {numPages || 1}
          </span>
          <button
            onClick={() => setPageNumber((p) => Math.min(numPages, p + 1))}
            disabled={pageNumber >= numPages}
            className="rounded border border-[var(--color-border)] px-2 py-0.5 disabled:opacity-40"
          >
            Next ›
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              setFitToWidth(false);
              setZoom((z) => Math.max(MIN_ZOOM, z - ZOOM_STEP));
            }}
            disabled={fitToWidth || zoom <= MIN_ZOOM}
            className="rounded border border-[var(--color-border)] px-2 py-0.5 disabled:opacity-40"
          >
            −
          </button>
          <span>{fitToWidth ? "Fit" : `${Math.round(zoom * 100)}%`}</span>
          <button
            onClick={() => {
              setFitToWidth(false);
              setZoom((z) => Math.min(MAX_ZOOM, z + ZOOM_STEP));
            }}
            disabled={fitToWidth || zoom >= MAX_ZOOM}
            className="rounded border border-[var(--color-border)] px-2 py-0.5 disabled:opacity-40"
          >
            +
          </button>
          <button
            onClick={() => setFitToWidth((f) => !f)}
            className={`rounded border px-2 py-0.5 ${
              fitToWidth
                ? "border-[var(--color-accent)] text-[var(--color-accent)]"
                : "border-[var(--color-border)]"
            }`}
          >
            Fit width
          </button>
        </div>
      </div>
      <div ref={paneRef} className="flex-1 overflow-y-auto p-6">
        <Document
          file={file}
          onLoadSuccess={({ numPages: n }) => setNumPages(n)}
          className="flex flex-col items-center"
        >
          <Page pageNumber={pageNumber} width={width} className="shadow-lg" />
        </Document>
      </div>
    </div>
  );
}
