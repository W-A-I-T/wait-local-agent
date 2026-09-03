import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ActivityShell, activityTabs } from "../ActivityShell";

describe("ActivityShell", () => {
  it("renders exactly Runs, Approvals, and Audit", () => {
    render(<MemoryRouter initialEntries={["/activity/runs"]}><ActivityShell><div>Existing screen content</div></ActivityShell></MemoryRouter>);

    expect(activityTabs.map((tab) => tab.label)).toEqual(["Runs", "Approvals", "Audit"]);
    expect(screen.getByRole("heading", { name: "Activity" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute("href", "/activity/runs");
    expect(screen.getByRole("link", { name: "Approvals" })).toHaveAttribute("href", "/approvals");
    expect(screen.getByRole("link", { name: "Audit" })).toHaveAttribute("href", "/audit");
    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText("Existing screen content")).toBeInTheDocument();
  });
});
