import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { PrincipalsAdmin } from "./PrincipalsAdmin";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedDashboard = vi.mocked(useDashboard);

const principal = {
  principal_id: "tech-alpha",
  kind: "staff" as const,
  display_name: "Tech Alpha",
  active: true,
  created_at: "2026-08-31T00:00:00Z",
  client_roles: [["alpha", "technician"]] as Array<[string, "technician"]>,
  global_roles: [],
  credential_count: 1,
  credentials: [{ credential_hash_prefix: "ph0000000000", active: true, created_at: "2026-08-31T00:00:00Z" }]
};

function renderScreen() {
  return render(<MemoryRouter><PrincipalsAdmin /></MemoryRouter>);
}

describe("PrincipalsAdmin", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedDashboard.mockReturnValue({
      clients: [{ client_id: "alpha", name: "Alpha" }]
    } as never);
    mockedApiFetch.mockImplementation(async (path, init) => {
      if (path === "/auth/principals" && !init?.method) return [principal] as never;
      if (path.endsWith("/credentials") && init?.method === "POST") return { token: "one-time-secret" } as never;
      if (path === "/auth/principals" && init?.method === "POST") {
        return { ...principal, token: "created-one-time-secret", credential_notice: "Principal created." } as never;
      }
      return principal as never;
    });
  });

  it("renders principal details and issues a one-time credential reveal", async () => {
    renderScreen();

    expect(await screen.findByRole("heading", { name: "People & Access" })).toBeInTheDocument();
    expect(screen.getAllByText("Tech Alpha").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Selected" }));
    fireEvent.click(await screen.findByRole("button", { name: "Issue credential" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent("one-time-secret");
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("one-time-secret")).not.toBeInTheDocument();
  });

  it("creates a principal and refreshes the list", async () => {
    renderScreen();
    await waitFor(() => expect(screen.getAllByText("Tech Alpha").length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText("Principal ID"), { target: { value: "viewer-beta" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Viewer Beta" } });
    fireEvent.click(screen.getByRole("button", { name: "Create & issue credential" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(
      "/auth/principals",
      expect.objectContaining({ method: "POST" })
    ));
    expect(await screen.findByText("Principal created.")).toBeInTheDocument();
    expect(await screen.findByText("created-one-time-secret")).toBeInTheDocument();
    const createCall = mockedApiFetch.mock.calls.find(([, init]) => init?.method === "POST" && init?.body);
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
      client_roles: [{ client_id: "alpha", role: "technician" }],
      issue_credential: true
    });
  });

  it("surfaces management load errors", async () => {
    mockedApiFetch.mockRejectedValue(new Error("access data unavailable"));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("access data unavailable");
  });
});
