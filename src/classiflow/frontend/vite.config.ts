import type { IncomingMessage } from "node:http";
import type { ProxyOptions } from "vite";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The frontend has its own pages at /classification, /users, and /audit --
// identical paths to real backend endpoints (GET /classification/review-queue's
// prefix, GET /users, GET /audit). Vite's proxy matches by URL prefix alone, so a
// direct navigation/refresh on one of these frontend routes was being forwarded to
// the backend (which 404s or doesn't recognize the bare path) instead of falling
// through to the SPA's index.html. Every real API call from this app goes through
// apiFetch, which always attaches an Authorization header once signed in; a
// browser's own page load/refresh never does -- used here as the signal to
// distinguish "this is really an API call" from "this is a page load," since the
// URL shape alone can't tell them apart for these three paths.
function apiOnly(): ProxyOptions {
  return {
    target: "http://127.0.0.1:8000",
    bypass: (req: IncomingMessage) => (req.headers.authorization ? undefined : req.url),
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/pipeline": "http://127.0.0.1:8000",
      "/classification": apiOnly(),
      "/jobs": "http://127.0.0.1:8000",
      "/documents": "http://127.0.0.1:8000",
      "/users": apiOnly(),
      "/audit": apiOnly(),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
});
