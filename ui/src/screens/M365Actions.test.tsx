import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { M365Actions } from "./M365Actions";
import { M365_ACTION_CATALOG } from "./m365ActionCatalog";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const dashboard = { role: "admin", roleResolved: true, selectedClientId: "client-acme" };
vi.mock("../app/DashboardContext", () => ({ useDashboard: () => dashboard }));

const mockedApiFetch = vi.mocked(apiFetch);
const approval = { id: 42, action_type: "m365.test", status: "pending_approval" };
const renderScreen = () => render(<MemoryRouter><M365Actions /></MemoryRouter>);

const EXPECTED_ENDPOINTS = [
  "/connectors/m365/users/drafts",
  "/connectors/m365/users/disable-drafts",
  "/connectors/m365/users/password-reset-drafts",
  "/connectors/m365/users/authentication-method-drafts",
  "/connectors/m365/users/license-drafts",
  "/connectors/m365/users/mailbox-settings-drafts",
  "/connectors/m365/users/session-revocation-drafts",
  "/connectors/m365/groups/membership-drafts",
  "/connectors/m365/mail-messages/delete-drafts",
  "/connectors/m365/mail-messages/move-drafts",
  "/connectors/m365/mail-messages/read-state-drafts",
  "/connectors/m365/managed-devices/reboot-drafts",
  "/connectors/m365/managed-devices/remote-lock-drafts",
  "/connectors/m365/managed-devices/retire-drafts",
  "/connectors/m365/managed-devices/sync-drafts",
  "/connectors/m365/teams/message-drafts"
];

async function waitForPickerReads() {
  await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledTimes(6));
}

function card(title: string): HTMLElement {
  return screen.getByRole("heading", { name: title }).closest("article")!;
}

function submitCard(title: string) {
  fireEvent.submit(card(title).querySelector("form")!);
}

async function expectPost(endpoint: string, body: Record<string, unknown>) {
  await waitFor(() => {
    const call = mockedApiFetch.mock.calls.find(([path, init]) => path === endpoint && init?.method === "POST");
    expect(call).toBeDefined();
    expect(JSON.parse(String(call?.[1]?.body))).toEqual(body);
  });
}

