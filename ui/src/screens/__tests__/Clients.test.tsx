import { act, fireEvent, render as rtlRender, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, apiFetch } from "../../api/client";
import type { ClientDirectoryEntry } from "../../api/types";
import { Clients } from "../Clients";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn(),
  ApiRequestError: class ApiRequestError extends Error {
    status?: number;
    constructor(message: string, _technicalDetail: string, status?: number) {
      super(message);
      this.status = status;
    }
  }
}));

vi.mock("../../app/DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true })
}));

const mockedApiFetch = vi.mocked(apiFetch);

function render(ui: Parameters<typeof rtlRender>[0]) {
  return rtlRender(<MemoryRouter>{ui}</MemoryRouter>);
}

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("Clients", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("renders active and archived clients while excluding quarantine", async () => {
    mockedApiFetch.mockImplementation(() => Promise.resolve([
      { client_id: "acme", name: "Acme", status: "active" },
      { client_id: "legacy", name: "Legacy Co", status: "archived" },
      { client_id: "__quarantine__", name: "Quarantine", status: "quarantine" }
    ]) as ReturnType<typeof apiFetch>);

    render(<Clients />);

    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    expect(screen.getByText("Legacy Co")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.queryByText("__quarantine__")).not.toBeInTheDocument();
  });

  it("shows loading and empty states", async () => {
    const pending = deferred<ClientDirectoryEntry[]>();
    mockedApiFetch.mockImplementation(() => pending.promise as ReturnType<typeof apiFetch>);

    render(<Clients />);

    expect(screen.getByText("Loading Clients…")).toBeInTheDocument();
    expect(screen.getByText("Loading Clients…").parentElement).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      pending.resolve([]);
    });

    expect(await screen.findByText("No clients are visible.")).toBeInTheDocument();
  });

  it("shows a retryable error", async () => {
    mockedApiFetch.mockImplementation(() => Promise.reject(new Error("Clients unavailable.")) as ReturnType<typeof apiFetch>);

    render(<Clients />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Clients unavailable."));
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("loads client detail and mappings when a client is selected", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "2026-01-01", updated_at: "2026-01-02" }) as ReturnType<typeof apiFetch>;
      return Promise.resolve([{ mapping_id: "map-1", connector_instance_id: "halo", external_company_id: "ext-1", external_company_name: "Acme Ltd", client_id: "acme", verified: 0, created_at: "now", updated_at: "now" }]) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });

    expect(await screen.findByText("Client detail")).toBeInTheDocument();
    expect(screen.getByText("Acme Ltd")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme");
  });

  it("switches to the read-only environment and resolves relationships", async () => {
    const graph = {
      refs: [
        { id: 1, client_id: "acme", entity_type: "ticket", source_system: "halo", external_id: "T-42", display_name: "Printer outage", provenance: "ticket-seed" },
        { id: 2, client_id: "acme", entity_type: "user", source_system: "halo", external_id: "U-7", display_name: "Alex User", provenance: "ticket-seed" }
      ],
      links: [{ id: 3, client_id: "acme", from_ref_id: 2, to_ref_id: 1, link_type: "requested_by", provenance: "ticket-seed" }]
    };
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "2026-01-01", updated_at: "2026-01-02" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/graph") return Promise.resolve(graph) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    expect(screen.getByRole("tab", { name: "Details" })).toHaveAttribute("aria-selected", "true");
    await act(async () => { screen.getByRole("tab", { name: "Environment" }).click(); });

    expect((await screen.findAllByText("Printer outage")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Alex User")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("requested_by").length).toBeGreaterThan(0);
    expect(screen.getByRole("tabpanel").textContent).toContain("Alex User");
    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/graph");
  });

  it("shows graph empty and not-found states without crashing", async () => {
    let graphResponse: unknown = { refs: [], links: [] };
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/graph") return (graphResponse instanceof Error ? Promise.reject(graphResponse) : Promise.resolve(graphResponse)) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Environment" }).click(); });
    expect(await screen.findByText("No environment entities are linked to this client yet.")).toBeInTheDocument();

    graphResponse = Object.assign(new Error("missing"), { status: 404 });
    await act(async () => { screen.getByRole("tab", { name: "Details" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Environment" }).click(); });
    expect(await screen.findByRole("alert")).toHaveTextContent("environment is no longer available");
  });

  it("loads baseline versions, groups drift, and accepts a candidate", async () => {
    const baseline = {
      baseline_id: "baseline-2",
      client_id: "acme",
      version: 2,
      generated_at: "2026-09-01T00:00:00Z",
      accepted: false,
      source_coverage: { microsoft_posture: "ready" },
      summary: {},
      sections: {}
    };
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/baselines" && init?.method === "POST") return Promise.resolve(baseline) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/baselines/2/accept") return Promise.resolve({ ...baseline, accepted: true }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/baselines") return Promise.resolve([baseline]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/drift") return Promise.resolve({
        client_id: "acme",
        baseline_version: 1,
        baseline_generated_at: "2026-08-31T00:00:00Z",
        generated_at: "2026-09-01T00:00:00Z",
        unchanged: false,
        findings: [{ domain: "microsoft_posture", path: "microsoft_posture.summary.noncompliant_devices", classification: "worsened", previous: 1, current: 2, correlation_label: "no matching approved change found" }],
        source_coverage: { microsoft_posture: "ready" },
        fresh_summary: {}
      }) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Baseline" }).click(); });

    expect(await screen.findByText("no matching approved change found")).toBeInTheDocument();
    expect(screen.getByText("worsened")).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Accept" }).click(); });
    expect(await screen.findByText("Current")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/baselines/2/accept", { method: "POST" });
  });

  it("applies environment filters, resets paging, and navigates pages", async () => {
    const graph = {
      refs: [
        { id: 1, client_id: "acme", entity_type: "device", source_system: "rmm", external_id: "D-1", display_name: "Laptop", provenance: "rmm-seed", last_seen: "2020-01-01T00:00:00Z" },
        { id: 2, client_id: "acme", entity_type: "user", source_system: "m365", external_id: "U-1", display_name: "Avery", provenance: "m365-seed" }
      ],
      links: [{ id: 3, client_id: "acme", from_ref_id: 2, to_ref_id: 1, link_type: "owns", provenance: "m365-seed" }],
      total_refs: 12,
      total_links: 8,
      has_more: true
    };
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      return Promise.resolve(graph) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Environment" }).click(); });
    expect(await screen.findByText("12 entities · 8 relationships")).toBeInTheDocument();

    await act(async () => { screen.getByRole("button", { name: "Next" }).click(); });
    expect(await screen.findByText("Page 2")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/graph?offset=100");
    expect(screen.getByRole("button", { name: "Previous" })).not.toBeDisabled();

    await act(async () => { fireEvent.change(screen.getByLabelText("Environment type filter"), { target: { value: "device" } }); });
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/graph?entity_type=device"));
    await screen.findByRole("option", { name: "rmm" });
    await act(async () => { fireEvent.change(screen.getByLabelText("Environment source filter"), { target: { value: "rmm" } }); });
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/graph?entity_type=device&source_system=rmm"));
    await screen.findByRole("option", { name: "owns" });
    await act(async () => { fireEvent.change(screen.getByLabelText("Environment relationship filter"), { target: { value: "owns" } }); });
    expect(await screen.findByText("Page 1")).toBeInTheDocument();
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/graph?entity_type=device&source_system=rmm&link_type=owns"));
  });

  it("renders stale and fallback environment values and handles inventory syncs", async () => {
    const graph = {
      refs: [{ id: 1, client_id: "acme", entity_type: "device", source_system: "rmm", external_id: "D-1", display_name: "", provenance: "collector", last_seen: "2020-01-01T00:00:00Z" }],
      links: [],
      has_more: false
    };
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/graph/sync-rmm") return Promise.resolve({ devices: 1, alerts: 2, links: 1, errors: ["RMM warning"] }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/graph/sync-m365") return Promise.resolve({ users: 1, devices: 2, links: 3, errors: ["M365 warning"] }) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme/graph" && init?.method === "POST") return Promise.resolve(graph) as ReturnType<typeof apiFetch>;
      return Promise.resolve(graph) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Environment" }).click(); });
    expect((await screen.findAllByText("D-1")).length).toBeGreaterThan(0);
    expect(screen.getByText("Stale")).toBeInTheDocument();
    expect(screen.getByText("1 entities · 0 relationships")).toBeInTheDocument();
    expect(screen.getByText("No relationships are linked to these entities.")).toBeInTheDocument();

    await act(async () => { screen.getByRole("button", { name: "Sync from RMM" }).click(); });
    expect(await screen.findByText("1 device synced")).toBeInTheDocument();
    expect(screen.getByText("2 alerts synced")).toBeInTheDocument();
    expect(screen.getByText("Needs attention: RMM warning")).toBeInTheDocument();

    await act(async () => { screen.getByRole("button", { name: "Sync from Microsoft 365" }).click(); });
    expect(await screen.findByText("1 user synced")).toBeInTheDocument();
    expect(screen.getByText("2 devices synced")).toBeInTheDocument();
    expect(screen.getByText("Needs attention: M365 warning")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme/graph/sync-m365", { method: "POST" });
  });

  it("shows sync-specific errors for unavailable adapters", async () => {
    const graph = { refs: [], links: [], total_refs: 0, total_links: 0, has_more: false };
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path.endsWith("sync-rmm")) return Promise.reject(new Error("RMM offline")) as ReturnType<typeof apiFetch>;
      if (path.endsWith("sync-m365")) return Promise.reject(new ApiRequestError("conflict", "conflict", 409)) as ReturnType<typeof apiFetch>;
      return Promise.resolve(graph) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Environment" }).click(); });
    await screen.findByText("No environment entities are linked to this client yet.");
    await act(async () => { screen.getByRole("button", { name: "Sync from RMM" }).click(); });
    expect(await screen.findByText("RMM offline")).toBeInTheDocument();
    await act(async () => { screen.getByRole("button", { name: "Sync from Microsoft 365" }).click(); });
    expect(await screen.findByText(/Microsoft 365 sync is unavailable/)).toBeInTheDocument();
  });

  it("creates a client and refreshes the directory", async () => {
    let listCalls = 0;
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients" && init?.method === "POST") return Promise.resolve({ client_id: "new-client", name: "New Client", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients") {
        listCalls += 1;
        return Promise.resolve(listCalls === 1 ? [] : [{ client_id: "new-client", name: "New Client", status: "active" }]) as ReturnType<typeof apiFetch>;
      }
      return Promise.resolve({ client_id: "new-client", name: "New Client", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("No clients are visible.");
    await act(async () => { screen.getByRole("button", { name: "New client" }).click(); });
    await act(async () => {
      const inputs = screen.getAllByRole("textbox");
      fireEvent.change(inputs[0], { target: { value: "new-client" } });
      fireEvent.change(inputs[1], { target: { value: "New Client" } });
      fireEvent.submit(screen.getByRole("button", { name: "Create client" }).closest("form")!);
    });
    expect(await screen.findByText("Client created.")).toBeInTheDocument();
    expect(listCalls).toBeGreaterThan(1);
  });

  it("patches status and verifies an unverified mapping", async () => {
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients" && init?.method === "PATCH") return Promise.resolve({ client_id: "acme", name: "Acme", status: "archived", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme") return Promise.resolve({ client_id: "acme", name: "Acme", status: "active", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings") return Promise.resolve([{ mapping_id: "map-1", connector_instance_id: "halo", external_company_id: "ext-1", external_company_name: "Acme Ltd", client_id: "acme", verified: 0, created_at: "now", updated_at: "now" }]) as ReturnType<typeof apiFetch>;
      if (path === "/clients/acme" && init?.method === "PATCH") return Promise.resolve({ client_id: "acme", name: "Acme", status: "archived", created_at: "now", updated_at: "now" }) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings/map-1/verify") return Promise.resolve({ mapping_id: "map-1", connector_instance_id: "halo", external_company_id: "ext-1", external_company_name: "Acme Ltd", client_id: "acme", verified: 1, created_at: "now", updated_at: "now", retenanted_count: 0 }) as ReturnType<typeof apiFetch>;
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    });

    render(<Clients />);
    await screen.findByText("Acme");
    await act(async () => { screen.getByRole("button", { name: "Acme" }).click(); });
    await screen.findByRole("button", { name: "Verify" });
    await act(async () => { screen.getByRole("button", { name: "Verify" }).click(); });
    expect(await screen.findByText(/Mapping verified/)).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/client-connector-mappings/map-1/verify", { method: "POST" });
    await act(async () => { screen.getByRole("button", { name: "Edit client" }).click(); });
    fireEvent.change(screen.getByRole("combobox"), { target: { value: "archived" } });
    await act(async () => { screen.getByRole("button", { name: "Save changes" }).click(); });
    expect(mockedApiFetch).toHaveBeenCalledWith("/clients/acme", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "archived" })
    });
    expect(await screen.findByText("Client updated.")).toBeInTheDocument();
  });
});
