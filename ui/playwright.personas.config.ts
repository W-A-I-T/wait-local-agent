import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e/personas",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [["list"], ["html", { outputFolder: "persona-report", open: "never" }]],
  outputDir: "persona-results",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:18790",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: `${process.env.WAIT_BROWSER_PYTHON ?? "python"} ../scripts/browser_fixture_server.py`,
    url: "http://127.0.0.1:18790/healthz",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
