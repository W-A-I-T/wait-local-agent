import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Templates } from "../src/screens/Templates";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true })
}));

describe("Templates", () => {
  const entry = {
    id: "gallery-acme",
    source_template_id: "ticket-triage",
    name: "Acme triage",
    trigger: "ticket.created",
    description: "Review Acme tickets.",
    action_type: "ticket.triage",
    approval_required: false,
    risk_level: "low",
    preview_fields: ["classification"],
    provenance: "local review",
    instructions: "Use the local policy.",
    enabled: true,
    version: 1,
    created_at: "2026-08-08T00:00:00Z",
    updated_at: "2026-08-08T00:00:00Z",
    client_id: "acme"
  };

  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/workflows/templates") {
        return Promise.resolve(new Response(JSON.stringify([{
          id: "ticket-triage",
          name: "Ticket Triage",
          trigger: "ticket.created",
          description: "Classify tickets.",
          action_type: "ticket.triage",
          approval_required: false,
          risk_level: "low",
          preview_fields: ["classification"]
        }]), { status: 200 }));
      }
      if (path === "/workflow-templates/gallery" && !init?.method) {
        return Promise.resolve(new Response(JSON.stringify([entry]), { status: 200 }));
      }
      if (path === "/workflow-templates/gallery/gallery-acme" && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body));
        return Promise.resolve(new Response(JSON.stringify({ ...entry, ...body, version: 2 }), { status: 200 }));
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  it("renders and saves an editable local template definition", async () => {
    render(<MemoryRouter><Templates /></MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "Template Gallery" })).toBeInTheDocument();
    const name = screen.getByLabelText("Name");
    fireEvent.change(name, { target: { value: "Acme triage updated" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(screen.getByText("Saved Acme triage updated as version 2.")).toBeInTheDocument());
    expect((vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL, RequestInit?]> } }).mock.calls.some(
      ([input, init]) => String(input) === "/workflow-templates/gallery/gallery-acme" && init?.method === "PATCH"
    )).toBe(true);
  });
});
