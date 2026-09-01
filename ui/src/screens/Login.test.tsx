import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Login } from "./Login";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedUseDashboard = vi.mocked(useDashboard);

function renderScreen() {
  return render(<MemoryRouter><Login /></MemoryRouter>);
}

describe("Login", () => {
  beforeEach(() => {
    window.localStorage.clear();
    mockedApiFetch.mockReset();
    mockedUseDashboard.mockReturnValue({ refresh: vi.fn().mockResolvedValue({ role: "viewer" }) } as never);
  });

  it("creates a browser session without persisting the credential", async () => {
    mockedApiFetch.mockResolvedValue({ session_created: true } as never);

    renderScreen();
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "secret-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(
      "/auth/login/local",
      expect.objectContaining({ body: JSON.stringify({ token: "secret-token" }) })
    ));
    expect(window.localStorage.getItem("wait-local-agent-api-token")).toBeNull();
  });

  it("keeps bootstrap credentials in the bearer break-glass path", async () => {
    mockedApiFetch.mockResolvedValue({ session_created: false } as never);

    renderScreen();
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "bootstrap-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(window.localStorage.getItem("wait-local-agent-api-token")).toBe("bootstrap-token"));
  });
});
