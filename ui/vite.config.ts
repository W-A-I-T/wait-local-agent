import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { apiProxyRoutes } from "./src/lib/apiProxyRoutes";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://localhost:8788";

const apiProxyOptions = {
  target: apiProxyTarget,
  changeOrigin: true,
  bypass: (request: { headers: { accept?: string }; url?: string }) =>
    request.headers.accept?.includes("text/html") ? request.url : undefined
};

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      apiProxyRoutes.map((route) => [
        route,
        apiProxyOptions
      ])
    )
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./tests/setup.ts",
    exclude: ["**/node_modules/**", "**/dist/**", "**/.idea/**", "**/.git/**", "**/.cache/**", "e2e/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "lcov"],
      reportsDirectory: "./coverage",
      exclude: ["src/vite-env.d.ts", "src/main.tsx", "e2e/**"],
      thresholds: {
        statements: 75,
        branches: 65,
        functions: 70,
        lines: 75
      }
    }
  }
});
