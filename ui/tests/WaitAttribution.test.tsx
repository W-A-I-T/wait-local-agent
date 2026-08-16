import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WaitAttribution } from "../src/components/WaitAttribution";


describe("WaitAttribution", () => {
  it("renders the required Community attribution visibly", () => {
    render(<WaitAttribution />);

    const attribution = screen.getByRole("contentinfo", { name: "WAIT attribution" });
    expect(attribution).toBeVisible();
    expect(attribution).toHaveTextContent("Powered by WAIT");
  });
});
