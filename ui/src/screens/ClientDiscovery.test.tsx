import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ClientDiscovery } from "./ClientDiscovery";
import { apiFetch } from "../api/client";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true })
}));

const response = {
  items: [{
    candidate_id: "candidate-1",
    connector_instance_id: "instance-1",
    provider: "connectwise",
    external_id: "42",
    display_name: "Acme Ltd",
    domains_json: "[]",
    provenance: "connectwise:instance-1",
    first_seen: "2026-01-01",
    last_seen: "2026-01-01",
    match_state: "proposed",
    matched_client_id: "acme",
    match_reason: "exact normalized client name",
    confidence: 0.9
  }],
  page: 1,
  page_size: 50,
  summary: { discovered: 1, reconciled: 0, need_confirmation: 1, unmatched: 0, conflicts: 0 }
};

describe("ClientDiscovery", () => {
  it("shows the queue and keeps bulk actions scoped to proposed rows", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/setup/mode") return { mode: "msp" };
      if (path.startsWith("/discovery/clients")) return response;
      return {};
    });
    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Client discovery" })).toBeInTheDocument();
    expect(screen.getByText("Acme Ltd")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Accept proposed" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Accept proposed" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/discovery/clients/accept-proposed", expect.objectContaining({ method: "POST" })));
  });

  it("hides the review queue in SMB mode", async () => {
    vi.mocked(apiFetch).mockResolvedValue({ mode: "smb" });
    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "Client discovery is disabled" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Review queue" })).not.toBeInTheDocument();
  });
});
