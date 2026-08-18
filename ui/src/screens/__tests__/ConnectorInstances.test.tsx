import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api/client";
import type { ConnectorInstance, PollSummary } from "../../api/types";
import { ConnectorInstances } from "../ConnectorInstances";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn()
}));

vi.mock("../../app/DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true })
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
      if (path === "/client-connector-mappings") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });
  });

  async function selectConnectWise() {
    await screen.findByRole("heading", { name: "Connect a system" });
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "connectwise" } });
  }

  function fillConnectWiseForm(apiVersion = "2024.1") {
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Acme ConnectWise" } });
    fireEvent.change(screen.getByLabelText("WAIT client (optional)"), { target: { value: "acme" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://cw.example.test" } });
    fireEvent.change(screen.getByLabelText(/^API version/), { target: { value: apiVersion } });
    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "  acme-company  " } });
    fireEvent.change(screen.getByLabelText("Public key"), { target: { value: "  public-key  " } });
    fireEvent.change(screen.getByLabelText("Private key"), { target: { value: "  private-key  " } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "  connectwise-client-id  " } });
  }

  it("shows only the selected provider's fields and masks provider secrets", async () => {
    render(<ConnectorInstances />);

    expect(await screen.findByLabelText("Client secret")).toHaveAttribute("type", "password");
    expect(screen.getByLabelText("Base URL")).toBeInTheDocument();
    expect(screen.queryByLabelText(/^API version/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Private key")).not.toBeInTheDocument();

    await selectConnectWise();

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

  it("shows the demo vault notice and does not create an instance after a secret 403", async () => {
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/secrets" && init?.method === "POST") {
        return Promise.reject(Object.assign(new Error("forbidden"), { status: 403 })) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    await screen.findByLabelText("Client secret");
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Demo Halo" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://halo.example.test" } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "halo-client-id" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "halo-secret" } });
    fireEvent.change(screen.getByLabelText("Tenant"), { target: { value: "halo-tenant" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect system" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Secret storage is unavailable in demo mode");
    expect(mockedApiFetch.mock.calls.some(([path, init]) => path === "/connector-instances" && init?.method === "POST")).toBe(false);
  });

  it("surfaces an orphaned-vault warning when instance creation fails", async () => {
    vi.spyOn(crypto, "randomUUID").mockReturnValue("123e4567-e89b-12d3-a456-426614174001");
    const instanceError = new Error("instance creation failed");
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/clients") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances" && init?.method === "POST") return Promise.reject(instanceError) as ReturnType<typeof apiFetch>;
      if (path === "/connector-instances") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/secrets" && init?.method === "POST") return Promise.resolve(undefined) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<ConnectorInstances />);
    await screen.findByLabelText("Client secret");
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Orphan Halo" } });
    fireEvent.change(screen.getByLabelText("Base URL"), { target: { value: "https://halo.example.test" } });
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "halo-client-id" } });
    fireEvent.change(screen.getByLabelText("Client secret"), { target: { value: "halo-secret" } });
    fireEvent.change(screen.getByLabelText("Tenant"), { target: { value: "halo-tenant" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect system" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The credential was stored in the vault but the connector instance could not be created: instance creation failed. Retry to create it (a new credential will be stored)."
    );
    expect(mockedApiFetch.mock.calls.filter(([path, init]) => path === "/secrets" && init?.method === "POST")).toHaveLength(1);
    expect(mockedApiFetch.mock.calls.filter(([path, init]) => path === "/connector-instances" && init?.method === "POST")).toHaveLength(1);
  });

  it("blocks ConnectWise submission for an invalid API version", async () => {
    render(<ConnectorInstances />);
    await selectConnectWise();
    fillConnectWiseForm("not-a-version");

    expect(screen.getByRole("button", { name: "Connect system" })).toBeDisabled();
    expect(mockedApiFetch.mock.calls.some(([path, init]) => path === "/secrets" && init?.method === "POST")).toBe(false);
  });
});
