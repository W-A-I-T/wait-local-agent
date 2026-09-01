import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ActivityShell, activityTabs } from "../ActivityShell";

describe("ActivityShell", () => {
  it("renders every activity surface and keeps the active tab on the current route", () => {
    render(
      <MemoryRouter initialEntries={["/smart-actions/runs"]}>
        <ActivityShell><div>Existing screen content</div></ActivityShell>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: "Activity & scheduling" })).toBeInTheDocument();
    expect(screen.getByText("Smart Action Runs", { selector: ".automations-subtitle" })).toBeInTheDocument();
    expect(screen.getByText(activityTabs[3].description)).toBeInTheDocument();
    expect(screen.getByText("Existing screen content")).toBeInTheDocument();

    for (const tab of activityTabs) {
      expect(screen.getByRole("link", { name: tab.label })).toHaveAttribute("href", tab.to);
    }
    expect(screen.getByRole("link", { name: "Smart Action Runs" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Events" })).not.toHaveAttribute("aria-current", "page");
  });

  it.each(activityTabs)("shows the $label description when its route is active", (tab) => {
    render(
      <MemoryRouter initialEntries={[tab.to]}>
        <ActivityShell><div /></ActivityShell>
      </MemoryRouter>
    );

    expect(screen.getByText(tab.description)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: tab.label })).toHaveAttribute("aria-current", "page");
  });
});
