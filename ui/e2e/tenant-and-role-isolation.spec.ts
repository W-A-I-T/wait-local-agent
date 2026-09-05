import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const apiUrl = process.env.WAIT_BROWSER_API_URL ?? "http://127.0.0.1:8788";
const bootstrapToken = process.env.WAIT_BROWSER_TOKEN ?? "integration-admin-token";

async function preparePrincipal(request: APIRequestContext, betaRole: "viewer" | "technician") {
  // These fixtures are exclusively for the disposable local integration stack.
  expect(["127.0.0.1", "localhost", "[::1]"]).toContain(new URL(apiUrl).hostname);
  const suffix = randomUUID();
  const alpha = `alpha-${suffix}`;
  const beta = `beta-${suffix}`;
  const principalId = `journey-${suffix}`;
  const headers = { Authorization: `Bearer ${bootstrapToken}` };
  for (const [client_id, name] of [[alpha, `Client Alpha ${suffix}`], [beta, `Client Beta ${suffix}`]]) {
    const response = await request.post(`${apiUrl}/clients`, { headers, data: { client_id, name } });
    expect(response.ok()).toBeTruthy();
  }
  const response = await request.post(`${apiUrl}/auth/principals`, {
    headers,
    data: {
      principal_id: principalId,
      kind: "staff",
      display_name: "Local journey fixture",
      client_roles: [{ client_id: alpha, role: "admin" }, { client_id: beta, role: betaRole }],
      issue_credential: true,
    },
  });
  expect(response.status()).toBe(200);
  const principal = await response.json() as { token: string };
  expect(typeof principal.token).toBe("string");
  return { alpha, beta, principalId, token: principal.token };
}

async function signIn(page: Page, token: string) {
  await page.goto("/");
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "WAIT AI Solutions Architect", exact: true })).toBeVisible();
}

async function deactivate(request: APIRequestContext, principalId: string) {
  const response = await request.patch(`${apiUrl}/auth/principals/${principalId}`, {
    headers: { Authorization: `Bearer ${bootstrapToken}` }, data: { active: false },
  });
  expect(response.ok()).toBeTruthy();
}

test.beforeEach(async ({ page, baseURL }) => {
  expect(["127.0.0.1", "localhost", "[::1]"]).toContain(new URL(baseURL!).hostname);
  await page.addInitScript(() => localStorage.setItem("wait-local-agent-onboarding-dismissed", "1"));
});

test("client switching resolves the selected role and rejects forged writes", async ({ page, request }) => {
  const fixture = await preparePrincipal(request, "viewer");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    await signIn(page, fixture.token);
    const selector = page.getByRole("combobox", { name: "Client", exact: true });
    await selector.selectOption(fixture.alpha);
    await expect(page.getByText("Role: admin", { exact: true })).toBeVisible();
    await page.goto("/technician-chat");
    await page.getByRole("button", { name: "New chat session", exact: true }).click();
    await expect(page.getByText(/Session .* started\./)).toBeVisible();
    await page.getByLabel("Message", { exact: true }).fill("help");
    await page.getByRole("button", { name: "Send", exact: true }).click();
    await expect(page.getByText("You", { exact: true })).toBeVisible();

    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Admin Settings", exact: true })).toBeVisible();
    const forbiddenRequests: string[] = [];
    page.on("request", (sent) => {
      if (sent.headers()["x-wait-client-id"] === fixture.beta &&
          ["/settings/security", "/secrets", "/auth/principals"].includes(new URL(sent.url()).pathname)) {
        forbiddenRequests.push(new URL(sent.url()).pathname);
      }
    });
    await selector.selectOption(fixture.beta);
    await expect(page.getByText("Role: viewer", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Administrator access required", exact: true })).toBeVisible();
    await expect(selector.locator("option")).toHaveCount(3);
    expect(forbiddenRequests).toEqual([]);

    for (const selected of [fixture.alpha, fixture.beta]) {
      const result = await request.post(`${apiUrl}/technician/chat/sessions`, {
        headers: { Authorization: `Bearer ${fixture.token}`, "X-WAIT-Client-ID": selected },
        data: { client_id: fixture.beta },
      });
      expect(result.status()).toBe(403);
    }
    await page.goto("/settings/access");
    await expect(page.getByRole("heading", { name: "MSP administrator access required" })).toBeVisible();
    await page.goto("/microsoft-admin");
    await expect(page.getByRole("heading", { name: "Microsoft Admin access denied", exact: true })).toBeVisible();
    await page.goto("/technician-chat");
    await expect(page.getByText("Technician access required", { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
  } finally {
    await deactivate(request, fixture.principalId);
  }
});

test("changing clients clears the active conversation and unsent drafts", async ({ page, request }) => {
  const fixture = await preparePrincipal(request, "technician");
  try {
    await signIn(page, fixture.token);
    const selector = page.getByRole("combobox", { name: "Client", exact: true });
    await selector.selectOption(fixture.alpha);
    await expect(page.getByText("Role: admin", { exact: true })).toBeVisible();
    await page.goto("/technician-chat");
    await page.getByRole("button", { name: "New chat session", exact: true }).click();
    await expect(page.getByText(/Session .* started\./)).toBeVisible();
    await page.getByLabel("Message", { exact: true }).fill("Unsent Alpha investigation");
    await page.getByLabel("Ticket id (optional)").fill("ALPHA-LOCAL-123");
    await page.getByLabel("Notification message").fill("Unsent Alpha notification");

    await selector.selectOption(fixture.beta);
    await expect(page.getByText("Role: technician", { exact: true })).toBeVisible();
    await expect(page.getByText("No technician sessions yet.", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Select or start a session" })).toBeVisible();
    await expect(page.getByLabel("Ticket id (optional)")).toHaveValue("");
    await expect(page.getByLabel("Notification message")).toHaveValue("");
    await expect(page.getByLabel("Message", { exact: true })).toHaveCount(0);
    await page.reload();
    await expect(selector).toHaveValue(fixture.beta);
    await expect(page.getByRole("heading", { name: "Select or start a session" })).toBeVisible();
  } finally {
    await deactivate(request, fixture.principalId);
  }
});
