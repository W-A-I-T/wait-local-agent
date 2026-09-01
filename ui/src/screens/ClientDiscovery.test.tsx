import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ClientDiscovery } from "./ClientDiscovery";
import { apiFetch } from "../api/client";
import type { DiscoveryResponse } from "../api/types";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true })
}));

const response: DiscoveryResponse = {
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

const populatedResponse: DiscoveryResponse = {
  items: [
    response.items[0],
    { ...response.items[0], candidate_id: "candidate-2", external_id: "43", display_name: "Ambiguous Co", match_state: "ambiguous", matched_client_id: null },
    { ...response.items[0], candidate_id: "candidate-3", external_id: "44", display_name: "Unmatched Co", match_state: "unmatched", matched_client_id: null },
  ],
  page: 1,
  page_size: 50,
  summary: { discovered: 8, reconciled: 5, need_confirmation: 2, unmatched: 1, conflicts: 3 }
};

const emptyResponse: DiscoveryResponse = {
  items: [],
  page: 1,
  page_size: 50,
  summary: { discovered: 0, reconciled: 0, need_confirmation: 0, unmatched: 0, conflicts: 0 }
};

describe("ClientDiscovery", () => {
  beforeEach(() => vi.clearAllMocks());

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

  it("runs discovery and reloads the queue", async () => {
    let listing = emptyResponse;
    vi.mocked(apiFetch).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/setup/mode") return { mode: "msp" };
      if (path === "/discovery/clients/run" && init?.method === "POST") {
        listing = response;
        return { failures: [] };
      }
      if (path.startsWith("/discovery/clients")) return listing;
      return {};
    });

    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Run discovery" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/discovery/clients/run", expect.objectContaining({ method: "POST", body: "{}" })));
    expect(await screen.findByRole("status")).toHaveTextContent("Discovery completed.");
    expect(screen.getByText("Acme Ltd")).toBeInTheDocument();
  });

  it("renders summary chips from a populated listing", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string) => {
      if (path === "/setup/mode") return { mode: "msp" };
      if (path.startsWith("/discovery/clients")) return populatedResponse;
      return {};
    });

    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    const summary = await screen.findByRole("region", { name: "Discovery summary" });
    expect(summary).toHaveTextContent("8 discovered");
    expect(summary).toHaveTextContent("5 reconciled");
    expect(summary).toHaveTextContent("2 need confirmation");
    expect(summary).toHaveTextContent("1 unmatched");
    expect(summary).toHaveTextContent("3 conflicts");
  });

  it("calls the correct endpoint for each row action", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/setup/mode") return { mode: "msp" };
      if (init?.method === "POST") return {};
      if (path.startsWith("/discovery/clients")) return populatedResponse;
      return {};
    });

    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    await screen.findByText("Acme Ltd");
    let row = screen.getByText("Acme Ltd").closest("tr");
    expect(row).not.toBeNull();
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/discovery/clients/candidate-1/accept", { method: "POST" }));
    await screen.findByText("Client match accepted.");

    row = screen.getByText("Acme Ltd").closest("tr");
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Create client" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/discovery/clients/candidate-1/create-client", { method: "POST" }));
    await screen.findByText("Client created and linked.");

    row = screen.getByText("Acme Ltd").closest("tr");
    fireEvent.click(within(row as HTMLElement).getByRole("button", { name: "Dismiss" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith("/discovery/clients/candidate-1/dismiss", { method: "POST" }));
    expect(await screen.findByText("Candidate dismissed.")).toBeInTheDocument();
  });

  it("enables bulk acceptance only for proposed rows", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/setup/mode") return { mode: "msp" };
      if (init?.method === "POST") return {};
      if (path.startsWith("/discovery/clients")) return populatedResponse;
      return {};
    });

    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    expect(await screen.findByRole("button", { name: "Accept proposed" })).toBeEnabled();
    const ambiguousRow = screen.getByText("Ambiguous Co").closest("tr");
    expect(ambiguousRow).not.toBeNull();
    expect(within(ambiguousRow as HTMLElement).queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Accept proposed" }));
    await waitFor(() => expect(apiFetch).toHaveBeenCalledWith(
      "/discovery/clients/accept-proposed",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ candidate_ids: ["candidate-1"] }) })
    ));
  });

  it("shows an error banner when discovery fails", async () => {
    vi.mocked(apiFetch).mockImplementation(async (path: string, init?: RequestInit) => {
      if (path === "/setup/mode") return { mode: "msp" };
      if (path === "/discovery/clients/run" && init?.method === "POST") throw new Error("Provider unavailable");
      if (path.startsWith("/discovery/clients")) return emptyResponse;
      return {};
    });

    render(<MemoryRouter><ClientDiscovery /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Run discovery" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Provider unavailable");
  });
});