describe("M365Actions", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    dashboard.selectedClientId = "client-acme";
    dashboard.role = "admin";
    dashboard.roleResolved = true;
    mockedApiFetch.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") return approval;
      return { items: [] };
    });
  });

  it("contains each backend draft endpoint exactly once and no invented endpoint", () => {
    const endpoints = M365_ACTION_CATALOG.map((action) => action.endpoint);
    expect(endpoints).toHaveLength(16);
    expect(new Set(endpoints).size).toBe(endpoints.length);
    expect([...endpoints].sort()).toEqual([...EXPECTED_ENDPOINTS].sort());
  });

  it("renders all five categories and all sixteen action forms", async () => {
    renderScreen();
    await waitForPickerReads();

    expect(screen.getByRole("heading", { name: "Identity" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Licenses & Groups" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Mailbox" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Devices" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Teams" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Create approval draft" })).toHaveLength(16);
  });

  it("submits the Identity action with the exact backend field names", async () => {
    renderScreen();
    await waitForPickerReads();
    fireEvent.change(within(card("Offboard — Disable user")).getByLabelText("User (UPN or email)"), { target: { value: " user@example.com " } });
    submitCard("Offboard — Disable user");
    await expectPost("/connectors/m365/users/disable-drafts", { user_identity: "user@example.com", client_id: "client-acme" });
  });

  it("submits the Licenses & Groups action with the exact backend field names", async () => {
    renderScreen();
    await waitForPickerReads();
    const groupCard = card("Change group membership");
    fireEvent.change(within(groupCard).getByLabelText("Group"), { target: { value: "group-1" } });
    fireEvent.change(within(groupCard).getByLabelText("User"), { target: { value: "user-1" } });
    fireEvent.change(within(groupCard).getByLabelText("Operation"), { target: { value: "add" } });
    submitCard("Change group membership");
    await expectPost("/connectors/m365/groups/membership-drafts", { group_id: "group-1", user_id: "user-1", operation: "add", client_id: "client-acme" });
  });

  it("submits the Mailbox action with a settings object", async () => {
    renderScreen();
    await waitForPickerReads();
    const mailboxCard = card("Update mailbox settings");
    fireEvent.change(within(mailboxCard).getByLabelText("User (UPN or email)"), { target: { value: "mail@example.com" } });
    fireEvent.change(within(mailboxCard).getByLabelText("Setting 1 name"), { target: { value: "timezone" } });
    fireEvent.change(within(mailboxCard).getByLabelText("Setting 1 value"), { target: { value: "UTC" } });
    submitCard("Update mailbox settings");
    await expectPost("/connectors/m365/users/mailbox-settings-drafts", { user_identity: "mail@example.com", settings: { timezone: "UTC" }, client_id: "client-acme" });
  });

  it("submits the Devices action with the exact backend field names", async () => {
    renderScreen();
    await waitForPickerReads();
    const deviceCard = card("Reboot managed device");
    fireEvent.change(within(deviceCard).getByLabelText("Managed device"), { target: { value: "device-001" } });
    submitCard("Reboot managed device");
    await expectPost("/connectors/m365/managed-devices/reboot-drafts", { device_id: "device-001", client_id: "client-acme" });
  });

  it("submits the Teams action with the exact backend field names", async () => {
    renderScreen();
    await waitForPickerReads();
    const teamsCard = card("Send Teams message");
    fireEvent.change(within(teamsCard).getByLabelText("Team"), { target: { value: "team-1" } });
    fireEvent.change(within(teamsCard).getByLabelText("Channel"), { target: { value: "channel-1" } });
    fireEvent.change(within(teamsCard).getByLabelText("Message"), { target: { value: "Please review this draft." } });
    submitCard("Send Teams message");
    await expectPost("/connectors/m365/teams/message-drafts", { team_id: "team-1", channel_id: "channel-1", body: "Please review this draft.", client_id: "client-acme" });
    expect(await screen.findByRole("link", { name: "Go to Approvals" })).toBeInTheDocument();
  });

  it("falls back to editable text inputs when picker reads fail", async () => {
    mockedApiFetch.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") return approval;
      throw new Error("m365 not_configured");
    });
    renderScreen();
    await waitForPickerReads();

    const userInput = within(card("Offboard — Disable user")).getByLabelText("User (UPN or email)") as HTMLInputElement;
    expect(userInput).toHaveAttribute("type", "text");
    expect(userInput).not.toHaveAttribute("list");
    expect(within(card("Offboard — Disable user")).getByRole("button", { name: "Create approval draft" })).toBeEnabled();
  });

  it("keeps the client requirement and disables every draft without a selection", () => {
    dashboard.selectedClientId = "";
    renderScreen();
    expect(screen.getAllByRole("button", { name: "Create approval draft" }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getByText("Select a client from the top bar to draft an action.")).toBeInTheDocument();
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0);
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it("preserves administrator gating and the access-loading state", () => {
    dashboard.roleResolved = false;
    const view = renderScreen();
    expect(screen.getByText("Checking administrator access…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create approval draft" })).not.toBeInTheDocument();

    dashboard.roleResolved = true;
    view.rerender(<MemoryRouter><M365Actions /></MemoryRouter>);
    expect(screen.getAllByRole("button", { name: "Create approval draft" })).toHaveLength(16);

    dashboard.role = "technician";
    view.rerender(<MemoryRouter><M365Actions /></MemoryRouter>);
    expect(screen.getByText("Administrator access required")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create approval draft" })).not.toBeInTheDocument();
  });

  it("keeps vault references as text-only inputs and enforces the minimum name length", async () => {
    renderScreen();
    await waitForPickerReads();
    const resetCard = card("Password reset");
    const vaultName = within(resetCard).getByLabelText("Vault secret name holding the temporary password") as HTMLInputElement;
    expect(vaultName).toHaveAttribute("type", "text");
    fireEvent.change(within(resetCard).getByLabelText("User (UPN or email)"), { target: { value: "reset@example.com" } });
    fireEvent.change(vaultName, { target: { value: "too-short" } });
    submitCard("Password reset");
    expect(await within(resetCard).findByText("Vault secret name must be at least 14 characters.")).toBeInTheDocument();
    expect(mockedApiFetch.mock.calls.some(([_path, init]) => init?.method === "POST")).toBe(false);
  });

  it("renders API errors as a danger notice", async () => {
    mockedApiFetch.mockImplementation(async (_path, init) => {
      if (init?.method === "POST") throw new Error("client scope is required");
      return { items: [] };
    });
    renderScreen();
    await waitForPickerReads();
    const deviceCard = card("Reboot managed device");
    fireEvent.change(within(deviceCard).getByLabelText("Managed device"), { target: { value: "device-001" } });
    submitCard("Reboot managed device");
    expect(await screen.findByRole("alert")).toHaveTextContent("client scope is required");
  });
});
