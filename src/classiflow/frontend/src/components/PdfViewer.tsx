import { useState } from "react";
import { Document, Page } from "react-pdf";

export default function PdfViewer({ fileUrl }: { fileUrl: string }) {
  const [numPages, setNumPages] = useState(0);

  return (
    <div className="overflow-y-auto">
      <Document file={fileUrl} onLoadSuccess={({ numPages: n }) => setNumPages(n)}>
        {Array.from({ length: numPages }, (_, i) => (
          <Page key={i} pageNumber={i + 1} width={500} />
        ))}
      </Document>
    </div>
  );
}
