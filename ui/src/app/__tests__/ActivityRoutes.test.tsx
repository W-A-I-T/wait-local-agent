import { fireEvent, render, screen } from "@testing-library/react";
import { Link, MemoryRouter, useSearchParams } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../../routes";

vi.mock("../../screens/ActivityRuns", () => ({
  ActivityRuns: () => {
    const [searchParams] = useSearchParams();
    return <div>Unified Runs screen · {searchParams.get("kind") ?? "all"} · {searchParams.get("execution_id") ?? "all"}</div>;
  }
}));
vi.mock("../../screens/Approvals", () => ({
  Approvals: () => (
    <div>
      Approvals screen
      <Link to="/executions/88?kind=execution">Open run #88</Link>
    </div>
  )
}));
vi.mock("../../screens/Audit", () => ({ Audit: () => <div>Audit screen</div> }));
vi.mock("../../screens/Executions", () => ({
  Executions: ({ initialExecutionId }: { initialExecutionId?: string }) => (
    <div>Execution detail screen · {initialExecutionId ?? "none"}</div>
  )
}));

describe("activity routes", () => {
  it("redirects executions into filtered Runs", async () => {
    render(<MemoryRouter initialEntries={["/executions"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByText("Unified Runs screen · execution · all")).toBeInTheDocument();
  });

  it("resolves an execution deep link with the execution preselected", async () => {
    render(<MemoryRouter initialEntries={["/executions/42?kind=execution"]}><AppRoutes /></MemoryRouter>);

    expect(await screen.findByText("Execution detail screen · 42")).toBeInTheDocument();
  });

  it("resolves an approval Open run link to the preselected execution detail", async () => {
    render(<MemoryRouter initialEntries={["/approvals"]}><AppRoutes /></MemoryRouter>);

    fireEvent.click(screen.getByRole("link", { name: "Open run #88" }));

    expect(await screen.findByText("Execution detail screen · 88")).toBeInTheDocument();
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
