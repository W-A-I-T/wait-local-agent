import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "../src/App";

describe("App", () => {
  it("renders ticket intelligence dashboard", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Ticket Intelligence" })).toBeInTheDocument();
    expect(screen.getByText("TCK-1001")).toBeInTheDocument();
    expect(screen.getByText("Safe defaults active")).toBeInTheDocument();
  });
});

