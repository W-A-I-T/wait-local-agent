import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../AppShell";
import { useDashboard } from "../DashboardContext";

vi.mock("../DashboardContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../DashboardContext")>();
  return { ...actual, useDashboard: vi.fn() };
});
vi.mock("../Sidebar", () => ({
  Sidebar: () => <aside>Sidebar</aside>
}));
vi.mock("../../routes", () => ({
  AppRoutes: () => <div>Routes</div>
}));
vi.mock("../../components/WaitAttribution", () => ({
  WaitAttribution: () => <div>Attribution</div>
}));

const mockedUseDashboard = vi.mocked(useDashboard);

function renderShell(
  writeHealth: { status: string; message: string },
  writeHealthResolved: boolean,
  authState: "demo" | null = null,
  roleResolved = false
) {
  mockedUseDashboard.mockReturnValue({
    apiToken: "",
    setApiToken: vi.fn(),
    saveApiToken: vi.fn(),
    clearApiToken: vi.fn(),
    refresh: vi.fn(),
    role: "viewer",
    authState,
    roleResolved,
    selectedClientId: "",
    setSelectedClientId: vi.fn(),
    clients: [],
    writeHealth,
    writeHealthResolved,
    liveWritesReady: writeHealth.status === "ready",
    statusMessage: "",
    refreshErrors: []
  } as never);

  return render(<MemoryRouter><AppShell /></MemoryRouter>);
}

describe("AppShell write-gate posture", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReset();
  });

  it("shows a quiet checking chip before the write-health fetch resolves", () => {
    renderShell({ status: "blocked", message: "Loading HaloPSA write health." }, false);

    expect(screen.getByRole("button", { name: "Checking write status…" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Checking write status…" })).not.toHaveClass("danger");
  });

  it("shows the gated posture and its backend explanation", () => {
    renderShell({
      status: "blocked",
      message: "Writes are blocked until WAIT_ALLOW_HTTP_PROBING=true and WAIT_ALLOW_WRITE_ACTIONS=true."
    }, true);

    const button = screen.getByRole("button", { name: "Safe Mode · writes disabled" });
    expect(button).not.toHaveClass("danger");
    fireEvent.click(button);

    expect(screen.getByText("PSA write gate (HaloPSA)")).toBeInTheDocument();
    expect(screen.getByText("Writes are blocked until WAIT_ALLOW_HTTP_PROBING=true and WAIT_ALLOW_WRITE_ACTIONS=true.")).toBeInTheDocument();
    expect(screen.getByText("Writes stay disabled until you explicitly enable them.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View connector details" })).toHaveAttribute("href", "/connectors");
  });

  it("shows the demo-mode badge and existing restriction explanation", () => {
    renderShell({ status: "blocked", message: "Writes are disabled in demo mode." }, true, "demo", true);

    expect(screen.getByText("Demo mode")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Explain demo mode" }));

    expect(screen.getByText("Demo mode is enabled for this appliance. Some write actions are intentionally unavailable.")).toBeInTheDocument();
  });
});
