import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Audit } from "../src/screens/Audit";

describe("Audit export filters", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/audit") return Promise.resolve(new Response(JSON.stringify([]), { status: 200 }));
      if (path.startsWith("/audit-events/export?")) return Promise.resolve(new Response("id,event_type\n", { status: 200 }));
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("sends format and date range parameters to the audit export route", async () => {
    render(<Audit />);

    await screen.findByRole("heading", { name: "Audit" });
    fireEvent.change(screen.getByLabelText("From date"), { target: { value: "2026-08-01" } });
    fireEvent.change(screen.getByLabelText("To date"), { target: { value: "2026-08-08" } });
    fireEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/audit-events/export?format=csv&from=2026-08-01T00%3A00%3A00Z&to=2026-08-08T23%3A59%3A59Z",
      expect.anything()
    ));
  });
});
