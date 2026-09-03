import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api/client";
import type { ClientConnectorMapping, ConnectorInstance, PollSummary } from "../../api/types";
import { ConnectorInstances } from "../ConnectorInstances";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn()
}));

vi.mock("../../app/DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true, refresh: vi.fn() })
}));

const mockedApiFetch = vi.mocked(apiFetch);

const instance: ConnectorInstance = {
  connector_instance_id: "ci-halo-1",
  connector_type: "halopsa",
  display_name: "Acme Halo",
  client_id: "acme",
  credential_ref: "super-secret-credential-ref",
  config_json: JSON.stringify({ api_key: "also-secret" }),
  status: "active",
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z"
};

function configureApiFetch(summary?: PollSummary) {
  mockedApiFetch.mockImplementation((path, init) => {
    if (path === "/clients") {
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    }
    if (path === "/connector-instances") {
      return Promise.resolve([instance]) as ReturnType<typeof apiFetch>;
    }
    if (path === "/ingestion/sync-cursors") {
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    }
    if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") {
      return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    }
    if (path === "/connectors/instances/ci-halo-1/sync" && init?.method === "POST") {
      return Promise.resolve(summary) as ReturnType<typeof apiFetch>;
    }
    throw new Error(`Unexpected request: ${path}`);
  });
}

describe("ConnectorInstances sync action", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("POSTs the instance sync endpoint and renders a credential-free summary", async () => {
    const summary: PollSummary = {
      connector_instance_id: "ci-halo-1",
      pages_fetched: 2,
      written: 7,
      quarantined: 1,
      status: "degraded",
      reason: "one company was not mapped"
    };
    configureApiFetch(summary);

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

    expect(await screen.findByLabelText("Connector sync summary")).toHaveTextContent("Status: degraded");
    expect(screen.getByLabelText("Connector sync summary")).toHaveTextContent("Written: 7");
    expect(screen.getByLabelText("Connector sync summary")).toHaveTextContent("Quarantined: 1");
    expect(screen.getByLabelText("Connector sync summary")).toHaveTextContent("Pages fetched: 2");
    expect(screen.queryByText("super-secret-credential-ref")).not.toBeInTheDocument();
    expect(screen.queryByText("also-secret")).not.toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/instances/ci-halo-1/sync", { method: "POST" });
  });

  it("renders skipped_locked as a normal summary status", async () => {
    configureApiFetch({
      connector_instance_id: "ci-halo-1",
      pages_fetched: 0,
      written: 0,
      quarantined: 0,
      status: "skipped_locked",
      reason: "another poll is already running"
    });

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

    expect(await screen.findByLabelText("Connector sync summary")).toHaveTextContent("Status: skipped_locked");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders a 409 reason inline", async () => {
    configureApiFetch();
    const conflict = Object.assign(new Error("That action conflicts with the appliance's current state. Refresh and try again."), {
      status: 409,
      technicalDetail: "/connectors/instances/ci-halo-1/sync failed with HTTP 409: connector instance is not active"
    });
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([instance]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/instances/ci-halo-1/sync" && init?.method === "POST") return Promise.reject(conflict) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Sync now" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("connector instance is not active"));
    expect(screen.getByRole("alert")).not.toHaveTextContent("technicalDetail");
  });
});

