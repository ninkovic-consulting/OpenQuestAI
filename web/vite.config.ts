import { defineConfig } from "vitest/config";

// In development the page talks to a running daemon through this proxy. The
// daemon refuses foreign origins, so the proxy presents the daemon's own.
const daemon = process.env["VISION_DAEMON"] ?? "http://127.0.0.1:7341";

// Two pages share the modules: the house, and the Mac app's floating widget.
const pages = { main: "index.html", widget: "widget.html" };

export default defineConfig({
  base: "./",
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 1200, rolldownOptions: { input: pages } },
  server: {
    proxy: {
      "/api": { target: daemon, headers: { origin: daemon } },
      "/ws": { target: daemon.replace(/^http/, "ws"), ws: true, headers: { origin: daemon } },
    },
  },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
