import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExtensionsPacks } from "../src/screens/ExtensionsPacks";
import { Sidebar } from "../src/app/Sidebar";

const dashboard = vi.hoisted(() => ({
  isAdmin: true,
  role: "admin" as "admin" | "viewer",
  roleResolved: true
}));

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => dashboard
}));

afterEach(() => {
  dashboard.isAdmin = true;
  dashboard.role = "admin";
  dashboard.roleResolved = true;
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("Extensions / Packs wiring", () => {
  it("loads packs and renders status, trust, license, and mount details", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/packs") {
        return jsonResponse([{ name: "reports", version: "1.2.3", locked: false, requires_license: true }]);
      }
      if (path === "/packs/status") {
        return jsonResponse([{
          name: "reports",
          version: "1.2.3",
          locked: false,
          requires_license: true,
          cli_available: true,
          router_available: true,
          mounted_cli: true,
          mounted_router: false,
          error: "router unavailable"
        }]);
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <ExtensionsPacks />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "reports" })).toBeInTheDocument();
    expect(screen.getByText("Unlocked")).toBeInTheDocument();
    expect(screen.getByText("License required")).toBeInTheDocument();
    expect(screen.getByText("router unavailable")).toBeInTheDocument();
    expect(screen.getByText("CLI mounted").parentElement).toHaveTextContent("Yes");
    expect(screen.getByText("Router mounted").parentElement).toHaveTextContent("No");
    fireEvent.click(screen.getByText("Advanced"));
    expect(screen.getByRole("link", { name: "Extensions" })).toHaveAttribute("href", "/system/extensions");
    expect(fetchMock.mock.calls.map(([input]) => String(input))).toEqual(
      expect.arrayContaining(["/packs", "/packs/status"])
    );
    expect(fetchMock.mock.calls.map(([input]) => String(input))).not.toContain("/packs/install");
  });

  it("renders a read-only error state when either status endpoint fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/packs") {
        return jsonResponse([]);
      }
      return new Response(JSON.stringify({ detail: "status unavailable" }), { status: 503 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ExtensionsPacks /></MemoryRouter>);

    expect(await screen.findByRole("alert")).toHaveTextContent("The appliance couldn't complete the request. Try again shortly.");
    expect(screen.queryByText("No packs installed")).not.toBeInTheDocument();
  });

  it("renders the empty state when no packs are installed", async () => {
    const fetchMock = vi.fn(async () => jsonResponse([]));
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter><ExtensionsPacks /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "No packs installed" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to install control" })).toHaveAttribute("href", "/#pack-install-form");
  });

  it("hides the admin surface from viewers", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    dashboard.isAdmin = false;
    dashboard.role = "viewer";

    render(
      <MemoryRouter>
        <ExtensionsPacks />
        <Sidebar />
      </MemoryRouter>
    );

    expect(await screen.findByText("Administrator role required to view installed extensions and packs.")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Extensions" })).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" }
  });
}
