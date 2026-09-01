import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { Settings } from "./Settings";

vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, apiFetch: vi.fn() };
});
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedDashboard = vi.mocked(useDashboard);

function installSettingsResponses(demoMode: boolean) {
  mockedApiFetch.mockImplementation(async (path) => {
    switch (path) {
      case "/settings/providers":
        return { local_model_provider: "demo", vector_backend: "local" } as never;
      case "/settings/security":
        return {
          api_token_configured: false,
          admin_token_configured: false,
          tech_token_configured: false,
          viewer_token_configured: false,
          api_auth_required: false,
          demo_mode: demoMode
        } as never;
      case "/packs":
      case "/secrets":
        return [] as never;
      case "/update-status":
        return { status: "current", detail: "No update available." } as never;
      case "/founder/lp-status":
        throw new Error("launch passport not configured");
      default:
        throw new Error(`Unexpected request: ${String(path)}`);
    }
  });
}

describe("Settings demo mode explanation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDashboard.mockReturnValue({
      authState: "local-open",
      isAdmin: true,
      loading: false,
      role: "admin"
    } as never);
  });

  it("explains the active restrictions and restart-only change mechanism", async () => {
    installSettingsResponses(true);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Demo mode is active." })).toBeInTheDocument();
    expect(screen.getByText(/Write actions and Power Platform deployment are disabled/)).toBeInTheDocument();
    expect(screen.getByText(/Other actions may also be unavailable if their own/)).toHaveTextContent("WAIT_ALLOW_*");
    expect(screen.getByText(/There is no in-app switch for this/)).toHaveTextContent("WAIT_DEMO_MODE");
    expect(screen.getByText(/There is no in-app switch for this/)).toHaveTextContent(/restart/i);
  });

  it("omits the active restriction explanation when demo mode is off", async () => {
    installSettingsResponses(false);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    );

    expect(await screen.findByText("Settings loaded.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Demo mode is active." })).not.toBeInTheDocument();
    expect(screen.queryByText(/Write actions and Power Platform deployment are disabled/)).not.toBeInTheDocument();
  });
});
