import { randomUUID } from "node:crypto";
import { stat } from "node:fs/promises";
import { expect, test, type Page } from "@playwright/test";

const token = process.env.WAIT_BROWSER_TOKEN ?? "integration-admin-token";
const apiUrl = process.env.WAIT_BROWSER_API_URL ?? "http://127.0.0.1:8788";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("wait-local-agent-onboarding-dismissed", "1");
  });
});

async function signIn(page: Page): Promise<void> {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in to the appliance", exact: true })).toBeVisible();
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "WAIT AI Solutions Architect", exact: true })).toBeVisible();
}

async function apiJson(
  page: Page,
  path: string,
  method = "GET",
  data?: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const response = await page.request.fetch(`${apiUrl}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}` },
    data,
  });
  expect(response.ok(), `${method} ${path}`).toBeTruthy();
  return await response.json() as Record<string, unknown>;
}

test("shows the local sign-in screen without a stored credential", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.reload();

  await expect(page.getByRole("heading", { name: "Sign in to the appliance", exact: true })).toBeVisible();
  await expect(page.getByLabel("Access token")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign in", exact: true })).toBeVisible();
});

test("completes the safe local setup journey and exercises primary UI surfaces", async ({ page }, testInfo) => {
  await signIn(page);

  const fixtureSuffix = `${testInfo.retry}-${testInfo.repeatEachIndex}-${randomUUID()}`;
  const clientId = `browser-smoke-${fixtureSuffix}`;
  const clientName = `Browser Smoke Client ${fixtureSuffix}`;
  const connectorName = `Browser Smoke Connector ${fixtureSuffix}`;
  const externalCompanyId = `browser-external-company-${fixtureSuffix}`;
  const externalCompanyName = `Browser Smoke Company ${fixtureSuffix}`;

  const routes = [
    ["/", "Operations Overview"],
    ["/clients", "Clients"],
    ["/client-discovery", "Client discovery"],
    ["/connectors", "Connectors"],
    ["/integrations/connector-instances", "Connector Instances"],
    ["/workflows", "Workflows"],
    ["/approvals", "Approval Queue"],
    ["/activity/runs", "Runs"],
    ["/consultant", "Solutions Architect"],
    ["/consultant/solution-delivery", "Solution delivery"],
    ["/settings", "Admin Settings"]
  ] as const;

  for (const [path, heading] of routes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }

  await page.goto("/connectors");
  await expect(page.getByRole("button", { name: "Browse data", exact: true })).toBeVisible();
  await expect(page.locator(".connector-card").first()).toBeVisible();

  await page.goto("/clients");
  await page.getByRole("button", { name: "New client" }).click();
  await page.getByLabel("Client ID").fill(clientId);
  await page.getByLabel("Name").fill(clientName);
  await page.getByRole("button", { name: "Create client" }).click();
  await expect(page.getByRole("status")).toContainText("Client created.");

  await page.goto("/integrations/connector-instances");
  await page.getByLabel("Provider").selectOption("halopsa");
  await page.getByLabel("Display name").fill(connectorName);
  await page.getByLabel("WAIT client (optional)").selectOption(clientId);
  await page.getByRole("button", { name: "Continue to credentials", exact: true }).click();
  await page.getByLabel("Service address").fill("https://provider.invalid");
  await page.getByLabel("Client ID", { exact: true }).fill("browser-client-id");
  await page.getByLabel("Client secret").fill("browser-client-secret");
  await page.getByLabel("Tenant").fill("browser-tenant");
  await page.getByRole("button", { name: "Continue to verify and map", exact: true }).click();
  await page.getByRole("button", { name: "Connect system" }).click();
  await expect(page.getByRole("status")).toContainText(`Connected ${connectorName}`);
  await page.goto("/integrations/connector-instances");
  await page.getByRole("button", { name: connectorName }).click();

  await page.getByLabel("External company ID").fill(externalCompanyId);
  await page.getByLabel("External company name (optional)").fill(externalCompanyName);
  await page.locator("#mapping-wait-client").selectOption(clientId);
  await expect(page.getByRole("button", { name: "Create mapping" })).toBeEnabled();
  await page.getByRole("button", { name: "Create mapping" }).click();
  await expect(page.getByText("Mapping created.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("External company mappings").getByText(connectorName, { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Verify" })).toBeVisible();
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("Mapping verified.", { exact: true })).toBeVisible();

  await page.goto("/?onboarding=1&step=2");
  await expect(page.getByRole("link", { name: "Open mapping verification" })).toBeVisible();

  await page.goto("/");
  await expect(page.getByText("Setup complete")).toBeVisible();

  await page.goto("/playbooks");
  await page.locator("#app-client-selector").selectOption(clientId);
  const qbr = page.locator("article").filter({ hasText: "Quarterly Business Review" });
  await expect(qbr).toBeVisible();
  await qbr.getByLabel("Period start").fill("2026-01-01");
  await qbr.getByLabel("Period end").fill("2026-03-31");
  await expect(qbr.getByRole("button", { name: "Preview" })).toBeEnabled();
  await qbr.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByRole("status")).toContainText("Preview ready for Quarterly Business Review.");

  await page.goto("/integrations/mcp");
  await expect(page.getByRole("heading", { name: "MCP server", exact: true })).toBeVisible();
  await expect(page.getByText("Published tool catalog")).toBeVisible();
});

