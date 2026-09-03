import { render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../../routes";

vi.mock("../../screens/ActivityRuns", () => ({
  ActivityRuns: () => {
    const [searchParams] = useSearchParams();
    return <div>Unified Runs screen · {searchParams.get("kind") ?? "all"} · {searchParams.get("execution_id") ?? "all"}</div>;
  }
}));
vi.mock("../../screens/Approvals", () => ({ Approvals: () => <div>Approvals screen</div> }));
vi.mock("../../screens/Audit", () => ({ Audit: () => <div>Audit screen</div> }));

describe("activity routes", () => {
  it("redirects executions into filtered Runs", async () => {
    render(<MemoryRouter initialEntries={["/executions"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByText("Unified Runs screen · execution · all")).toBeInTheDocument();
  });

  it("preserves an execution deep link while moving it into filtered Runs", async () => {
    render(<MemoryRouter initialEntries={["/executions/42?kind=execution"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByText("Unified Runs screen · execution · 42")).toBeInTheDocument();
  });

  it.each([
    ["/approvals", "Approvals screen"],
    ["/audit", "Audit screen"],
  ])("keeps %s under the Activity shell", (path, label) => {
    render(<MemoryRouter initialEntries={[path]}><AppRoutes /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
