import { fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { Clients } from "./Clients";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({
    role: "admin",
    roleResolved: true,
    isMspAdmin: true,
    commercialEntitlement: { edition: "commercial" },
    refresh: vi.fn(),
    refreshConfiguration: vi.fn()
  })
}));

const mockedApiFetch = vi.mocked(apiFetch);

function render(ui: Parameters<typeof rtlRender>[0]) {
  return rtlRender(<MemoryRouter>{ui}</MemoryRouter>);
}

describe("Clients commercial activation hook", () => {
  it("shows neutral activation controls only for a loaded commercial entitlement", async () => {
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/commercial-activations") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/setup/mode") return Promise.resolve({ mode: "msp" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/commercial-activation" && init?.method === "POST") {
        return Promise.resolve({ client_id: "acme", activated_at: "now", activated_by: "operator" }) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);

    expect(await screen.findByText("Commercial: unmanaged")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Set managed" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/commercial-activation", { method: "POST" }));
    expect(await screen.findByText("Commercial: managed")).toBeInTheDocument();
  });
});
