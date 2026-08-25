import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { pdfjs } from "react-pdf";
import App from "./App";
import "./index.css";

pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
