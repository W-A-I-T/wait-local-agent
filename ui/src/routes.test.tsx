import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "./routes";

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
});
