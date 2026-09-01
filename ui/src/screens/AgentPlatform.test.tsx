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
    mockedUseDashboard.mockReturnValue({ canWrite: true, role: "admin" } as ReturnType<typeof useDashboard>);
    mockedApiFetch.mockImplementation(async (path: string) => responseFor(path) as never);
  });

  it("exposes each governed capability and keeps approval checks actionable", async () => {
    render(<AgentPlatform />);

    expect(await screen.findByRole("heading", { name: "Agent Platform" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Durable memory" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Skills" }));
    expect(await screen.findByRole("heading", { name: "Versioned skills" })).toBeInTheDocument();

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

    fireEvent.click(screen.getByRole("tab", { name: "Attachments" }));
    expect(await screen.findByRole("heading", { name: "Ticket image context" })).toBeInTheDocument();
  });

  it("disables mutation controls for read-only operators", async () => {
    mockedUseDashboard.mockReturnValue({ canWrite: false, role: "viewer" } as ReturnType<typeof useDashboard>);
    render(<AgentPlatform />);

    expect(await screen.findByRole("button", { name: "Store revision" })).toBeDisabled();
    fireEvent.click(screen.getByRole("tab", { name: "Technicians" }));
    expect(await screen.findByRole("button", { name: "Save profile" })).toBeDisabled();
  });
});
