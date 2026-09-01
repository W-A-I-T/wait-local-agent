import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { SolutionDelivery } from "./SolutionDelivery";
import { useDashboard } from "../app/DashboardContext";
import type { ApprovalRequest } from "../api/types";

vi.mock("../app/DashboardContext", async () => {
  const actual = await vi.importActual<typeof import("../app/DashboardContext")>("../app/DashboardContext");
  return { ...actual, useDashboard: vi.fn() };
});

const mockedUseDashboard = vi.mocked(useDashboard);

function dashboard(overrides: Partial<ReturnType<typeof baseDashboard>> = {}) {
  return { ...baseDashboard(), ...overrides };
}

function baseDashboard() {
  return {
    approvalRequests: [] as ApprovalRequest[],
    canWrite: true,
    clientId: "acme",
    clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
    executeApproval: vi.fn().mockResolvedValue(undefined),
    isAdmin: true,
    refresh: vi.fn().mockResolvedValue(undefined),
  };
}

beforeEach(() => {
  mockedUseDashboard.mockReset();
  vi.unstubAllGlobals();
});

describe("SolutionDelivery", () => {
  it("renders the governed pipeline and submits the verified package and follow-up bodies", async () => {
    mockedUseDashboard.mockReturnValue(dashboard() as never);
    const packageArtifact = {
      format: "wait-local-agent.power-platform.deployable-source",
      format_version: 1,
      client_id: "acme",
      solution: { unique_name: "employee_onboarding" },
      output_directory: "/workspace/employee_onboarding",
      files: [],
      file_count: 0,
      deployable: true,
      package_status: "deployable_source",
      credentials_included: false,
      execution_started: false,
      deployment_started: false,
      package_digest: "sha256:package",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(packageArtifact), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ valid: true, deployable: true, deployment_started: false }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "blocked", message: "Power Platform source materialization is blocked until WAIT_ALLOW_WRITE_ACTIONS=true." }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><SolutionDelivery /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Solution delivery" })).toBeInTheDocument();
    expect(screen.getByText(/Deploys via your locally-authenticated pac CLI/)).toBeInTheDocument();
    expect(screen.getByText("Package")).toBeInTheDocument();
    expect(screen.getByText("Validate")).toBeInTheDocument();
    expect(screen.getByText("Materialize")).toBeInTheDocument();
    expect(screen.getByText("Deploy stages")).toBeInTheDocument();
    expect(screen.getByText("Rollback")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Build package" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      client_id: "acme",
      solution_name: "employee_onboarding",
      publisher_name: "WAIT",
      publisher_prefix: "wait",
      output_directory: "/path/inside/WAIT_POWER_PLATFORM_WORKSPACE/employee_onboarding",
      artifacts: [],
      connector_artifacts: [],
    });

    fireEvent.click(screen.getByRole("button", { name: "Validate package" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ client_id: "acme", package: packageArtifact });

    fireEvent.click(screen.getByRole("button", { name: "Materialize source" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
    expect(JSON.parse(fetchMock.mock.calls[2][1].body)).toEqual({ client_id: "acme", package: packageArtifact });
    expect(screen.getByText("Unmet")).toBeInTheDocument();
    expect(screen.getAllByText(/WAIT_ALLOW_WRITE_ACTIONS=true/).length).toBeGreaterThan(0);
  });

  it("confirms stage execution and rollback requests from successful approval evidence", async () => {
    const request: ApprovalRequest = {
      id: 17,
      subject_id: "acme:employee_onboarding:dev",
      action_type: "power_platform.solution_stage",
      status: "approved",
      comment: "",
      execution_status: "succeeded",
      execution_message: "Stage completed",
      can_execute: false,
      payload: {
        client_id: "acme",
        solution_name: "employee_onboarding",
        publisher_name: "WAIT",
        publisher_prefix: "wait",
        output_directory: "/workspace/employee_onboarding",
        deployment_targets: [{ name: "dev", environment_url: "https://dev.example" }],
        stage: "dev",
        promotion_evidence: {},
      },
      output: { artifact_digest: "sha256:artifact" },
    };
    const executableRequest: ApprovalRequest = {
      ...request,
      id: 16,
      subject_id: "acme:employee_onboarding:build",
      execution_status: "not_started",
      can_execute: true,
      output: undefined,
      payload: { ...request.payload, stage: "build" },
    };
    const executeApproval = vi.fn().mockResolvedValue(undefined);
    const refresh = vi.fn().mockResolvedValue(undefined);
    mockedUseDashboard.mockReturnValue(dashboard({ approvalRequests: [executableRequest, request], executeApproval, refresh }) as never);
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ approval: { ...request, id: 18, action_type: "power_platform.solution_rollback" }, plan: {} }), { status: 201 }));
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("confirm", vi.fn().mockReturnValue(true));
    render(<MemoryRouter><SolutionDelivery /></MemoryRouter>);

    fireEvent.click(screen.getAllByRole("button", { name: "Execute stage" })[0]);
    expect(executeApproval).toHaveBeenCalledWith(16, "power_platform.solution_stage");

    fireEvent.click(screen.getByRole("button", { name: "Request rollback" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({
      client_id: "acme",
      stage: "dev",
      rollback_artifact_path: "/workspace/employee_onboarding/employee_onboarding.zip",
      rollback_evidence: { available: true, strategy: "reimport_previous_package", artifact_digest: "sha256:artifact" },
    });
  });

  it("prefills a Solutions Architect handoff and preserves hand-edited artifacts", async () => {
    mockedUseDashboard.mockReturnValue(dashboard() as never);
    const artifact = {
      format: "wait-local-agent.power-apps-artifact",
      client_id: "acme",
      credentials_included: false,
    };
    const packageArtifact = {
      format: "wait-local-agent.power-platform.deployable-source",
      format_version: 1,
      client_id: "acme",
      solution: { unique_name: "employee_onboarding" },
      output_directory: "/workspace/employee_onboarding",
      files: [],
      file_count: 0,
      deployable: true,
      package_status: "deployable_source",
      credentials_included: false,
      execution_started: false,
      deployment_started: false,
      package_digest: "sha256:package",
    };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(packageArtifact), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(
      <MemoryRouter initialEntries={[{
        pathname: "/consultant/solution-delivery",
        state: { source: "solutions-architect", clientId: "acme", artifacts: [artifact] },
      }]}>
        <Routes>
          <Route path="/consultant/solution-delivery" element={<SolutionDelivery />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByRole("status")).toHaveTextContent(/1 artifact received from Solutions Architect/);
    const artifacts = screen.getByLabelText("Artifacts (JSON array)");
    expect(artifacts).toHaveValue(JSON.stringify([artifact], null, 2));

    fireEvent.click(screen.getByRole("button", { name: "Build package" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toMatchObject({ artifacts: [artifact], client_id: "acme" });

    fireEvent.change(artifacts, { target: { value: "[]" } });
    fireEvent.click(screen.getByRole("button", { name: "Build package" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({ artifacts: [], client_id: "acme" });
  });

  it("ignores malformed handoff state without weakening materialization gates", () => {
    mockedUseDashboard.mockReturnValue(dashboard({ isAdmin: false }) as never);
    vi.stubGlobal("fetch", vi.fn());
    render(
      <MemoryRouter initialEntries={[{
        pathname: "/consultant/solution-delivery",
        state: { source: "solutions-architect", clientId: "acme", artifacts: [null] },
      }]}>
        <Routes>
          <Route path="/consultant/solution-delivery" element={<SolutionDelivery />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(screen.getByLabelText("Artifacts (JSON array)")).toHaveValue("[]");
    expect(screen.queryByText(/received from Solutions Architect/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Materialize source" })).toBeDisabled();
    expect(screen.getByText("Administrator access is required to materialize source files.")).toBeInTheDocument();
  });
});
