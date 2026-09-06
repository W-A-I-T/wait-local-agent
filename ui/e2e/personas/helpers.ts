import { expect, test as base, type APIRequestContext, type Page } from "@playwright/test";

export const adminToken = "acceptance-admin-token";
export const requesterToken = "acceptance-requester-token";

export const test = base.extend<{ browserErrors: string[] }>({
  browserErrors: [async ({ page }, use) => {
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await use(errors);
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
