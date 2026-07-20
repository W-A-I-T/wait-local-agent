import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Settings } from "../src/screens/Settings";
import { FounderJourney } from "../src/surfaces/founder/FounderJourney";
import { OnboardingWizard } from "../src/surfaces/onboarding/OnboardingWizard";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ isAdmin: true })
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("wla-04 onboarding and parity surfaces", () => {
  it("progresses through onboarding steps and runs the ingest and demo summary calls", async () => {
    const onDone = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/connectors/halopsa/health") {
        return jsonResponse({ status: "ready", message: "HaloPSA is ready." });
      }
      if (path === "/knowledge/ingest") {
        return jsonResponse([{ path: "runbook.md" }]);
      }
      if (path === "/tickets/HALO-1/summary") {
        return jsonResponse({
          ticket_id: "HALO-1",
          classification: "service",
          summary: "Printer offline",
          suggested_response: "A technician will follow up.",
          sources: []
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<OnboardingWizard onDone={onDone} onDismiss={vi.fn()} />);

    expect(screen.getByText("Choose your primary PSA provider")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByLabelText("API token")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByPlaceholderText("/path/to/knowledge")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("/path/to/knowledge"), { target: { value: "/workspace/knowledge" } });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Ready to ingest from /workspace/knowledge")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByLabelText("Demo ticket id")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());

    expect(fetchMock).toHaveBeenCalledWith("/knowledge/ingest", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenCalledWith("/tickets/HALO-1/summary", expect.anything());
  });

  it("renders the friendly Founder Pack install state for a 501 response", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ error: "founder pack not installed" }, 501));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <FounderJourney />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("/path/to/launcher-project"), { target: { value: "/workspace/launcher" } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText(/Founder Pack is not installed/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Settings / Packs" })).toHaveAttribute("href", "/settings");
    expect(fetchMock).toHaveBeenCalledWith("/founder/scan", expect.objectContaining({ method: "POST" }));
  });

  it("submits an admin backup request from Settings", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") {
        return jsonResponse({ local_model_provider: "demo", vector_backend: "local" });
      }
      if (path === "/settings/security") {
        return jsonResponse({ api_token_configured: false, demo_mode: true });
      }
      if (path === "/packs" || path === "/secrets") {
        return jsonResponse([]);
      }
      if (path === "/update-status") {
        return jsonResponse({ status: "current", detail: "No update available." });
      }
      if (path === "/backups") {
        return jsonResponse({ status: "queued" });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    );

    await screen.findByText("Settings loaded.");
    fireEvent.change(screen.getByLabelText("Destination"), { target: { value: "/workspace/backups" } });
    fireEvent.click(screen.getByLabelText("Encrypt backup"));
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "/backups",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ destination: "/workspace/backups", encrypt: true })
        })
      );
    });
    expect(await screen.findByText("Backup requested.")).toBeInTheDocument();
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
