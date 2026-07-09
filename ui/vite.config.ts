import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8788";
const apiProxyRoutes = [
  "/health",
  "/auth",
  "/tickets",
  "/approval-requests",
  "/audit",
  "/audit-events",
  "/event-history",
  "/events",
  "/knowledge",
  "/workflows",
  "/workflow-runs",
  "/connectors",
  "/scheduled-jobs",
  "/update-status",
  "/founder",
  "/packs",
  "/settings",
  "/secrets"
];

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      apiProxyRoutes.map((route) => [
        route,
        {
          target: apiProxyTarget,
          changeOrigin: true
        }
      ])
    )
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./tests/setup.ts"
  }
});
