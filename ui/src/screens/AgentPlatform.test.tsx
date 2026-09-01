import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentPlatform } from "./AgentPlatform";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedUseDashboard = vi.mocked(useDashboard);

const pendingSession = {
  id: "iteration-1",
  source_type: "agent",
  source_id: "agent-1",
  source_version: 1,
  entity_id: "TCK-1001",
  status: "pending_approval",
  current_step: 0,
  steps: [{ tool_id: "dispatch-suggestion", payload: {} }],
  approval_id: 42,
  events: [{ ordinal: 0, event_type: "step.pending_approval", status: "pending_approval" }]
};

function responseFor(path: string): unknown {
  if (path === "/packs/agent-platform/status") {
    return {
      status: "ready",
      migration_version: 1100,
      capabilities: {
        durable_memory: true,
        versioned_skills: true,
        skill_validation_harness: true,
        step_iteration: true,
        technician_ranking: true,
        ticket_image_context: true
      },
      attachment_max_bytes: 4 * 1024 * 1024,
      write_actions_enabled: false,
      llm_inference_enabled: false,
      initialized: true
    };
  }
  if (path === "/packs/agent-platform/iterations") return [pendingSession];
  if (path === "/agents") return [{ id: "agent-1", name: "Dispatch review", client_id: "acme" }];
  if (path === "/packs/agent-platform/memories") return [];
  if (path === "/packs/agent-platform/skills") return [];
  if (path === "/smart-actions") return [{ action_id: "ticket-triage", title: "Ticket triage", risk_level: "low", requires_approval: false }];
  if (path === "/packs/agent-platform/technicians") return [];
  if (path.includes("/attachments/analyses")) return [];
  if (path.includes("/attachments")) return [];
  return {};
}

