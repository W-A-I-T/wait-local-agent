import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AutomationsShell, automationTabs } from "../AutomationsShell";

describe("AutomationsShell", () => {
  it("renders every automation surface and keeps the active tab on the current route", () => {
    render(
      <MemoryRouter initialEntries={["/templates"]}>
        <AutomationsShell><div>Existing screen content</div></AutomationsShell>
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: "Automations" })).toBeInTheDocument();
    expect(screen.getByText("My templates", { selector: ".automations-subtitle" })).toBeInTheDocument();
    expect(screen.getByText(automationTabs[2].description)).toBeInTheDocument();
    expect(screen.getByText("Existing screen content")).toBeInTheDocument();

    for (const tab of automationTabs) {
      expect(screen.getByRole("link", { name: tab.label })).toHaveAttribute("href", tab.to);
    }
    expect(screen.getByRole("link", { name: "My templates" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Run" })).not.toHaveAttribute("aria-current", "page");
  });

  it.each(automationTabs)("shows the $label description when its route is active", (tab) => {
    render(
      <MemoryRouter initialEntries={[tab.to]}>
        <AutomationsShell><div /></AutomationsShell>
      </MemoryRouter>
    );

    expect(screen.getByText(tab.description)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: tab.label })).toHaveAttribute("aria-current", "page");
  });

  it("links Run history to Activity from the Run tab description", () => {
    render(
      <MemoryRouter initialEntries={["/workflows"]}>
        <AutomationsShell><div /></AutomationsShell>
      </MemoryRouter>
    );

    expect(screen.getByRole("link", { name: "Run history → Activity" })).toHaveAttribute("href", "/executions");
  });
});
