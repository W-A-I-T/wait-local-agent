import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { EmptyState } from "./EmptyState";

describe("EmptyState", () => {
  it("explains the empty state and renders an optional link action", () => {
    render(
      <MemoryRouter>
        <EmptyState
          title="No clients yet"
          why="Create a client before connecting a provider."
          action={{ label: "Create a client", to: "/clients#client-form" }}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: "No clients yet" })).toBeInTheDocument();
    expect(screen.getByText("Create a client before connecting a provider.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Create a client" })).toHaveAttribute("href", "/clients#client-form");
  });
});