test("diagnostics shows the local support boundary and correlation inventory", async ({ page }) => {
  await signIn(page);

  const summary = await apiJson(page, "/diagnostics/summary");
  expect(summary.support_upload).toEqual(expect.objectContaining({ available: false }));
  expect(Array.isArray(summary.correlation_ids)).toBeTruthy();

  await page.goto("/system/diagnostics");
  await expect(page.getByRole("heading", { name: "Diagnostics & Support", exact: true })).toBeVisible();
  await expect(page.getByText("Support upload is not available in this edition. Download remains available.")).toBeVisible();
});

test("client discovery loads and displays the persisted deployment mode", async ({ page }) => {
  await signIn(page);

  const mode = await apiJson(page, "/setup/mode", "PUT", { mode: "msp" });
  expect(mode.mode).toBe("msp");

  await page.goto("/client-discovery");
  await expect(page.getByRole("heading", { name: "Client discovery", exact: true })).toBeVisible();
  await expect(page.getByLabel("Workspace mode summary")).toHaveText("MSP mode");
  await expect(page.getByRole("heading", { name: "Before you run discovery", exact: true })).toBeVisible();
  await expect(page.getByText("No discovery candidates yet.", { exact: true })).toBeVisible();
  await expect(page.getByText("No ticketing connector is active, so there is no provider data to review.", { exact: true })).toBeVisible();
  // The prerequisite banner and the empty state both link to connector setup.
  await expect(page.getByRole("link", { name: "Connect a ticketing system", exact: true }).first()).toBeVisible();
});

test("settings update check reports an unknown status without a configured channel", async ({ page }) => {
  await signIn(page);

  const update = await apiJson(page, "/update-check", "POST");
  expect(update.status).toBe("unknown");
  expect(update.detail).toBe("disabled");

  await page.goto("/settings");
  await page.getByRole("button", { name: "Check for updates" }).click();
  await expect(page.getByText("Update check complete.")).toBeVisible();
  await expect(page.locator('dt:has-text("Update check") + dd')).toHaveText("unknown");
});

test("collectors exports text from a locally created run", async ({ page }) => {
  await signIn(page);
  await page.goto("/collectors");

  await expect(page.getByRole("heading", { name: "Collectors", exact: true })).toBeVisible();
  const collector = page.getByRole("combobox", { name: "Collector", exact: true });
  await expect(collector).toBeVisible();
  // Select a local collector explicitly because the default is credential-gated.
  await collector.selectOption("host-runtime");
  await expect(collector).toHaveValue(/.+/);
  const runNow = page.getByRole("button", { name: "Run now", exact: true });
  await expect(runNow).toBeEnabled();
  await runNow.click();
  await page.getByRole("button", { name: "Yes, run it" }).click();
  await expect(page.getByText("Run started.")).toBeVisible();
  await page.getByRole("button", { name: "Export" }).first().click();
  await expect(page.locator("pre.code-panel").last()).not.toHaveText("");
});

test("the approvals workspace exposes selected-client and all-client scope", async ({ page }, testInfo) => {
  await signIn(page);
  const suffix = `${testInfo.retry}-${testInfo.repeatEachIndex}-${randomUUID()}`;
  const clientId = `approval-scope-${suffix}`;
  const clientName = `Approval Scope ${suffix}`;
  const created = await apiJson(page, "/clients", "POST", {
    client_id: clientId,
    name: clientName,
  });
  expect(created.client_id).toBe(clientId);

  await page.goto("/approvals");
  const approvalsScope = page.locator(".approvals-panel .scope-badge");
  await expect(approvalsScope).toHaveText("All clients");

  await page.locator("#app-client-selector").selectOption(clientId);
  await expect(approvalsScope).toHaveText(`Scoped to ${clientName}`);

  await page.locator("#app-client-selector").selectOption("");
  await expect(approvalsScope).toHaveText("All clients");
});

test("audit export downloads a non-empty local file", async ({ page }) => {
  await signIn(page);
  await page.goto("/audit");
  await expect(page.getByRole("heading", { name: "Audit", exact: true })).toBeVisible();

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Export Events JSON" }).click(),
  ]);
  const downloadPath = await download.path();
  expect(downloadPath).not.toBeNull();
  expect((await stat(downloadPath!)).size).toBeGreaterThan(0);
});
