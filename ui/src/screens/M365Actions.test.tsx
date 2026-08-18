import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { M365Actions } from "./M365Actions";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const dashboard = { role: "admin", roleResolved: true, selectedClientId: "client-acme" };
vi.mock("../app/DashboardContext", () => ({ useDashboard: () => dashboard }));

const mockedApiFetch = vi.mocked(apiFetch);
const renderScreen = () => render(<MemoryRouter><M365Actions /></MemoryRouter>);

describe("M365Actions", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    dashboard.selectedClientId = "client-acme";
    mockedApiFetch.mockResolvedValue({ id: 42, action_type: "m365.test", status: "pending_approval" });
  });

  it("renders three forms and posts each draft with the selected client", async () => {
    renderScreen();
    expect(screen.getAllByRole("button", { name: "Create approval draft" })).toHaveLength(3);

    fireEvent.change(screen.getAllByLabelText("User (UPN or email)")[0], { target: { value: "user@example.com" } });
    fireEvent.submit(screen.getByRole("heading", { name: "Offboard — Disable user" }).closest("section")!.querySelector("form")!);
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/m365/users/disable-drafts", expect.objectContaining({ body: JSON.stringify({ user_identity: "user@example.com", client_id: "client-acme" }) })));

    fireEvent.change(screen.getByLabelText("Vault secret name holding the temporary password"), { target: { value: "vault-secret-name" } });
    fireEvent.change(screen.getAllByLabelText("User (UPN or email)")[1], { target: { value: "reset@example.com" } });
    fireEvent.submit(screen.getByRole("heading", { name: "Password reset" }).closest("section")!.querySelector("form")!);
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/m365/users/password-reset-drafts", expect.objectContaining({ body: JSON.stringify({ user_identity: "reset@example.com", temporary_vault_name: "vault-secret-name", force_change_password_next_sign_in: true, force_change_password_next_sign_in_with_mfa: false, client_id: "client-acme" }) })));

    fireEvent.change(screen.getByLabelText("Managed device ID"), { target: { value: "device-001" } });
    fireEvent.submit(screen.getByRole("heading", { name: "Device reboot" }).closest("section")!.querySelector("form")!);
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/m365/managed-devices/reboot-drafts", expect.objectContaining({ body: JSON.stringify({ device_id: "device-001", client_id: "client-acme" }) })));
    expect(await screen.findAllByText(/pending approval #42/)).toHaveLength(3);
    expect(screen.getAllByRole("link", { name: "Go to Approvals" })).toHaveLength(3);
  });

  it("blocks drafts without a client and rejects short vault names without a password input", () => {
    dashboard.selectedClientId = "";
    const view = renderScreen();
    expect(screen.getAllByRole("button", { name: "Create approval draft" }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getAllByText("Select a client from the top bar to draft an action.")).toHaveLength(3);
    expect(document.querySelectorAll('input[type="password"]')).toHaveLength(0);
    dashboard.selectedClientId = "client-acme";
    view.rerender(<MemoryRouter><M365Actions /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Vault secret name holding the temporary password"), { target: { value: "too-short" } });
    expect(screen.getAllByRole("button", { name: "Create approval draft" })[1]).toBeDisabled();
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it("renders API errors as a danger notice", async () => {
    mockedApiFetch.mockRejectedValue(new Error("client scope is required"));
    renderScreen();
    fireEvent.change(screen.getByLabelText("Managed device ID"), { target: { value: "device-001" } });
    fireEvent.click(screen.getAllByRole("button", { name: "Create approval draft" })[2]);
    expect(await screen.findByRole("alert")).toHaveTextContent("client scope is required");
    expect(screen.getByRole("alert")).toHaveClass("notice", "danger");
  });
});
