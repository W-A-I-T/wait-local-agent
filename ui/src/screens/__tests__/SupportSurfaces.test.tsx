import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Audit } from "../Audit";
import { Settings } from "../Settings";
import { TechnicianPath } from "../TechnicianPath";
import { useDashboard } from "../../app/DashboardContext";

vi.mock("../../app/DashboardContext", () => ({ useDashboard: vi.fn() }));

const mockedUseDashboard = vi.mocked(useDashboard);

describe("support surfaces", () => {
  beforeEach(() => {
    mockedUseDashboard.mockReturnValue({ isAdmin: true, loading: true, role: "admin" } as never);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("shows licensing facts and pack signature state without a license value", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "local", offline_mode: true });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: true, demo_mode: false });
      if (path === "/packs") {
        return jsonResponse([{ name: "core", version: "1.0.0", locked: false, requires_license: false, signature_status: "not_recorded" }]);
      }
      if (path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "idle", detail: "disabled" });
      throw new Error(`Unexpected request: ${path}`);
    }));

    render(<MemoryRouter><Settings /></MemoryRouter>);

    expect(await screen.findByText("AGPL-3.0-only with WAIT additional terms")).toBeInTheDocument();
    expect(screen.getByText("Signature record: Not recorded")).toBeInTheDocument();
    expect(screen.queryByText(/license key/i)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read the community and commercial use guide" })).toHaveAttribute(
      "href",
      expect.stringContaining("community-vs-commercial-use.md")
    );
  });

  it("keeps the local audit privacy notice visible", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse([])));
    render(<Audit />);

    expect(await screen.findByRole("note")).toHaveTextContent("Audit data stays on this appliance");
    expect(screen.getByRole("note")).toHaveTextContent("never transmitted to WAIT");
  });

  it("links every technician step to the real workspace", () => {
    render(<MemoryRouter><TechnicianPath /></MemoryRouter>);

    const destinations = ["/tickets", "/technician-chat", "/technician-chat", "/approvals", "/audit"];
    expect(screen.getAllByRole("link", { name: "Open" }).map((link) => link.getAttribute("href"))).toEqual(destinations);
  });
});

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { headers: { "Content-Type": "application/json" } });
}
