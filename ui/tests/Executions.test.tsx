import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Executions } from "../src/screens/Executions";

describe("Executions", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/executions" || path.startsWith("/executions?")) return Promise.resolve(new Response(JSON.stringify([{
        id: 4,
        run_kind: "agent",
        source_run_id: 9,
        actor: "operator",
        status: "completed",
        started_at: "2026-08-08T00:00:00Z",
        finished_at: "2026-08-08T00:00:02Z",
        trigger_source: "manual",
        client_id: "acme"
      }]), { status: 200 }));
      if (path === "/executions/4") return Promise.resolve(new Response(JSON.stringify({
        id: 4,
        run_kind: "agent",
        source_run_id: 9,
        actor: "operator",
        status: "completed",
        started_at: "2026-08-08T00:00:00Z",
        finished_at: "2026-08-08T00:00:02Z",
        trigger_source: "manual",
        client_id: "acme",
        steps: [{ id: 8, ordinal: 0, kind: "tool.invoke", name: "Ticket triage", status: "success", started_at: "", finished_at: "", output: { classification: "network" }, error_detail: "" }],
        artifacts: [{ id: 2, step_ordinal: 0, name: "summary.json", media_type: "application/json", byte_size: 42, sha256: "abc123" }]
      }), { status: 200 }));
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("lists executions and opens redacted step and artifact metadata", async () => {
    render(<MemoryRouter><Executions /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Execution History" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Run #4/ }));
    expect(await screen.findByRole("heading", { name: "Run #4" })).toBeInTheDocument();
    expect(screen.getByText(/Ticket triage/)).toBeInTheDocument();
    expect(screen.getByText(/classification/)).toBeInTheDocument();
    expect(screen.getByText("summary.json")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Run kind"), { target: { value: "agent" } });
    await waitFor(() => expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL]> } }).mock.calls.some(([input]) => String(input) === "/executions?kind=agent")).toBe(true));
  });
});
