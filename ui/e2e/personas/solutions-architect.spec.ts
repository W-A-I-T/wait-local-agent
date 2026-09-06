import { randomUUID } from "node:crypto";
import { api, expect, selectAlpha, signIn, test } from "./helpers";

test("architect completes and resumes guided discovery and reviews a local delivery package", async ({ page, request }) => {
  await signIn(page);
  const name = `Local onboarding ${randomUUID()}`;
  await selectAlpha(page);
  await page.goto("/consultant");
  await page.getByLabel("Solution name", { exact: true }).fill(name);
  await page.getByLabel("Business goal", { exact: true }).fill("Reduce manual onboarding using a reviewed local plan");
  const started = page.waitForResponse((response) => response.url().endsWith("/consultant/discovery/sessions") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Start guided discovery", exact: true }).click();
  let session = await (await started).json();
  // The backend supplies bounded questions; every answer is entered in the UI.
  for (let turn = 0; session.next_question && turn < 20; turn += 1) {
    if (session.next_question.kind === "boolean") {
      await page.getByRole("checkbox", { name: "Yes", exact: true }).uncheck();
    } else {
      await page.getByRole("textbox", { name: "Guided discovery answer" }).fill("Local test evidence reviewed by the service team");
    }
    const saved = page.waitForResponse((response) => response.url().includes(`/discovery/sessions/${session.session_id}/turn`));
    await page.getByRole("button", { name: "Save answer and continue" }).click();
    session = await (await saved).json();
  }
  expect(session.status).toBe("complete");
  expect(session.blueprint_id).toBeTruthy();
  await expect(page.getByText("Guided discovery is complete. Review the evidence and readiness result above.")).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: new RegExp(`${name} · completed`) }).click();
  await expect(page.getByLabel("Guided discovery transcript")).toContainText("Local test evidence reviewed by the service team");

  await page.getByRole("link", { name: "Solution delivery", exact: true }).click();
  const fixture = await api(request, "/__acceptance/fixtures");
  await page.getByLabel("Output directory", { exact: true }).fill(`${fixture.delivery}/${randomUUID()}`);
  await page.getByRole("button", { name: "Build package", exact: true }).click();
  await expect(page.getByText("Package ready", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Validate package", exact: true }).click();
  await expect(page.getByText("Validation passed", { exact: true })).toBeVisible();
  await expect(page.getByText(/Nothing runs until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT/)).toBeVisible();
});
