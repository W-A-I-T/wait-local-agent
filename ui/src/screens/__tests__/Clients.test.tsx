import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api/client";
import type { ClientDirectoryEntry } from "../../api/types";
import { Clients } from "../Clients";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn()
}));

vi.mock("../../app/DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true })
}));

const mockedApiFetch = vi.mocked(apiFetch);

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

  it("switches to the read-only operational graph and resolves relationships", async () => {
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
    await act(async () => { screen.getByRole("tab", { name: "Operational graph" }).click(); });

    expect((await screen.findAllByText("Printer outage")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Alex User")).length).toBeGreaterThan(0);
    expect(screen.getByText("requested_by")).toBeInTheDocument();
    expect(screen.getByRole("tabpanel").textContent).toContain("Alex User");
    expect(screen.getByRole("tabpanel").querySelector("button")).toBeNull();
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
    await act(async () => { screen.getByRole("tab", { name: "Operational graph" }).click(); });
    expect(await screen.findByText("No operational-graph entities are linked to this client yet.")).toBeInTheDocument();

    graphResponse = Object.assign(new Error("missing"), { status: 404 });
    await act(async () => { screen.getByRole("tab", { name: "Details" }).click(); });
    await act(async () => { screen.getByRole("tab", { name: "Operational graph" }).click(); });
    expect(await screen.findByRole("alert")).toHaveTextContent("operational graph is no longer available");
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
