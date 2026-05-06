import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "../src/App";

describe("App", () => {
  it("renders ticket intelligence dashboard", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Ticket Intelligence" })).toBeInTheDocument();
    expect(screen.getAllByText("TCK-1001").length).toBeGreaterThan(0);
    expect(screen.getByText("Safe defaults active")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Knowledge Index" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Approval Queue" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Workflow Templates" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Connector Readiness" })).toBeInTheDocument();
    expect(screen.getAllByText("HaloPSA").length).toBeGreaterThan(0);
  });
});
