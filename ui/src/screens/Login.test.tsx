import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Login } from "./Login";
import { apiFetch } from "../api/client";
import { useDashboard } from "../app/DashboardContext";
import { buildApiHeaders, clearInMemoryApiToken, selectedClientStorageKey } from "../api/headers";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const mockedUseDashboard = vi.mocked(useDashboard);

function renderScreen(initialEntries = ["/"]) {
  return render(<MemoryRouter initialEntries={initialEntries}><Login /></MemoryRouter>);
}

describe("Login", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    clearInMemoryApiToken();
    delete window["__WAIT_API_BASE__"];
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

  it("does not carry a previous account's client scope into a new sign-in", async () => {
    window.localStorage.setItem(selectedClientStorageKey, "previous-account-client");
    mockedApiFetch.mockImplementation(async (path) => {
      if (path === "/auth/login/local") {
        expect(new Headers(buildApiHeaders()).has("X-WAIT-Client-ID")).toBe(false);
        return { session_created: true } as never;
      }
      return { enabled: false } as never;
    });

    renderScreen();
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "new-account-fixture" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(mockedUseDashboard().refresh).toHaveBeenCalled());
    expect(window.localStorage.getItem(selectedClientStorageKey)).toBeNull();
  });

  it("keeps bootstrap credentials in session storage for the bearer break-glass path", async () => {
    mockedApiFetch.mockResolvedValue({ session_created: false } as never);

    renderScreen();
    fireEvent.change(screen.getByLabelText("Access token"), { target: { value: "bootstrap-token" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(window.localStorage.getItem("wait-local-agent-api-token")).toBeNull());
    expect(window.sessionStorage.getItem("wait-local-agent-api-token")).toBe("bootstrap-token");
    expect(buildApiHeaders()).toMatchObject({ Authorization: "Bearer bootstrap-token" });
    expect(screen.getByRole("status")).toHaveTextContent("this session is not persisted");
  });

  it("uses the desktop API base for Microsoft sign-in and preserves the validated next path", async () => {
    mockedApiFetch.mockResolvedValue({ enabled: true } as never);
    window["__WAIT_API_BASE__"] = "http://127.0.0.1:8788";
    const { assign, restore } = mockLocationAssign();

    renderScreen(["/settings?tab=providers"]);
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Microsoft" }));

    expect(assign).toHaveBeenCalledWith(
      "http://127.0.0.1:8788/auth/oidc/login?next=%2Fsettings%3Ftab%3Dproviders"
    );
    restore();
  });

  it("keeps Microsoft sign-in relative when no API base is configured", async () => {
    mockedApiFetch.mockResolvedValue({ enabled: true } as never);
    delete window["__WAIT_API_BASE__"];
    const { assign, restore } = mockLocationAssign();

    renderScreen();
    fireEvent.click(await screen.findByRole("button", { name: "Sign in with Microsoft" }));

    expect(assign).toHaveBeenCalledWith("/auth/oidc/login?next=%2F");
    restore();
  });
});

function mockLocationAssign() {
  const originalLocation = window.location;
  const assign = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, assign }
  });
  return {
    assign,
    restore: () => Object.defineProperty(window, "location", { configurable: true, value: originalLocation })
  };
}
