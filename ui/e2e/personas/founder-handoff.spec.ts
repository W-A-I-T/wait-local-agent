import { api, expect, signIn, test } from "./helpers";

test("founder reviews the real privacy package, cancels, and retries a failed fixture handoff", async ({ page, request }) => {
  const fixture = await api(request, "/__acceptance/fixtures");
  expect(fixture.uploads).toBe(0);
  await signIn(page);
  await page.goto("/founder");
  await page.getByLabel("Project folder", { exact: true }).fill(fixture.project);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await expect(page.getByRole("heading", { name: "What will be shared" })).toBeVisible();
  await expect(page.getByText("Source files are not uploaded.")).toBeVisible();
  await page.getByRole("button", { name: "Preview upload package", exact: true }).click();
  await expect(page.getByText(/Configuration key names included: EXAMPLE_API_KEY/)).toBeVisible();
  expect((await api(request, "/__acceptance/fixtures")).uploads).toBe(0);
  await page.getByRole("button", { name: "Continue to confirmation" }).click();
  await expect(page.getByRole("heading", { name: "Confirm this upload" })).toBeVisible();
  await page.getByRole("button", { name: "Dismiss", exact: true }).click();
  expect((await api(request, "/__acceptance/fixtures")).uploads).toBe(0);
  await page.getByRole("button", { name: "Next", exact: true }).click();
  await page.getByRole("button", { name: "Preview upload package", exact: true }).click();
  await page.getByRole("button", { name: "Continue to confirmation" }).click();
  const failedUpload = page.waitForResponse((response) => response.url().includes("/founder/upload/") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Upload reviewed package" }).click();
  expect((await failedUpload).ok()).toBeFalsy();
  await expect(page.getByText(/Upload complete/)).toHaveCount(0);
  expect((await api(request, "/__acceptance/fixtures")).uploads).toBe(1);
  // A failed provider handoff must remain retryable without pretending success.
  await page.getByRole("button", { name: "Upload reviewed package" }).click();
  await expect(page.getByText(/Upload complete\./)).toBeVisible();
  expect((await api(request, "/__acceptance/fixtures")).uploads).toBe(2);
  await expect(page.getByRole("button", { name: "Run launch scan", exact: true })).toBeDisabled();
  await expect(page.getByText("No latest report reference was returned yet.")).toBeVisible();
  await expect(page.getByText("This check is unavailable in the installed package.")).toHaveCount(2);
});
