import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { useDashboard } from "../app/DashboardContext";
import { apiFetch } from "../api/client";
import { Agents } from "./Agents";
import { Analytics } from "./Analytics";
import { Audit } from "./Audit";
import { Backfills } from "./Backfills";
import { Collectors } from "./Collectors";
import { Connectors } from "./Connectors";
import { Consultant } from "./Consultant";
import { Knowledge } from "./Knowledge";
import { Reports } from "./Reports";
import { SolutionDelivery } from "./SolutionDelivery";
import { TechnicianChat } from "./TechnicianChat";
import { Templates } from "./Templates";
import { Workflows } from "./Workflows";

vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));
vi.mock("../api/client", () => ({ apiFetch: vi.fn(), apiFetchBlob: vi.fn() }));

const clients = [
  { client_id: "acme", name: "Acme Support", status: "active" },
  { client_id: "globex", name: "Globex IT", status: "active" },
];

const analyticsSummary = {
  range: { from: null, to: null },
  client_id: null,
  executions_over_time: [],
  success_rate: { total: 0, succeeded: 0, rate: 0 },
  failures_by_status: [],
  activity_breakdown: [],
  approval_rate: { requested: 0, decided: 0, approved: 0, rejected: 0, pending: 0, rate: 0, derivation: "" },
  ticket_metrics: {
    touched: 0,
    resolved: 0,
    resolution_rate: 0,
    derivation: "",
    historical_resolution: { resolved_with_history: 0, with_duration: 0, average_minutes: null, derivation: "" },
  },
  activity_by_workflow: [],
  estimated_minutes_saved: { minutes: 0, estimate: true, derivation: "" },
  model_usage: { runs_with_usage: 0, runs_with_cost: 0, input_tokens: 0, output_tokens: 0, estimated_cost_usd: 0, estimate: true, derivation: "" },
};

const dashboard = {
  approvalRequests: [],
  authState: "authenticated",
  canWrite: true,
  clientId: "acme",
  selectedClientId: "acme",
  setSelectedClientId: vi.fn(),
  clients,
  connectors: [],
  executeApproval: vi.fn(),
  huduConnector: undefined,
  haloConnector: undefined,
  isAdmin: true,
  loading: false,
  refresh: vi.fn().mockResolvedValue(undefined),
  role: "admin",
  roleResolved: true,
  writeHealth: { status: "blocked", message: "", count: 0 },
};

function responseFor(path: string): unknown {
  if (path === "/agents") return [];
  if (path === "/agent-backfills") return [];
  if (path === "/tools") return [];
  if (path === "/workflow-runs") return [];
  if (path === "/workflows/templates") return [];
  if (path === "/workflow-templates/gallery") return [];
  if (path === "/collectors/modules") return [{ id: "collector", name: "Collector", description: "", config_schema: [] }];
  if (path === "/collectors/runs") return [];
  if (path === "/reports") return [];
  if (path === "/hardening/runs") return [];
  if (path === "/backup/restore-exercises") return [];
  if (path === "/technician/chat/sessions") return [];
  if (path === "/smart-actions/runs") return [];
  if (path === "/knowledge/documents") return [{ id: 7, path: "docs/runbook.md", title: "Runbook", kind: "markdown", checksum: "sum", modified_at: "now", chunk_count: 1, indexed_at: "now", client_id: "acme", authority: "UNTRUSTED", sop_version: null, approved_by: null, approved_at: null, superseded_by: null }];
  if (path === "/analytics/summary") return analyticsSummary;
  if (path === "/audit") return [];
  if (path === "/consultant/blueprints") return [];
  if (path === "/consultant/use-cases") return { use_cases: [] };
  if (path === "/consultant/monitoring/agents") return { agent_count: 0, total_runs: 0, failed_runs: 0 };
  if (path === "/consultant/discovery/sessions") return [];
  if (path.includes("/connectors/") && path.endsWith("/companies")) return { result: { count: 0 }, items: [] };
  if (path.includes("/connectors/") && path.endsWith("/articles")) return { result: { count: 0 }, items: [] };
  return { status: "blocked", message: "" };
}

function renderScreen(screen: React.ReactElement) {
  return render(<MemoryRouter>{screen}</MemoryRouter>);
}

beforeEach(() => {
  vi.mocked(useDashboard).mockReturnValue(dashboard as never);
  vi.mocked(apiFetch).mockImplementation((path: string) => Promise.resolve(responseFor(path)) as ReturnType<typeof apiFetch>);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("ClientIdSelect screen rollout", () => {
  it.each([
    ["Consultant", <Consultant />, "discovery-client-id", true],
    ["SolutionDelivery package", <SolutionDelivery />, "package-client-id", true],
    ["SolutionDelivery deployment", <SolutionDelivery />, "deployment-client-id", true],
    ["SolutionDelivery rollback", <SolutionDelivery />, "rollback-client-id", true],
    ["Backfills", <Backfills />, "backfill-client-id", false],
    ["Templates", <Templates />, "template-client-id", false],
    ["Workflows", <Workflows />, "workflow-client-id", false],
    ["Collectors", <Collectors />, "collector-client-id", false],
    ["Agents", <Agents />, "agent-client-id", false],
    ["Reports", <Reports />, "report-client-id", false],
    ["TechnicianChat", <TechnicianChat />, "technician-client-id", true],
    ["Knowledge", <Knowledge />, "knowledge-search-client-id", false],
    ["Analytics", <Analytics />, "analytics-client-id", false],
    ["Audit", <Audit />, "audit-client-id", false],
  ] as const)("renders real client options for %s", async (_name, screenElement, controlId, required) => {
    renderScreen(screenElement);

    await waitFor(() => expect(document.getElementById(controlId)).toBeInTheDocument());
    const control = document.getElementById(controlId);
    expect(control).toHaveValue(required || _name === "Agents" ? "acme" : "");
    if (required) {
      expect(control).toBeRequired();
    } else {
      expect(control).not.toBeRequired();
    }
    expect(screen.getAllByRole("option", { name: "Acme Support" }).some((option) => option.getAttribute("value") === "acme")).toBe(true);
    expect(screen.getAllByRole("option", { name: "Globex IT" }).some((option) => option.getAttribute("value") === "globex")).toBe(true);
  });

  it("shows authority metadata and controls only to administrators", async () => {
    const adminRender = renderScreen(<Knowledge />);

    expect(await screen.findByText("Authority: UNTRUSTED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change authority" })).toBeInTheDocument();

    adminRender.unmount();
    vi.mocked(useDashboard).mockReturnValue({ ...dashboard, role: "viewer", isAdmin: false } as never);
    renderScreen(<Knowledge />);

    expect(await screen.findByText("Authority: UNTRUSTED")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change authority" })).not.toBeInTheDocument();
  });

  it("opens the administrator authority editor", async () => {
    renderScreen(<Knowledge />);

    fireEvent.click(await screen.findByRole("button", { name: "Change authority" }));

    expect(screen.getByLabelText("Authority")).toHaveValue("UNTRUSTED");
    expect(screen.getByLabelText("SOP version")).toBeInTheDocument();
  });
});
