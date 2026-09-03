import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../../routes";

vi.mock("../DashboardContext", () => ({
  useDashboard: () => ({ role: "admin", roleResolved: true, isMspAdmin: true })
}));

vi.mock("../../screens/Overview", () => ({ Overview: () => <h2>Operations Overview</h2> }));
vi.mock("../../screens/Clients", () => ({ Clients: () => <h2>Clients</h2> }));
vi.mock("../../screens/ClientDiscovery", () => ({ ClientDiscovery: () => <h2>Client discovery</h2> }));
vi.mock("../../screens/Connectors", () => ({ Connectors: () => <h2>Connectors</h2> }));
vi.mock("../../screens/ConnectorInstances", () => ({ ConnectorInstances: () => <h2>Connector Instances</h2> }));
vi.mock("../../screens/Workflows", () => ({ Workflows: () => <h2>Workflows</h2> }));
vi.mock("../../screens/Approvals", () => ({ Approvals: () => <h2>Approval Queue</h2> }));
vi.mock("../../screens/ActivityRuns", () => ({ ActivityRuns: () => <h2>Runs</h2> }));
vi.mock("../../screens/Consultant", () => ({ Consultant: () => <h2>Solutions Architect</h2> }));
vi.mock("../../screens/SolutionDelivery", () => ({ SolutionDelivery: () => <h2>Solution delivery</h2> }));
vi.mock("../../screens/Settings", () => ({ Settings: () => <h2>Admin Settings</h2> }));

const routeHeadings = [
  ["/", "Operations Overview"],
  ["/clients", "Clients"],
  ["/client-discovery", "Client discovery"],
  ["/connectors", "Connectors"],
  ["/integrations/connector-instances", "Connector Instances"],
  ["/workflows", "Workflows"],
  ["/approvals", "Approval Queue"],
  ["/activity/runs", "Runs"],
  ["/consultant", "Solutions Architect"],
  ["/consultant/solution-delivery", "Solution delivery"],
  ["/settings", "Admin Settings"]
] as const;

describe("route headings", () => {
  it.each(routeHeadings)("keeps %s headed by %s", (path, heading) => {
    render(<MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: new RegExp(`^${heading}$`) })).toBeInTheDocument();
  });
});
