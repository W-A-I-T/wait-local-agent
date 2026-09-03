import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "../src/app/Sidebar";
import type { ClientConnectorMapping, QuarantinedTicket, UnmappedRecord } from "../src/api/types";
import { SyncReconciliation } from "../src/screens/SyncReconciliation";

const dashboard = vi.hoisted(() => ({
  role: "admin" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const instances = [{
  connector_instance_id: "ci-halo-1",
  connector_type: "halopsa",
  display_name: "Acme Halo",
  client_id: "acme",
  credential_ref: null,
  config_json: "{}",
  status: "active",
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z"
}];

const cursors = [
  cursor("ci-halo-1", "tickets", "idle", "cursor-42"),
  cursor("ci-halo-1", "companies", "syncing", "cursor-43"),
  cursor("ci-halo-1", "assets", "degraded", null),
  cursor("ci-halo-unknown", "users", "failed", "cursor-44")
];

const record: UnmappedRecord = {
  record_id: "unmapped-1",
  connector_instance_id: "ci-halo-1",
  external_company_id: "external-company-42",
  external_id: "ticket-99",
  record_type: "ticket",
  payload_digest: "digest-abc",
  reason: "no_verified_mapping",
  created_at: "2026-08-16T09:30:00Z",
  resolved_at: null
};

const mapping: ClientConnectorMapping = {
  mapping_id: "mapping-1",
  connector_instance_id: "ci-halo-1",
  external_company_id: "external-company-42",
  external_company_name: "Acme External",
  client_id: "acme",
  verified: 0,
  created_at: "2026-08-16T08:00:00Z",
  updated_at: "2026-08-16T08:00:00Z"
};

const quarantinedTicket: QuarantinedTicket = {
  id: "ticket-quarantine-1",
  client: "Unmapped / Quarantine",
  subject: "Ticket awaiting mapping",
  body: "Ticket body",
  priority: "high",
  status: "quarantined",
  client_id: "__quarantine__",
  requester_id: "requester-1",
  created_at: "2026-08-16T09:45:00Z",
  updated_at: "2026-08-16T09:45:00Z",
  source_system: "halopsa",
  connector_instance_id: "ci-halo-1",
  external_id: "ticket-external-1",
  external_client_id: "external-company-42"
};

const clients = [
  { client_id: "acme", name: "Acme MSP", status: "active", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" },
  { client_id: "inactive-client", name: "Inactive Client", status: "inactive", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" },
  { client_id: "__quarantine__", name: "Unmapped / Quarantine", status: "quarantine", created_at: "2026-08-01T00:00:00Z", updated_at: "2026-08-01T00:00:00Z" }
];

afterEach(() => {
  dashboard.role = "admin";
  dashboard.roleResolved = true;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Sync / Reconciliation screen", () => {
  it("renders sync health, connector labels, status badges, and quarantine records", async () => {
    const fetchMock = stubData({ records: [record] });

    render(
      <MemoryRouter>
        <SyncReconciliation />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Sync Health" })).toBeInTheDocument();
    expect(screen.getAllByText("Acme Halo")).not.toHaveLength(0);
    expect(screen.getAllByText("halopsa")).not.toHaveLength(0);
    expect(screen.getByText("Idle")).toBeInTheDocument();
    expect(screen.getByText("Syncing")).toBeInTheDocument();
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("Failed — needs attention")).toBeInTheDocument();
    expect(screen.getByText("cursor-42")).toBeInTheDocument();
    expect(screen.getByText("external-company-42")).toBeInTheDocument();
    expect(screen.getByText("no_verified_mapping")).toBeInTheDocument();
    expect(screen.getByText("digest-abc")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sync / Reconciliation" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(
      expect.arrayContaining(["/ingestion/sync-cursors", "/ingestion/unmapped", "/connector-instances"])
    );
  });

  it("confirms resolve, posts only the resolve action, refetches, and removes the resolved row", async () => {
    let currentRecords = [record];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/ingestion/sync-cursors") return jsonResponse(cursors);
      if (path === "/ingestion/unmapped") return jsonResponse(currentRecords);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings") return jsonResponse([]);
      if (path === "/clients") return jsonResponse(clients);
      if (path === "/ingestion/unmapped/unmapped-1/resolve") {
        expect(init?.method).toBe("POST");
        currentRecords = [{ ...record, resolved_at: "2026-08-16T10:00:00Z" }];
        return jsonResponse(currentRecords[0]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    await screen.findByText("external-company-42");

    fireEvent.click(screen.getByRole("button", { name: "Resolve record unmapped-1" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Mark this record as reviewed?");
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/resolve"))).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.queryByText("external-company-42")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Record marked as reviewed.");
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/ingestion/unmapped")).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/resolve"))).toHaveLength(1);
    expect(fetchMock.mock.calls
      .filter(([input]) => String(input).includes("/resolve"))[0]?.[1])
      .toEqual(expect.objectContaining({ method: "POST" }));
  });

  it("surfaces a resolve error and keeps the record available for retry", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/ingestion/sync-cursors") return jsonResponse(cursors);
      if (path === "/ingestion/unmapped") return jsonResponse([record]);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings") return jsonResponse([]);
      if (path === "/clients") return jsonResponse(clients);
      if (path === "/ingestion/unmapped/unmapped-1/resolve") {
        expect(init?.method).toBe("POST");
        return new Response(JSON.stringify({ detail: "resolve unavailable" }), { status: 503 });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    await screen.findByText("external-company-42");
    fireEvent.click(screen.getByRole("button", { name: "Resolve record unmapped-1" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.getByText("external-company-42")).toBeInTheDocument();
  });

  it("shows empty and loading failure states", async () => {
    const emptyFetch = stubData({ records: [], cursorRows: [] });
    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    expect(await screen.findByText("All connectors mapped — nothing quarantined.")).toBeInTheDocument();
    expect(screen.getByText("No sync cursors are recorded.")).toBeInTheDocument();
    expect(screen.getByText("No mappings awaiting verification.")).toBeInTheDocument();
    expect(emptyFetch).toHaveBeenCalledWith("/ingestion/unmapped", expect.anything());

    vi.unstubAllGlobals();
    const errorFetch = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/ingestion/sync-cursors") {
        return new Response(JSON.stringify({ detail: "sync unavailable" }), { status: 503 });
      }
      return jsonResponse([]);
    });
    vi.stubGlobal("fetch", errorFetch);
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("confirms a pending mapping, refetches, and surfaces the re-tenant count", async () => {
    let currentMappings = [mapping];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/ingestion/sync-cursors") return jsonResponse(cursors);
      if (path === "/ingestion/unmapped") return jsonResponse([]);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings") return jsonResponse(currentMappings);
      if (path === "/clients") return jsonResponse(clients);
      if (path === "/client-connector-mappings/mapping-1/verify") {
        expect(init?.method).toBe("POST");
        currentMappings = [{ ...mapping, verified: 1 }];
        return jsonResponse({ ...currentMappings[0], retenanted_count: 3 });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    await screen.findByText("Acme External");
    fireEvent.click(screen.getByRole("button", { name: "Confirm mapping mapping-1" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("Confirm this connector mapping?");
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("status")).toHaveTextContent(
      "Mapping verified — 3 quarantined tickets re-tenanted."
    );
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/client-connector-mappings")).toHaveLength(2);
    expect(screen.getByText("No mappings awaiting verification.")).toBeInTheDocument();
  });

  it("keeps a pending mapping and shows the friendly danger notice on a 409 verify", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/ingestion/sync-cursors") return jsonResponse(cursors);
      if (path === "/ingestion/unmapped") return jsonResponse([]);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings") return jsonResponse([mapping]);
      if (path === "/clients") return jsonResponse(clients);
      if (path === "/client-connector-mappings/mapping-1/verify") {
        expect(init?.method).toBe("POST");
        return jsonResponse({ detail: "mapping state changed" }, 409);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    await screen.findByText("Acme External");
    fireEvent.click(screen.getByRole("button", { name: "Confirm mapping mapping-1" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That action conflicts with the appliance's current state. Refresh and try again."
    );
    expect(screen.getByText("Acme External")).toBeInTheDocument();
  });

  it("reclassifies a quarantined ticket with the selected client and refetches", async () => {
    let currentTickets = [quarantinedTicket];
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/ingestion/sync-cursors") return jsonResponse(cursors);
      if (path === "/ingestion/unmapped") return jsonResponse([]);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings") return jsonResponse([]);
      if (path === "/clients") return jsonResponse([...clients, { ...clients[0], client_id: "beta", name: "Beta Client" }]);
      if (path === "/ingestion/quarantined?connector_instance_id=ci-halo-1") return jsonResponse(currentTickets);
      if (path === "/ingestion/quarantined/ticket-quarantine-1/reclassify") {
        expect(init?.method).toBe("POST");
        expect(JSON.parse(String(init?.body))).toEqual({ client_id: "beta" });
        currentTickets = [];
        return jsonResponse({ ticket_id: quarantinedTicket.id, client_id: "beta" });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    await screen.findByText("No mappings awaiting verification.");
    fireEvent.change(screen.getByRole("combobox", { name: "Quarantined ticket connector" }), { target: { value: "ci-halo-1" } });
    await screen.findByText("Ticket awaiting mapping");
    fireEvent.click(screen.getByRole("button", { name: "Reclassify ticket ticket-quarantine-1" }));
    fireEvent.change(screen.getByRole("combobox", { name: "Target client" }), { target: { value: "beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(screen.queryByText("Ticket awaiting mapping")).not.toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveTextContent("Quarantined ticket reclassified.");
    expect(fetchMock.mock.calls.filter(([input]) => String(input) === "/ingestion/quarantined?connector_instance_id=ci-halo-1")).toHaveLength(2);
  });

  it("keeps a quarantined ticket and shows the friendly danger notice on a 400 reclassify", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/ingestion/sync-cursors") return jsonResponse(cursors);
      if (path === "/ingestion/unmapped") return jsonResponse([]);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings") return jsonResponse([]);
      if (path === "/clients") return jsonResponse(clients);
      if (path === "/ingestion/quarantined?connector_instance_id=ci-halo-1") return jsonResponse([quarantinedTicket]);
      if (path === "/ingestion/quarantined/ticket-quarantine-1/reclassify") {
        expect(init?.method).toBe("POST");
        return jsonResponse({ detail: "inactive client" }, 400);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><SyncReconciliation /></MemoryRouter>);
    await screen.findByText("No mappings awaiting verification.");
    fireEvent.change(screen.getByRole("combobox", { name: "Quarantined ticket connector" }), { target: { value: "ci-halo-1" } });
    await screen.findByText("Ticket awaiting mapping");
    fireEvent.click(screen.getByRole("button", { name: "Reclassify ticket ticket-quarantine-1" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The request could not be completed. Check the details and try again."
    );
    expect(screen.getByText("Ticket awaiting mapping")).toBeInTheDocument();
  });

  it("does not load or expose the surface to viewers", async () => {
    dashboard.role = "viewer";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <SyncReconciliation />
        <Sidebar />
      </MemoryRouter>
    );

    expect(screen.getByText("Administrator role required to view sync and reconciliation details.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sync / Reconciliation" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function cursor(
  connectorInstanceId: string,
  cursorType: string,
  status: "idle" | "syncing" | "degraded" | "failed",
  cursorValue: string | null
) {
  return {
    connector_instance_id: connectorInstanceId,
    cursor_type: cursorType,
    cursor_value: cursorValue,
    status,
    last_synced_at: "2026-08-16T09:00:00Z",
    updated_at: "2026-08-16T09:30:00Z"
  };
}

function stubData({ records, cursorRows = cursors }: { records: Array<typeof record>; cursorRows?: typeof cursors }) {
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/ingestion/sync-cursors") return jsonResponse(cursorRows);
    if (path === "/ingestion/unmapped") return jsonResponse(records);
    if (path === "/connector-instances") return jsonResponse(instances);
    if (path === "/client-connector-mappings") return jsonResponse([]);
    if (path === "/clients") return jsonResponse(clients);
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
