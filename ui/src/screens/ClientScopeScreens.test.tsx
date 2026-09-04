import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDashboard } from "../app/DashboardContext";
import { ActivityRuns } from "./ActivityRuns";
import { Audit } from "./Audit";
import { Executions } from "./Executions";
import { Overview } from "./Overview";

vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));
vi.mock("../components/SetupStatus", () => ({
  SetupStatus: () => <div>Setup status</div>
}));

const mockedUseDashboard = vi.mocked(useDashboard);
const clients = [{ client_id: "alpha", name: "Alpha Support", status: "active" }];

function renderScreen(screenElement: React.ReactElement) {
  return render(<MemoryRouter>{screenElement}</MemoryRouter>);
}

describe("client-scoped activity screens", () => {
  let requests: Array<{ path: string; headers: Headers }>;

  beforeEach(() => {
    requests = [];
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      requests.push({ path: String(input), headers: new Headers(init?.headers) });
      return new Response(JSON.stringify([]), { headers: { "Content-Type": "application/json" } });
    }));
    mockedUseDashboard.mockReturnValue({
      selectedClientId: "alpha",
      clients,
      connectors: [],
      liveWritesReady: false,
      writeHealth: { status: "blocked", message: "Writes are gated.", count: 0 },
      workflowRuns: [],
      eventHistory: [],
      eventDeliveries: [],
      retryEventDelivery: vi.fn(),
      canWrite: false,
      isConfigured: true,
      configurationLoading: false,
      roleResolved: true,
      isAdmin: false,
      isMspAdmin: false
    } as never);
    window.localStorage.setItem("wait-local-agent-selected-client", "alpha");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each([
    ["Audit", <Audit key="audit" />, "/audit"],
    ["Executions", <Executions key="executions" />, "/executions"],
    ["Activity", <ActivityRuns key="activity" />, "/packs/operator-control/activity/runs"],
  ] as const)("shows the selected scope and sends it for %s", async (_name, screenElement, path) => {
    renderScreen(screenElement);

    expect(await screen.findByText("Scoped to Alpha Support")).toBeInTheDocument();
    const request = requests.find((entry) => entry.path.startsWith(path));
    expect(request?.headers.get("X-WAIT-Client-ID")).toBe("alpha");
  });

  it("shows the selected scope on the Operations Overview", () => {
    renderScreen(<Overview />);

    expect(screen.getByText("Scoped to Alpha Support")).toBeInTheDocument();
  });

  it("shows the empty scope state and omits the scope header when the selector is cleared", async () => {
    mockedUseDashboard.mockReturnValue({ selectedClientId: "", clients, isMspAdmin: false } as never);
    window.localStorage.clear();

    renderScreen(<Audit />);

    expect(await screen.findByText("No client selected")).toBeInTheDocument();
    expect(requests[0]?.headers.has("X-WAIT-Client-ID")).toBe(false);
  });
});
