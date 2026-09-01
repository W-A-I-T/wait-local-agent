import { randomUUID } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

const token = process.env.WAIT_BROWSER_TOKEN ?? "integration-admin-token";

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

test("shows the local sign-in screen without a stored credential", async ({ page }) => {
  await page.goto("/");
  await page.evaluate(() => localStorage.clear());
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
    ["/integrations/connector-instances", "Connector Instances"],
    ["/knowledge", "Knowledge"],
    ["/playbooks", "MSP Playbooks"],
    ["/integrations/mcp", "MCP server"],
    ["/settings", "Admin Settings"]
  ] as const;

  for (const [path, heading] of routes) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
  }

  await page.goto("/clients");
  await page.getByRole("button", { name: "New client" }).click();
  await page.getByLabel("Client ID").fill(clientId);
  await page.getByLabel("Name").fill(clientName);
  await page.getByRole("button", { name: "Create client" }).click();
  await expect(page.getByRole("status")).toContainText("Client created.");

  await page.goto("/integrations/connector-instances");
  await page.getByLabel("Display name").fill(connectorName);
  await page.getByLabel("WAIT client (optional)").selectOption(clientId);
  await page.getByLabel("Base URL").fill("https://provider.invalid");
  await page.getByLabel("Client ID", { exact: true }).fill("browser-client-id");
  await page.getByLabel("Client secret").fill("browser-client-secret");
  await page.getByLabel("Tenant").fill("browser-tenant");
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
  const qbr = page.locator("article").filter({ hasText: "Quarterly Business Review" });
  await expect(qbr).toBeVisible();
  await qbr.getByLabel("Period start").fill("2026-01-01");
  await qbr.getByLabel("Period end").fill("2026-03-31");
  await qbr.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByRole("status")).toContainText("Preview ready for Quarterly Business Review.");

  await page.goto("/integrations/mcp");
  await expect(page.getByRole("heading", { name: "MCP server", exact: true })).toBeVisible();
  await expect(page.getByText("Published tool catalog")).toBeVisible();
});
