import { randomUUID } from "node:crypto";
import { api, expect, requesterToken, selectAlpha, signIn, test } from "./helpers";

test("requester submits, technician replies, and the private conversation survives reload", async ({ page, context }) => {
  const subject = `Cannot sign in ${randomUUID()}`;
  await page.goto("/end-user");
  await page.getByLabel("Support access token").fill(requesterToken);
  await page.getByRole("button", { name: "Save access" }).click();
  await expect(page.getByRole("status")).toHaveText(/Access token saved/);
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByLabel("Subject")).toBeFocused();
  await page.getByLabel("Subject", { exact: true }).fill(subject);
  await page.getByLabel("Details", { exact: true }).fill("The local fixture account cannot sign in.");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByRole("status")).toHaveText(/Your request EUS-.* was submitted/);
  const ticketId = await page.getByLabel("Request number").inputValue();
  await page.getByLabel("Send a follow-up").fill("I can reproduce this after restarting.");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Your message was sent to the support team.");

  const operator = await context.newPage();
  await signIn(operator);
  await selectAlpha(operator);
  await operator.goto("/tickets");
  await operator.getByRole("button", { name: subject, exact: true }).click();
  await operator.getByRole("button", { name: "Load conversation" }).click();
  await expect(operator.getByText("I can reproduce this after restarting.", { exact: true })).toBeVisible();
  await operator.getByLabel("Reply to requester").fill("We are reviewing your request. No provider change has been made.");
  await operator.getByRole("button", { name: "Add support reply" }).click();
  await expect(operator.getByText("Reply added to the local customer conversation.")).toBeVisible();

  await page.reload();
  await page.getByLabel("Request number").fill(ticketId);
  await page.getByRole("button", { name: "Check status" }).click();
  await expect(page.getByText("We are reviewing your request. No provider change has been made.")).toBeVisible();
  await page.getByRole("button", { name: "Ask for technician attention" }).click();
  await expect(page.getByText("Status: escalated")).toBeVisible();
  await operator.close();
});

test("requester cannot see other requesters or clients, and clearing access removes private state", async ({ page, request }) => {
  const fixture = await api(request, "/__acceptance/fixtures");
  await page.goto("/end-user");
  await page.getByLabel("Support access token").fill(requesterToken);
  await page.getByRole("button", { name: "Save access" }).click();
  await expect(page.getByRole("status")).toHaveText(/Access token saved/);
  for (const ticketId of [fixture.other_ticket, fixture.beta_ticket]) {
    await page.getByLabel("Request number").fill(ticketId);
    const response = page.waitForResponse((item) => item.url().endsWith(`/end-user/tickets/${ticketId}`));
    await page.getByRole("button", { name: "Check status" }).click();
    expect((await response).status()).toBe(404);
    await expect(page.getByText("No request selected")).toBeVisible();
  }
  await expect(page.getByRole("combobox", { name: "Client", exact: true })).toHaveCount(0);
  await page.getByLabel("Subject", { exact: true }).fill(`Private request ${randomUUID()}`);
  await page.getByLabel("Details", { exact: true }).fill("Requester private details");
  await page.getByRole("button", { name: "Submit request" }).click();
  await expect(page.getByText("Requester private details", { exact: true })).toBeVisible();
  await page.getByLabel("Send a follow-up").fill("Unsent private follow-up");
  await page.getByLabel("Support access token").fill("");
  await page.getByRole("button", { name: "Save access" }).click();
  await expect(page.getByText("No request selected")).toBeVisible();
  await expect(page.getByText("Requester private details", { exact: true })).toHaveCount(0);
  await expect(page.getByLabel("Send a follow-up")).toHaveCount(0);
  await page.reload();
  await expect(page.getByLabel("Support access token")).toBeEmpty();
  await expect(page.getByRole("button", { name: "Check status" })).toBeDisabled();
});
