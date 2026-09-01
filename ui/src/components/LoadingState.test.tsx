import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LoadingState } from "./LoadingState";

describe("LoadingState", () => {
  it("announces a busy loading panel", () => {
    render(<LoadingState label="Loading records…" />);

    expect(screen.getByText("Loading records…")).toBeInTheDocument();
    expect(screen.getByText("Loading records…").closest(".loading-state")).toHaveAttribute("aria-busy", "true");
  });
});
