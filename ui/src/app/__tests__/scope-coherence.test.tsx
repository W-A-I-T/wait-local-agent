import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboard } from "../DashboardContext";
import { apiFetch } from "../../api/client";
import { Agents } from "../../screens/Agents";
import { Backfills } from "../../screens/Backfills";
import { Workflows } from "../../screens/Workflows";

vi.mock("../DashboardContext", () => ({ useDashboard: vi.fn() }));
vi.mock("../../api/client", () => ({ apiFetch: vi.fn() }));

const dashboard = {
  canWrite: true,
  clients: [{ client_id: "acme", name: "Acme Support", status: "active" }],
  selectedClientId: "acme",
  isMspAdmin: false,
  role: "admin",
  roleResolved: true,
  connectors: []
};

const tool = {
  id: "ticket-triage",
  name: "Ticket Triage",
  title: "Ticket classification",
  description: "Classify tickets.",
  risk_level: "low",
  required_role: "viewer",
  approval_required: false,
  access_mode: "read"
};

const agent = {
  id: "agent-1",
  name: "Ticket triage",
  description: "Bounded triage.",
  enabled: true,
  trigger: "manual",
  entity_type: "ticket",
  filters: {},
  enabled_tools: [tool.id],
  steps: [{ tool_id: tool.id, payload: {} }],
  max_steps: 1,
  execution_timeout_seconds: 30,
  client_id: "acme",
  version: 1,
  run_once_per_entity: true,
  depends_on_agent_ids: [],
  context_sources: ["ticket"],
  approval_expiry_seconds: null,
  approval_required_tools: [],
  approval_rules: [],
  result_aware: false
};

const template = {
  id: "template-1",
  name: "Ticket triage",
  description: "Review a ticket.",
  trigger: "manual",
  approval_required: false,
  risk_level: "low",
  fields: []
};

beforeEach(() => {
  vi.mocked(useDashboard).mockReturnValue(dashboard as never);
  vi.mocked(apiFetch).mockImplementation(async (path, init) => {
    const requestPath = String(path);
    if (requestPath === "/tools") return [tool] as never;
    if (requestPath === "/agents") return [agent] as never;
    if (requestPath === "/workflows/templates") return [template] as never;
    if (requestPath === "/workflow-runs") return [] as never;
    if (requestPath === "/agent-backfills") return [] as never;
    if (requestPath === "/agent-backfills/preview") return { entity_count: 1, execution_mode: "sequential" } as never;
    if (init?.method === "POST" && requestPath === "/agents") return agent as never;
    if (init?.method === "POST" && requestPath.includes("/runs")) return { id: "run-1" } as never;
    if (init?.method === "POST" && requestPath === "/agent-backfills") return { ...agent, id: 1 } as never;
    return [] as never;
  });
});

afterEach(() => vi.clearAllMocks());

describe("shell scope coherence", () => {
  it.each([
    ["Agents", <Agents />],
    ["Backfills", <Backfills />],
    ["Workflows", <Workflows />]
  ] as const)("does not render a second client selector on %s", async (_name, element) => {
    render(<MemoryRouter>{element}</MemoryRouter>);
    await waitFor(() => expect(screen.queryByRole("combobox", { name: /client/i })).not.toBeInTheDocument());
  });

  it("posts the shell client when creating an agent", async () => {
    render(<MemoryRouter><Agents /></MemoryRouter>);
    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Ticket triage" } });
    fireEvent.click(await screen.findByLabelText("Ticket Triage"));
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path, init]) => (
      String(path) === "/agents" && init?.method === "POST" && JSON.parse(String(init.body)).client_id === "acme"
    ))).toBe(true));
  });

  it("posts the shell client when previewing a backfill", async () => {
    render(<MemoryRouter><Backfills /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Agent Backfills" });
    fireEvent.change(screen.getByLabelText("Ticket IDs"), { target: { value: "TCK-1001" } });
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path, init]) => (
      String(path) === "/agent-backfills/preview" && init?.method === "POST" && JSON.parse(String(init.body)).client_id === "acme"
    ))).toBe(true));
  });

  it("posts the shell client when starting a workflow", async () => {
    render(<MemoryRouter><Workflows /></MemoryRouter>);
    await screen.findByRole("heading", { name: "Workflows" });
    fireEvent.change(screen.getByLabelText("Template"), { target: { value: template.id } });
    fireEvent.change(screen.getByLabelText("Ticket id"), { target: { value: "TCK-1001" } });
    fireEvent.click(screen.getByRole("button", { name: "Start Workflow" }));

    await waitFor(() => expect(vi.mocked(apiFetch).mock.calls.some(([path, init]) => (
      String(path) === `/workflows/templates/${template.id}/runs`
      && init?.method === "POST"
      && JSON.parse(String(init.body)).client_id === "acme"
    ))).toBe(true));
  });

  it("shows shared guidance and disables creation for a bound principal without shell scope", async () => {
    vi.mocked(useDashboard).mockReturnValue({ ...dashboard, selectedClientId: "" } as never);
    render(<MemoryRouter><Workflows /></MemoryRouter>);

    expect(await screen.findByText("Choose a client in the top bar to continue.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start Workflow" })).toBeDisabled();
  });
});
