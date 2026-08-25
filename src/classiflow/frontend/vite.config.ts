import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/auth": "http://127.0.0.1:8000",
      "/pipeline": "http://127.0.0.1:8000",
      "/classification": "http://127.0.0.1:8000",
      "/jobs": "http://127.0.0.1:8000",
      "/documents": "http://127.0.0.1:8000",
      "/users": "http://127.0.0.1:8000",
      "/audit": "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/setupTests.ts",
  },
});
