import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

export const adminToken = "acceptance-admin-token";
export const requesterToken = "acceptance-requester-token";

export const test = base.extend<{ browserErrors: string[] }>({
  browserErrors: [async ({ context }, use, testInfo) => {
    const errors: string[] = [];
    const diagnostics: object[] = [];
    const observe = (page: Page) => {
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => {
        if (message.type() !== "error" && message.type() !== "warning") return;
        const text = message.text();
        diagnostics.push({ type: message.type(), text });
        // Chromium also logs expected 401/403/404/503 responses. Each negative
        // journey asserts those responses explicitly; script errors still fail.
        if (message.type() === "error" && !text.startsWith("Failed to load resource:")) errors.push(text);
      });
      page.on("response", (response) => {
        if (response.status() >= 400) diagnostics.push({ status: response.status(), path: new URL(response.url()).pathname });
      });
      page.on("requestfailed", (request) => {
        const failure = request.failure()?.errorText ?? "Unknown network failure";
        diagnostics.push({ failure, path: new URL(request.url()).pathname });
        if (failure !== "net::ERR_ABORTED") errors.push(failure);
      });
    };
    context.pages().forEach(observe);
    context.on("page", observe);
    await use(errors);
    await testInfo.attach("browser-diagnostics", { body: JSON.stringify(diagnostics, null, 2), contentType: "application/json" });
    expect(errors, "Unexpected browser exceptions").toEqual([]);
  }, { auto: true }],
});
export { expect };

export async function signIn(page: Page, token = adminToken, dismissOnboarding = true) {
  await page.goto("/");
  await page.getByLabel("Access token", { exact: true }).fill(token);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText(/Role: (admin|technician|viewer)/)).toBeVisible();
  if (dismissOnboarding) {
    await page.getByRole("button", { name: "Dismiss", exact: true }).click();
  }
}

export async function api(request: APIRequestContext, path: string, data?: object, method = data ? "POST" : "GET") {
  const response = await request.fetch(path, {
    method, data, headers: { Authorization: `Bearer ${adminToken}` },
  });
  expect(response.ok(), `${method} ${path}: ${response.status()}`).toBeTruthy();
  return response.json();
}

export async function selectAlpha(page: Page) {
  await page.getByRole("combobox", { name: "Client", exact: true }).selectOption("acceptance-alpha");
}
