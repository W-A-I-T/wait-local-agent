import { randomUUID } from "node:crypto";
import { api, expect, selectAlpha, signIn, test } from "./helpers";

test("architect resumes discovery and distinguishes a review package from deployable work", async ({ page, request }) => {
  await signIn(page);
  const name = `Local onboarding ${randomUUID()}`;
  await selectAlpha(page);
  await page.goto("/consultant");
  await page.getByLabel("Solution name", { exact: true }).fill(name);
  await page.getByLabel("Business goal", { exact: true }).fill("Reduce manual onboarding using a reviewed local plan");
  const started = page.waitForResponse((response) => response.url().endsWith("/consultant/discovery/sessions") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Start guided discovery", exact: true }).click();
  let session = await (await started).json();
  // Use the actual discovery schema's remaining questions, including optional
  // evidence; the shipped flow completes only once all questions are answered.
  const remainingQuestions = session.unanswered.length;
  const answered = new Set<string>();
  for (let turn = 0; session.next_question && turn < remainingQuestions; turn += 1) {
    expect(answered.has(session.next_question.id), "Discovery must advance to a new question").toBe(false);
    answered.add(session.next_question.id);
    await expect(page.getByText(`${session.unanswered.length} evidence questions remain unanswered.`, { exact: true })).toBeVisible();
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

  await page.getByRole("complementary", { name: "Workspace navigation" }).getByRole("link", { name: "Solution delivery", exact: true }).click();
  const fixture = await api(request, "/__acceptance/fixtures");
  await page.getByLabel("Output directory", { exact: true }).fill(`${fixture.delivery}/${randomUUID()}`);
  await page.getByRole("button", { name: "Build package", exact: true }).click();
  await expect(page.getByText("Package ready", { exact: true })).toBeVisible();
  const validation = page.waitForResponse((response) => response.url().endsWith("/power-platform/package/validate"));
  await page.getByRole("button", { name: "Validate package", exact: true }).click();
  const refusal = await validation;
  expect(refusal.status()).toBe(422);
  expect((await refusal.json()).detail).toContain("package contains no component that will import");
  await expect(page.getByRole("alert")).toContainText("This package is for design review only.");
  await expect(page.getByText("Validation passed", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Nothing runs until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT/)).toBeVisible();
});
