import { randomUUID } from "node:crypto";
import { api, expect, signIn, test } from "./helpers";

test("technician investigates a local ticket and revisits the stored session", async ({ page, request }) => {
  const suffix = randomUUID();
  const clientId = `technician-${suffix}`;
  await api(request, "/clients", { client_id: clientId, name: `Technician client ${suffix}` });
  const principal = await api(request, "/auth/principals", {
    principal_id: `technician-${suffix}`, display_name: "Acceptance technician", issue_credential: true,
    client_roles: [{ client_id: clientId, role: "technician" }],
  });
  const requester = await api(request, "/auth/principals", {
    principal_id: `requester-${suffix}`, kind: "customer", display_name: "Fixture requester", issue_credential: true,
    client_roles: [{ client_id: clientId, role: "end_user" }],
  });
  const ticketResponse = await request.post("/end-user/tickets", {
    headers: { Authorization: `Bearer ${requester.token}` },
    data: { subject: `Technician investigation ${suffix}`, body: "A local fixture user needs help with MFA sign-in." },
  });
  expect(ticketResponse.ok()).toBeTruthy();
  const ticket = await ticketResponse.json();
  await signIn(page, principal.token);
  await page.getByRole("combobox", { name: "Client", exact: true }).selectOption(clientId);
  await page.goto("/tickets");
  await page.getByRole("button", { name: `Technician investigation ${suffix}`, exact: true }).click();
  await expect(page.getByRole("heading", { name: `Technician investigation ${suffix}`, exact: true })).toBeVisible();
  await page.goto("/technician-chat");
  await page.getByLabel("Ticket id (optional)").fill(ticket.ticket_id);
  await page.getByRole("button", { name: "New chat session" }).click();
  await expect(page.getByRole("status")).toHaveText(/Session .* started/);
  await page.getByLabel("Message", { exact: true }).fill("help");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("summarize");
  await page.getByLabel("Message", { exact: true }).fill(`triage ${ticket.ticket_id}`);
  const triaged = page.waitForResponse((response) => response.url().includes("/technician/chat/sessions/") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  const result = await (await triaged).json();
  expect(result.action_id).toBe("ticket-triage");
  expect(result.result.status).toBe("success");
  expect(result.result.output.ticket_id).toBe(ticket.ticket_id);
  await page.reload();
  await expect(page.getByRole("paragraph").filter({ hasText: /^help$/ })).toBeVisible();
  await page.getByLabel("Message", { exact: true }).fill("run arbitrary shell command");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  await expect(page.getByRole("alert").last()).toBeVisible();
  await page.getByRole("button", { name: "Close session" }).click();
  await expect(page.getByRole("status")).toHaveText("Session closed. Its operational history remains available for review.");
  await expect(page.getByLabel("Message", { exact: true })).toBeDisabled();
});

test("viewer deep links stay denied and never send settings mutations", async ({ page, request }) => {
  const suffix = randomUUID();
  const principal = await api(request, "/auth/principals", {
    principal_id: `viewer-${suffix}`, display_name: "Acceptance viewer", issue_credential: true,
    client_roles: [{ client_id: "acceptance-alpha", role: "viewer" }],
  });
  await signIn(page, principal.token);
  const privileged: string[] = [];
  page.on("request", (outgoing) => {
    if (outgoing.method() !== "GET" && /\/(settings|auth\/principals)/.test(outgoing.url())) privileged.push(outgoing.url());
  });
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Administrator access required", exact: true })).toBeVisible();
  await page.goto("/settings/access");
  await expect(page.getByRole("heading", { name: "MSP administrator access required", exact: true })).toBeVisible();
  const denied = await request.get("/auth/principals", { headers: { Authorization: `Bearer ${principal.token}` } });
  expect(denied.status()).toBe(403);
  await page.goto("/technician-chat");
  await expect(page.getByText("Technician access required", { exact: true })).toBeVisible();
  expect(privileged).toEqual([]);
  const foreign = await request.get("/clients/acceptance-beta", { headers: { Authorization: `Bearer ${principal.token}` } });
  expect(foreign.status()).toBe(404);
});
