import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectorFactory } from "../src/screens/ConnectorFactory";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true })
}));

describe("ConnectorFactory", () => {
  const connectorResponse = new Response(JSON.stringify({
    format: "wait-local-agent.power-platform-connector",
    format_version: 1,
    name: "WAIT Ticket API",
    auth_type: "none",
    operation_count: 1,
    warnings: [],
    api_definition: { swagger: "2.0" },
    api_properties: { properties: { publisher: "WAIT" } }
  }), { status: 200 });

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      if (String(input) === "/consultant/connectors/power-platform") return Promise.resolve(connectorResponse.clone());
      return Promise.resolve(new Response(JSON.stringify({
        format: "wait-local-agent.power-platform-cli-plan",
        format_version: 1,
        operation: "connector.create",
        mutates_external_state: true,
        requires_approval: true,
        pac_available: false,
        environment: "https://org.crm.dynamics.com",
        solution_unique_name: null,
        artifact_dir: "/tmp/connector",
        files: {},
        command: ["pac", "connector", "create"],
        approval_payload: {}
      }), { status: 200 }));
    }));
  });

  it("generates reviewable connector artifacts without executing the API", async () => {
    render(<MemoryRouter><ConnectorFactory /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Power Platform Connector Factory" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Generate connector artifacts" }));

    await waitFor(() => expect(screen.getByText("Generated WAIT Ticket API with 1 operation.")).toBeInTheDocument());
    expect(screen.getByText("apiDefinition.json")).toBeInTheDocument();
    expect(screen.getByText("apiProperties.json")).toBeInTheDocument();
  });

  it("reports invalid JSON before making a request", async () => {
    render(<MemoryRouter><ConnectorFactory /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("OpenAPI 2.0 definition"), { target: { value: "not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate connector artifacts" }));

    expect(await screen.findByText("Unexpected token 'o', \"not json\" is not valid JSON")).toBeInTheDocument();
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it("plans PAC deployment without executing it", async () => {
    render(<MemoryRouter><ConnectorFactory /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText("Artifact directory"), { target: { value: "/tmp/connector" } });
    fireEvent.change(screen.getByLabelText("Power Platform environment"), { target: { value: "https://org.crm.dynamics.com" } });
    fireEvent.click(screen.getByRole("button", { name: "Create PAC plan" }));

    await waitFor(() => expect(screen.getByText(/External mutation: yes/)).toBeInTheDocument());
    expect(screen.getAllByText("pac connector create").length).toBeGreaterThan(0);
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/pac/connector/create"))).toBe(true);
  });
});
