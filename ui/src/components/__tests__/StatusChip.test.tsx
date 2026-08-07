import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ScopeChip, StatusChip } from "../StatusChip";

describe("StatusChip", () => {
  it.each([
    ["success", "Working"],
    ["empty", "Nothing found"],
    ["partial", "Partly collected"],
    ["not_authorized", "No permission — check the credentials"],
    ["unavailable", "Couldn't reach it"],
    ["completed", "Done"],
    ["failed", "Didn't finish"],
    ["running", "Running"]
  ])("maps %s to plain language", (status, label) => {
    render(<StatusChip status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("shows the remediation hint verbatim", () => {
    render(<StatusChip status="not_authorized" hint="Check the saved credential for this source." />);

    const hint = screen.getByText("Check the saved credential for this source.");
    expect(hint).toBeInTheDocument();
    expect(screen.getByText("No permission — check the credentials")).toHaveAttribute(
      "title",
      "Check the saved credential for this source."
    );
  });

  it("renders unknown statuses without protocol styling", () => {
    render(<StatusChip status="mystery_state" />);
    expect(screen.getByText("Mystery state")).toBeInTheDocument();
  });
});

describe("ScopeChip", () => {
  it("labels host-scoped runs", () => {
    render(<ScopeChip scope="host" />);
    expect(screen.getByText("Collected from this computer")).toBeInTheDocument();
  });

  it("labels container-scoped runs", () => {
    render(<ScopeChip scope="container" />);
    expect(screen.getByText("Collected from inside the app's container")).toBeInTheDocument();
  });

  it("renders nothing for an unknown scope", () => {
    const { container } = render(<ScopeChip scope="elsewhere" />);
    expect(container).toBeEmptyDOMElement();
  });
});
