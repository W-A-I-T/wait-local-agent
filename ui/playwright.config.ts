import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? "github" : "line",
  use: {
    baseURL: process.env.WAIT_BROWSER_UI_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"]
  }
});
