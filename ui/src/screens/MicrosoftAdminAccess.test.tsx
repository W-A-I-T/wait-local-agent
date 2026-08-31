import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { MicrosoftAdminAccess } from "./MicrosoftAdminAccess";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedDashboard = vi.mocked(useDashboard);
const refreshDashboard = vi.fn(async () => undefined);

const principals = [
  {
    principal_id: "tech-alpha",
    kind: "staff",
    display_name: "Tech Alpha",
    active: true,
    client_roles: [["alpha", "technician"]],
    global_roles: []
  },
  {
    principal_id: "msp-admin",
    kind: "staff",
    display_name: "MSP Admin",
    active: true,
    client_roles: [],
    global_roles: ["msp_admin"]
  }
];

const activeGrant = {
  principal_id: "tech-alpha",
  capability_key: "microsoft_admin",
  client_id: "alpha",
  active: true,
  granted_by: "bootstrap",
  updated_by: "bootstrap",
  created_at: "2026-08-28T00:00:00Z",
  updated_at: "2026-08-28T00:00:00Z"
};

function installApi(grants = [activeGrant], principalRows = principals) {
  mockedApiFetch.mockImplementation(async (path, init) => {
    if (path === "/packs/microsoft-admin/access/principals") return principalRows as never;
    if (String(path).startsWith("/packs/microsoft-admin/access/grants?")) return grants as never;
    if (path === "/packs/microsoft-admin/access/grants" && init?.method === "POST") {
      return activeGrant as never;
    }
    if (path === "/packs/microsoft-admin/access/grants/revoke") {
      return { ...activeGrant, active: false } as never;
    }
    throw new Error(`unexpected request ${path}`);
  });
}

describe("MicrosoftAdminAccess", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDashboard.mockReturnValue({
      clients: [
        { client_id: "alpha", name: "Alpha" },
        { client_id: "beta", name: "Beta" }
      ],
      refresh: refreshDashboard
    } as never);
  });

  it("lists active grants and grants an eligible client scope", async () => {
    installApi([]);
    render(<MicrosoftAdminAccess />);

    await screen.findByRole("heading", { name: "Grant access" });
    await waitFor(() => expect(screen.getByLabelText("Principal")).toHaveValue("tech-alpha"));
    await waitFor(() => expect(screen.getByLabelText("Client")).toHaveTextContent("Alpha"));
    expect(screen.getByText("No active Microsoft Admin grants.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Grant Microsoft Admin" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/microsoft-admin/access/grants",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          principal_id: "tech-alpha",
          capability_key: "microsoft_admin",
          client_id: "alpha"
        })
      })
    ));
    expect(await screen.findByText("Microsoft Admin access granted.")).toBeInTheDocument();
    expect(refreshDashboard).toHaveBeenCalled();
  });

  it("allows global scope only for an MSP administrator and revokes an exact grant", async () => {
    installApi();
    render(<MicrosoftAdminAccess />);

    await screen.findByText("Client: alpha");
    const globalCheckbox = screen.getByLabelText(/Global Microsoft Admin access/);
    expect(globalCheckbox).toBeDisabled();

    fireEvent.change(screen.getByLabelText("Principal"), { target: { value: "msp-admin" } });
    await waitFor(() => expect(screen.getByLabelText(/Global Microsoft Admin access/)).toBeEnabled());
    fireEvent.click(screen.getByLabelText(/Global Microsoft Admin access/));
    expect(screen.queryByLabelText("Client")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Revoke" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/microsoft-admin/access/grants/revoke",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          principal_id: "tech-alpha",
          capability_key: "microsoft_admin",
          client_id: "alpha"
        })
      })
    ));
    expect(await screen.findByText("Microsoft Admin access revoked.")).toBeInTheDocument();
  });

  it("surfaces access-data load failures", async () => {
    mockedApiFetch.mockRejectedValue(new Error("access data unavailable"));
    render(<MicrosoftAdminAccess />);

    expect(await screen.findByRole("alert")).toHaveTextContent("access data unavailable");
  });

  it("explains a fresh install with no principals instead of showing dead selects", async () => {
    installApi([], []);
    render(<MicrosoftAdminAccess />);

    expect(await screen.findByRole("heading", { name: "No principals are available" })).toBeInTheDocument();
    expect(screen.getByText(/configured technician tokens or database principals/)).toBeInTheDocument();
    expect(screen.getByText(/A fresh install has none/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Principal")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Client")).not.toBeInTheDocument();
  });
});
