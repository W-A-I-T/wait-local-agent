import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "./routes";
import { useDashboard } from "./app/DashboardContext";

vi.mock("./app/DashboardContext", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./app/DashboardContext")>();
  return { ...actual, useDashboard: vi.fn() };
});

const mockedUseDashboard = vi.mocked(useDashboard);

beforeEach(() => {
  mockedUseDashboard.mockReset();
});

describe("application routes", () => {
  it("renders NotFound for an unknown path instead of redirecting", async () => {
    render(
      <MemoryRouter initialEntries={["/does-not-exist?from=test"]}>
        <AppRoutes />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByText("/does-not-exist?from=test")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Return to Overview" })).toHaveAttribute("href", "/");
  });

  it("gates Settings before mounting its admin-only requests for technicians", () => {
    mockedUseDashboard.mockReturnValue({ role: "technician", roleResolved: true } as never);
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter initialEntries={["/settings"]}>
        <AppRoutes />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: "Administrator access required" })).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
