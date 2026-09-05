import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ConnectorInstances } from "../src/screens/ConnectorInstances";
import { Sidebar } from "../src/app/Sidebar";

const dashboard = vi.hoisted(() => ({
  role: "admin" as "admin" | "viewer",
  roleResolved: true,
  refresh: vi.fn()
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

const instances = [{
  connector_instance_id: "ci-halo-1",
  connector_type: "halopsa",
  display_name: "Acme Halo",
  client_id: "acme",
  credential_ref: "super-secret-credential-ref",
  config_json: JSON.stringify({ api_key: "also-secret" }),
  status: "active",
  created_at: "2026-08-15T10:00:00Z",
  updated_at: "2026-08-15T10:00:00Z"
}, {
  connector_instance_id: "ci-syncro-1",
  connector_type: "syncro",
  display_name: "Shared Syncro",
  client_id: null,
  credential_ref: null,
  config_json: "{}",
  status: "error",
  created_at: "2026-08-15T11:00:00Z",
  updated_at: "2026-08-15T11:00:00Z"
}];

const mappings = [{
  mapping_id: "map-1",
  connector_instance_id: "ci-halo-1",
  external_company_id: "halo-company-42",
  external_company_name: "Acme Holdings",
  client_id: "acme",
  verified: 1,
  created_at: "2026-08-15T10:01:00Z",
  updated_at: "2026-08-15T10:01:00Z"
}, {
  mapping_id: "map-2",
  connector_instance_id: "ci-halo-1",
  external_company_id: "halo-company-99",
  external_company_name: null,
  client_id: "contoso",
  verified: 0,
  created_at: "2026-08-15T10:02:00Z",
  updated_at: "2026-08-15T10:02:00Z"
}];

afterEach(() => {
  dashboard.role = "admin";
  dashboard.roleResolved = true;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Connector Instances screen", () => {
  it("loads instances and mappings with presence-only credentials and verification badges", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path === "/connector-instances") return jsonResponse(instances);
      if (path === "/client-connector-mappings?connector_instance_id=ci-halo-1") return jsonResponse(mappings);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <ConnectorInstances />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Configured instances" })).toBeInTheDocument();
    expect(screen.getByText("Acme Halo")).toBeInTheDocument();
    expect(screen.getByText("Acme Halo").closest("tr")).toHaveTextContent("Configured");
    expect(screen.getByText("Shared Syncro").closest("tr")).toHaveTextContent("Not configured");
    expect(screen.getByText("Unassigned")).toBeInTheDocument();
    expect(screen.queryByText("super-secret-credential-ref")).not.toBeInTheDocument();
    expect(screen.queryByText("also-secret")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connector instances" })).toHaveAttribute("href", "/integrations/connector-instances");

    fireEvent.click(screen.getByRole("button", { name: /Acme Halo/ }));

    expect(await screen.findByText("Acme Holdings")).toBeInTheDocument();
    expect(screen.getByText("Verified")).toBeInTheDocument();
    expect(screen.getByText("Unverified")).toBeInTheDocument();
    expect(screen.getByText("halo-company-99")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/client-connector-mappings?connector_instance_id=ci-halo-1", expect.anything());
    expect(fetchMock.mock.calls.every(([, init]) => !init || !("method" in init) || init.method === undefined || init.method === "GET")).toBe(true);
  });

  it("loads row detail and patches only changed connector fields", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/connector-instances") return jsonResponse(instances.slice(0, 1));
      if (path === "/clients") return jsonResponse([{ client_id: "acme", name: "Acme", status: "active" }]);
      if (path === "/connector-instances/ci-halo-1" && !init?.method) return jsonResponse(instances[0]);
      if (path === "/connector-instances/ci-halo-1" && init?.method === "PATCH") {
        return jsonResponse({ ...instances[0], display_name: "Acme Halo Updated" });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectorInstances />);

    await screen.findByRole("heading", { name: "Configured instances" });
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(await screen.findByLabelText("Edit connector display name"), { target: { value: "Acme Halo Updated" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/connector-instances/ci-halo-1",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ display_name: "Acme Halo Updated" }) })
    ));
    expect(fetchMock.mock.calls.some(([input, init]) => String(input) === "/connector-instances/ci-halo-1" && !init?.method)).toBe(true);
  });

  it("shows the read-only error state", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/connector-instances") {
        return new Response(JSON.stringify({ detail: "instances unavailable" }), { status: 503 });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectorInstances />);

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    await waitFor(() => expect(screen.queryByText("Loading Connector Instances…")).not.toBeInTheDocument());
  });

  it("does not load or expose the admin surface to viewers", () => {
    dashboard.role = "viewer";
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <ConnectorInstances />
        <Sidebar />
      </MemoryRouter>
    );

    expect(screen.getByText("Administrator role required to view connector instances.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Connector instances" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders the instance form fields for each supported PSA", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/connector-instances") return jsonResponse([]);
      if (String(input) === "/clients") return jsonResponse([]);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectorInstances />);
    await screen.findByText("No connector instances are configured.");
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "autotask" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Autotask" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText("API integration code")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "syncro" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Syncro" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText(/Syncro subdomain/)).toBeInTheDocument();
    expect(screen.getByLabelText("API key")).toBeInTheDocument();
    expect(screen.queryByLabelText("Service address")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back" }));

    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "servicenow" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "ServiceNow" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue to credentials" }));
    expect(screen.getByLabelText("ServiceNow instance URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByLabelText(/API version/)).toBeInTheDocument();
  });

  it("renders instance fields for each supported RMM", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/connector-instances") return jsonResponse([]);
      if (String(input) === "/clients") return jsonResponse([]);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectorInstances />);
    await screen.findByText("No connector instances are configured.");
    fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "ninjaone" } });
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
    const created = {
      ...instances[0],
      connector_instance_id: "ci-m365-1",
      connector_type: "m365",
      display_name: "Acme Microsoft 365",
      credential_ref: "connector:m365:acme-microsoft-365:123e4567-e89b-12d3-a456-426614174002",
      config_json: "{}"
    };
    let instanceListCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/clients") return jsonResponse([]);
      if (path === "/connector-instances" && init?.method === "POST") return jsonResponse(created);
      if (path === "/connector-instances") {
        instanceListCalls += 1;
        return jsonResponse(instanceListCalls === 1 ? [] : [created]);
      }
      if (path === "/ingestion/sync-cursors") return jsonResponse([]);
      if (path === "/secrets" && init?.method === "POST") return jsonResponse(undefined);
      if (path === "/connector-instances/ci-m365-1") return jsonResponse(created);
      if (path === "/client-connector-mappings?connector_instance_id=ci-m365-1") return jsonResponse([]);
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

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

    expect(await screen.findByRole("status")).toHaveTextContent("Saved connection Acme Microsoft 365.");
    expect(screen.getByRole("status")).toHaveTextContent("Provider access has not been verified.");
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith("/sync"))).toBe(false);
    const secretCall = fetchMock.mock.calls.find(([input, request]) => String(input) === "/secrets" && request?.method === "POST");
    const instanceCall = fetchMock.mock.calls.find(([input, request]) => String(input) === "/connector-instances" && request?.method === "POST");
    expect(JSON.parse(String(secretCall?.[1]?.body))).toEqual({
      name: created.credential_ref,
      value: JSON.stringify({ mode: "client_credentials", tenant_id: "tenant-value", client_id: "application-value", client_secret: "credential-value" })
    });
    expect(JSON.parse(String(instanceCall?.[1]?.body))).toMatchObject({ connector_type: "m365", config_json: "{}" });
    expect(String(instanceCall?.[1]?.body)).not.toContain("credential-value");
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" }
  });
}
