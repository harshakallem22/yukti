import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // Proxying keeps the browser same-origin in dev, so SSE and fetch need no
    // CORS preflight and the API's origin allowlist stays strict.
    proxy: { "/api": { target: "http://127.0.0.1:8010", changeOrigin: true } },
  },
  test: { environment: "jsdom", globals: true, setupFiles: "./src/test-setup.ts" },
});
