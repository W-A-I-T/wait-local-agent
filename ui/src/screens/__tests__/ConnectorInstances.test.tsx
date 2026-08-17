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