describe("ConnectorInstances company mappings", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("discovers Halo companies and shows the manual-entry note when none are returned", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([instance]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/halopsa/clients?page=1&page_size=50") {
        return Promise.resolve({ result: { status: "not_configured", message: "Halo is not configured", count: 0 }, items: [] }) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Discover companies" }));

    expect(await screen.findByText("No companies returned.")).toBeInTheDocument();
    expect(screen.getByText("the provider returned no data; you can enter a company ID manually below.")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/halopsa/clients?page=1&page_size=50");
  });

  it("clears discovered companies when selecting a different instance", async () => {
    const secondInstance: ConnectorInstance = {
      ...instance,
      connector_instance_id: "ci-halo-2",
      display_name: "Beta Halo"
    };
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([instance, secondInstance]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1" || path === "/client-connector-mappings?connector_instance_id=ci-halo-2") {
        return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors/halopsa/clients?page=1&page_size=50") {
        return Promise.resolve({ result: { status: "success", message: "ok", count: 1 }, items: [{ id: "halo-company-42", name: "Acme Provider" }] }) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Discover companies" }));
    expect(await screen.findByRole("button", { name: "Use Acme Provider" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Beta Halo/ }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Use Acme Provider" })).not.toBeInTheDocument());
  });

  it("prefills a discovered company, creates a mapping, and refreshes mappings", async () => {
    const mapping: ClientConnectorMapping = {
      mapping_id: "mapping-1",
      connector_instance_id: "ci-halo-1",
      external_company_id: "halo-company-42",
      external_company_name: "Acme Provider",
      client_id: "acme",
      verified: 0,
      created_at: "now",
      updated_at: "now"
    };
    let mappingListCalls = 0;
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([instance]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") {
        mappingListCalls += 1;
        return Promise.resolve(mappingListCalls === 1 ? [] : [mapping]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connectors/halopsa/clients?page=1&page_size=50") {
        return Promise.resolve({ result: { status: "success", message: "ok", count: 1 }, items: [{ id: "halo-company-42", name: "Acme Provider" }] }) as ReturnType<typeof apiFetch>;
      }
      if (path === "/client-connector-mappings" && init?.method === "POST") return Promise.resolve(mapping) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Discover companies" }));
    fireEvent.click(await screen.findByRole("button", { name: "Use Acme Provider" }));
    fireEvent.change(screen.getByLabelText("WAIT client"), { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Create mapping" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Mapping created.");
    const createCall = mockedApiFetch.mock.calls.find(([path, init]) => path === "/client-connector-mappings" && init?.method === "POST");
    expect(createCall).toBeDefined();
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      connector_instance_id: "ci-halo-1",
      external_company_id: "halo-company-42",
      external_company_name: "Acme Provider",
      client_id: "acme"
    });
    expect(screen.getAllByText("Acme Provider").length).toBeGreaterThan(0);
    expect(mappingListCalls).toBe(1);
  });

  it("verifies an unverified mapping and shows the verified status chip", async () => {
    const unverified: ClientConnectorMapping = {
      mapping_id: "mapping-1",
      connector_instance_id: "ci-halo-1",
      external_company_id: "halo-company-42",
      external_company_name: "Acme Provider",
      client_id: "acme",
      verified: 0,
      created_at: "now",
      updated_at: "now"
    };
    const verified = { ...unverified, verified: 1 };
    let mappingListCalls = 0;
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([instance]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") {
        mappingListCalls += 1;
        return Promise.resolve(mappingListCalls === 1 ? [unverified] : [verified]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/client-connector-mappings/mapping-1/verify" && init?.method === "POST") return Promise.resolve(verified) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Halo/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Verify" }));

    expect(await screen.findByText("Verified")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/client-connector-mappings/mapping-1/verify", { method: "POST" });
    expect(mappingListCalls).toBe(1);
  });

  it("uses the ConnectWise endpoint and hides discovery for unsupported connector types", async () => {
    const connectWiseInstance: ConnectorInstance = { ...instance, connector_instance_id: "ci-connectwise-1", connector_type: "connectwise", display_name: "Acme ConnectWise" };
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([connectWiseInstance]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-connectwise-1") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/connectwise/companies?page=1&page_size=50") {
        return Promise.resolve({ result: { status: "success", message: "ok", count: 1 }, items: [{ id: "cw-company-42", name: "Acme ConnectWise" }] }) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    const firstRender = render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme ConnectWise/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Discover companies" }));
    expect((await screen.findAllByText("Acme ConnectWise")).length).toBeGreaterThan(0);
    expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/connectwise/companies?page=1&page_size=50");

    firstRender.unmount();
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([{ ...instance, connector_type: "autotask", display_name: "Acme Autotask" }]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<ConnectorInstances />);
    fireEvent.click(await screen.findByRole("button", { name: /Acme Autotask/ }));
    expect(screen.queryByRole("button", { name: "Discover companies" })).not.toBeInTheDocument();
  });
});

describe("ConnectorInstances connect flow", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") {
        return Promise.resolve([
          { client_id: "acme", name: "Acme", status: "active" },
          { client_id: "__quarantine__", name: "Quarantine", status: "quarantine" }
        ]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connector-instances") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  async function selectConnectWise() {
    await screen.findByRole("heading", { name: /Connect a system/ });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "connectwise" } });
  }

  function fillConnectWiseForm(apiVersion = "2024.1") {
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Acme ConnectWise" } });
    fireEvent.change(screen.getByLabelText("WAIT client (optional)"), { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    fireEvent.change(screen.getByLabelText("Service address"), { target: { value: "https://cw.example.test" } });
    fireEvent.change(screen.getByLabelText(/^API version/), { target: { value: apiVersion } });
    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "  acme-company  " } });
    fireEvent.change(screen.getByLabelText("Public key"), { target: { value: "  public-key  " } });
    fireEvent.change(screen.getByLabelText("Private key"), { target: { value: "  private-key  " } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "  connectwise-client-id  " } });
  }

  it("shows only the selected provider's fields and masks provider secrets", async () => {
    render(<ConnectorInstances />);

    expect(await screen.findByLabelText("Display name")).toBeInTheDocument();
    expect(screen.queryByLabelText("Client secret")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Service address")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^API version/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Private key")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Halo" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText("Client secret")).toHaveAttribute("type", "password");
    expect(screen.getAllByText("The value entered here is the credential. It is stored encrypted and never displayed again.")).toHaveLength(3);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    await selectConnectWise();
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "ConnectWise" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));

    expect(screen.getByLabelText(/^API version/)).toBeInTheDocument();
    expect(screen.getByLabelText("Private key")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Company")).toBeInTheDocument();
    expect(screen.queryByLabelText("Client secret")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tenant")).not.toBeInTheDocument();
    expect(screen.queryByText("Quarantine")).not.toBeInTheDocument();
  });

  it("stores credentials first, then creates an instance with only non-secret config", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174000");
    const created: ConnectorInstance = {
      ...instance,
      connector_instance_id: "ci-connectwise-1",
      connector_type: "connectwise",
      display_name: "Acme ConnectWise",
      client_id: "acme",
      credential_ref: "connector:connectwise:acme-connectwise:123e4567-e89b-12d3-a456-426614174000",
      config_json: JSON.stringify({ base_url: "https://cw.example.test", api_version: "2024.1" })
    };
    let listCalls = 0;
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") {
        return Promise.resolve([{ client_id: "acme", name: "Acme", status: "active" }]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connector-instances" && init?.method === "POST") {
        return Promise.resolve(created) as ReturnType<typeof apiFetch>;
      }
      if (path === "/connector-instances") {
        listCalls += 1;
        return Promise.resolve(listCalls === 1 ? [] : [created]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/secrets" && init?.method === "POST") return Promise.resolve(undefined) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-connectwise-1") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    await selectConnectWise();
    fillConnectWiseForm();
    fireEvent.click(screen.getByRole("button", { name: "Continue to verify and map" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect system" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Connected Acme ConnectWise.");
    const secretCall = mockedApiFetch.mock.calls.find(([path, init]) => path === "/secrets" && init?.method === "POST");
    const instanceCall = mockedApiFetch.mock.calls.find(([path, init]) => path === "/connector-instances" && init?.method === "POST");
    const secretCallIndex = mockedApiFetch.mock.calls.findIndex(([path, init]) => path === "/secrets" && init?.method === "POST");
    const instanceCallIndex = mockedApiFetch.mock.calls.findIndex(([path, init]) => path === "/connector-instances" && init?.method === "POST");
    expect(secretCall).toBeDefined();
    expect(instanceCall).toBeDefined();
    expect(secretCallIndex).toBeLessThan(instanceCallIndex);
    const secretPayload = JSON.parse(String(secretCall?.[1]?.body)) as { name: string; value: string };
    const instancePayload = JSON.parse(String(instanceCall?.[1]?.body)) as { credential_ref: string; config_json: string; client_id: string };
    expect(secretPayload).toEqual({
      name: "connector:connectwise:acme-connectwise:123e4567-e89b-12d3-a456-426614174000",
      value: JSON.stringify({ company: "acme-company", public_key: "public-key", private_key: "private-key", client_id: "connectwise-client-id" })
    });
    expect(instancePayload).toEqual({
      connector_type: "connectwise",
      display_name: "Acme ConnectWise",
      client_id: "acme",
      credential_ref: "connector:connectwise:acme-connectwise:123e4567-e89b-12d3-a456-426614174000",
      config_json: JSON.stringify({ base_url: "https://cw.example.test", api_version: "2024.1" })
    });
    expect(JSON.stringify(instancePayload)).not.toContain("acme-company");
    expect(JSON.stringify(instancePayload)).not.toContain("public-key");
    expect(JSON.stringify(instancePayload)).not.toContain("private-key");
    expect(JSON.stringify(instancePayload)).not.toContain("connectwise-client-id");
  });

  it("shows the demo secure-store notice and does not create an instance after a secret 403", async () => {
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/secrets" && init?.method === "POST") {
        return Promise.reject(Object.assign(new Error("forbidden"), { status: 403 })) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Demo Halo" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    fireEvent.change(screen.getByLabelText("Service address"), { target: { value: "https://halo.example.test" } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "halo-client-id" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "halo-secret" } });
    fireEvent.change(screen.getByLabelText("Tenant"), { target: { value: "halo-tenant" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to verify and map" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect system" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Secure credential storage is unavailable in demo mode");
    expect(mockedApiFetch.mock.calls.some(([path, init]) => path === "/connector-instances" && init?.method === "POST")).toBe(false);
  });

  it("surfaces an orphaned-secure-store warning when instance creation fails", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174001");
    const instanceError = new Error("instance creation failed");
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances" && init?.method === "POST") return Promise.reject(instanceError) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/secrets" && init?.method === "POST") return Promise.resolve(undefined) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Orphan Halo" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    fireEvent.change(screen.getByLabelText("Service address"), { target: { value: "https://halo.example.test" } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "halo-client-id" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "halo-secret" } });
    fireEvent.change(screen.getByLabelText("Tenant"), { target: { value: "halo-tenant" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to verify and map" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect system" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The credential was stored in the secure store but the connector instance could not be created: instance creation failed. Stored under reference connector:halopsa:orphan-halo:123e4567-e89b-12d3-a456-426614174001; it is unused until an instance references it. Retry to create it (a new credential will be stored)."
    );
    expect(mockedApiFetch.mock.calls.filter(([path, init]) => path === "/secrets" && init?.method === "POST")).toHaveLength(1);
    expect(mockedApiFetch.mock.calls.filter(([path, init]) => path === "/connector-instances" && init?.method === "POST")).toHaveLength(1);
  });

  it("blocks ConnectWise submission for an invalid API version", async () => {
    render(<ConnectorInstances />);
    await selectConnectWise();
    fillConnectWiseForm("not-a-version");

    expect(screen.getByRole("button", { name: "Continue to verify and map" })).toBeDisabled();
    expect(mockedApiFetch.mock.calls.some(([path, init]) => path === "/secrets" && init?.method === "POST")).toBe(false);
  });

  it("renders instance fields for each supported RMM", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    await screen.findByText("No connector instances are configured.");
    const provider = screen.getByLabelText("Provider");

    fireEvent.change(provider, { target: { value: "ninjaone" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Ninja" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText("Access token")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("NinjaOne organization map JSON")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "dattormm" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Datto" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText("Datto RMM site map JSON")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "ncentral" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "N-central" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText("N-central organization-unit map JSON")).toBeInTheDocument();
    expect(screen.getByLabelText("Provider service address")).toBeInTheDocument();
  });

  it("supports Microsoft 365 client-credential and static-token profile modes", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174002");
    const created: ConnectorInstance = {
      ...instance,
      connector_instance_id: "ci-m365-1",
      connector_type: "m365",
      display_name: "Acme Microsoft 365",
      credential_ref: "connector:m365:acme-microsoft-365:123e4567-e89b-12d3-a456-426614174002",
      config_json: "{}"
    };
    let instanceListCalls = 0;
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances" && init?.method === "POST") return Promise.resolve(created) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") {
        instanceListCalls += 1;
        return Promise.resolve(instanceListCalls === 1 ? [] : [created]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/ingestion/sync-cursors") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/secrets" && init?.method === "POST") return Promise.resolve(undefined) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances/ci-m365-1") return Promise.resolve(created) as ReturnType<typeof apiFetch>;
      if (path === "/client-connector-mappings?connector_instance_id=ci-m365-1") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    fireEvent.change(await screen.findByLabelText("Provider"), { target: { value: "m365" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Acme Microsoft 365" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.queryByLabelText("Service address")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Tenant ID")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Credential mode"), { target: { value: "static_token" } });
    expect(screen.getByLabelText("Access token")).toHaveAttribute("type", "password");
    fireEvent.change(screen.getByLabelText("Credential mode"), { target: { value: "client_credentials" } });
    fireEvent.change(screen.getByLabelText("Tenant ID"), { target: { value: "tenant-value" } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "application-value" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "credential-value" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to verify and map" }));
    fireEvent.click(screen.getByRole("button", { name: "Connect system" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Connected Acme Microsoft 365.");
    const secretCall = mockedApiFetch.mock.calls.find(([path, request]) => path === "/secrets" && request?.method === "POST");
    const instanceCall = mockedApiFetch.mock.calls.find(([path, request]) => path === "/connector-instances" && request?.method === "POST");
    expect(JSON.parse(String(secretCall?.[1]?.body))).toEqual({
      name: created.credential_ref,
      value: JSON.stringify({ mode: "client_credentials", tenant_id: "tenant-value", client_id: "application-value", client_secret: "credential-value" })
    });
    expect(JSON.parse(String(instanceCall?.[1]?.body))).toMatchObject({
      connector_type: "m365",
      config_json: "{}"
    });
    expect(JSON.stringify(instanceCall?.[1]?.body)).not.toContain("credential-value");
  });
});