describe("AgentPlatform", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedUseDashboard.mockReturnValue({
      canWrite: true,
      role: "admin",
      clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
      selectedClientId: "acme",
      liveWritesReady: false,
      writeHealthResolved: true
    } as unknown as ReturnType<typeof useDashboard>);
    mockedApiFetch.mockImplementation(async (path: string) => responseFor(path) as never);
  });

  it("exposes each governed capability and keeps approval checks actionable", async () => {
    render(<AgentPlatform />);

    expect(await screen.findByRole("heading", { name: "Agent Platform" })).toBeInTheDocument();
    expect(screen.getByText(/Client scope: Acme Support \(acme\)/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Durable memory" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No durable memory is available" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Skills" }));
    expect(await screen.findByRole("heading", { name: "Versioned skills" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No governed skills are available" })).toBeInTheDocument();
    const triageAction = screen.getByRole("checkbox", { name: /Ticket triage/ });
    expect(triageAction).not.toBeChecked();
    fireEvent.click(triageAction);
    expect(triageAction).toBeChecked();

    fireEvent.click(screen.getByRole("tab", { name: "Iterations" }));
    expect(await screen.findByRole("heading", { name: "Step iteration" })).toBeInTheDocument();
    const approvalButton = await screen.findByRole("button", { name: "Check approval" });
    expect(approvalButton).toBeEnabled();
    expect(screen.getByRole("button", { name: "Restart" })).toBeDisabled();

    fireEvent.click(approvalButton);
    await waitFor(() => {
      expect(mockedApiFetch).toHaveBeenCalledWith(
        "/packs/agent-platform/iterations/iteration-1/continue",
        expect.objectContaining({ method: "POST" })
      );
    });

    fireEvent.click(screen.getByRole("tab", { name: "Technicians" }));
    expect(await screen.findByRole("heading", { name: "Technician intelligence" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No technician profiles are available" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Attachments" }));
    expect(await screen.findByRole("heading", { name: "Ticket image context" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "No ticket images are loaded" })).toBeInTheDocument();
  });

  it("disables mutation controls for read-only operators", async () => {
    mockedUseDashboard.mockReturnValue({
      canWrite: false,
      role: "viewer",
      clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
      selectedClientId: "acme",
      liveWritesReady: false,
      writeHealthResolved: true
    } as unknown as ReturnType<typeof useDashboard>);
    render(<AgentPlatform />);

    expect(await screen.findByRole("button", { name: "Store revision" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "Technicians" }));
    expect(await screen.findByRole("button", { name: "Save profile" })).toBeDisabled();
  });

  it("explains status failures instead of presenting a ready platform", async () => {
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/packs/agent-platform/status") throw new Error("status unavailable");
      return responseFor(path) as never;
    });

    render(<AgentPlatform />);

    expect(await screen.findByRole("alert")).toHaveTextContent("status unavailable");
    expect(screen.queryByRole("heading", { name: "Agent Platform" })).not.toBeInTheDocument();
  });

  it("shows blocked and initializing status while capability checks are unresolved", async () => {
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/packs/agent-platform/status") {
        return { ...responseFor(path) as object, initialized: false } as never;
      }
      return responseFor(path) as never;
    });

    mockedUseDashboard.mockReturnValue({
      canWrite: true,
      role: "admin",
      clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
      selectedClientId: "acme",
      liveWritesReady: false,
      writeHealthResolved: false
    } as unknown as ReturnType<typeof useDashboard>);

    render(<AgentPlatform />);

    expect(await screen.findByText("initializing")).toBeInTheDocument();
    expect(screen.getByText("checking")).toBeInTheDocument();
    expect(screen.getByText("blocked")).toBeInTheDocument();
  });

  it("explains an unavailable client label and empty action catalog", async () => {
    mockedUseDashboard.mockReturnValue({
      canWrite: true,
      role: "admin",
      clients: [],
      selectedClientId: "acme",
      liveWritesReady: true,
      writeHealthResolved: true
    } as unknown as ReturnType<typeof useDashboard>);
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/smart-actions") return [] as never;
      return responseFor(path) as never;
    });

    render(<AgentPlatform />);

    expect(await screen.findByText(/Client scope: Selected client \(acme\)/)).toBeInTheDocument();
    expect(screen.getAllByText("ready", { exact: true })).toHaveLength(2);
    fireEvent.click(screen.getByRole("tab", { name: "Skills" }));
    expect(await screen.findByText("No Smart Actions are available in the current catalog.")).toBeInTheDocument();
  });

  it("requires an explicit client scope before loading pack data", async () => {
    mockedUseDashboard.mockReturnValue({
      canWrite: true,
      role: "admin",
      clients: [],
      selectedClientId: "",
      liveWritesReady: false,
      writeHealthResolved: true
    } as unknown as ReturnType<typeof useDashboard>);

    render(<AgentPlatform />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a client");
    expect(await screen.findByRole("heading", { name: "Choose a client to load Agent Platform data" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Store revision" })).not.toBeInTheDocument();
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/packs/agent-platform/memories");
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/packs/agent-platform/skills");
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/packs/agent-platform/iterations");
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/packs/agent-platform/technicians");
  });

  it("reloads scoped records when the selected client changes", async () => {
    let memoryRows: unknown[] = [{
      id: "memory-a",
      key: "client-a-fact",
      value: { owner: "client-a" },
      summary: "Client A only",
      provenance: "browser test",
      version: 1,
      scope_type: "client",
      pinned: false
    }];
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/packs/agent-platform/memories") return memoryRows as never;
      return responseFor(path) as never;
    });

    const view = render(<AgentPlatform />);
    expect(await screen.findByRole("heading", { name: "client-a-fact" })).toBeInTheDocument();

    memoryRows = [];
    mockedUseDashboard.mockReturnValue({
      canWrite: true,
      role: "admin",
      clients: [
        { client_id: "acme", name: "Acme Support", status: "active" },
        { client_id: "client-b", name: "Client B", status: "active" }
      ],
      selectedClientId: "client-b",
      liveWritesReady: false,
      writeHealthResolved: true
    } as unknown as ReturnType<typeof useDashboard>);
    view.rerender(<AgentPlatform />);

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "client-a-fact" })).not.toBeInTheDocument();
      expect(screen.getByRole("heading", { name: "No durable memory is available" })).toBeInTheDocument();
    });
  });

  it("shows a recoverable error when scoped memory cannot be loaded", async () => {
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path === "/packs/agent-platform/memories") throw new Error("memory unavailable");
      return responseFor(path) as never;
    });

    render(<AgentPlatform />);

    expect(await screen.findByRole("status")).toHaveTextContent("memory unavailable");
    expect(screen.getByRole("heading", { name: "No durable memory is available" })).toBeInTheDocument();
  });

  it("reports invalid memory input without sending a failed save", async () => {
    render(<AgentPlatform />);

    fireEvent.change(screen.getByLabelText("Key"), { target: { value: "support-policy" } });
    fireEvent.change(screen.getByLabelText("Provenance"), { target: { value: "operator note" } });
    fireEvent.change(screen.getByLabelText("JSON value"), { target: { value: "not-json" } });
    fireEvent.click(screen.getByRole("button", { name: "Store revision" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Memory value must be valid JSON");
    expect(mockedApiFetch).not.toHaveBeenCalledWith("/packs/agent-platform/memories", expect.anything());

    fireEvent.change(screen.getByLabelText("JSON value"), { target: { value: "[]" } });
    fireEvent.click(screen.getByRole("button", { name: "Store revision" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Memory value must be a JSON object");
  });
});
