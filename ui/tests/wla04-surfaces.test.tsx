import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Settings } from "../src/screens/Settings";
import { Knowledge, parserPayload } from "../src/screens/Knowledge";
import { FounderJourney } from "../src/surfaces/founder/FounderJourney";
import { OnboardingWizard } from "../src/surfaces/onboarding/OnboardingWizard";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ isAdmin: true, canWrite: true, refresh: vi.fn() })
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("wla-04 onboarding and parity surfaces", () => {
  it("normalizes the UI parser names to the backend parser contract", () => {
    expect(parserPayload("auto")).toBe("");
    expect(parserPayload("plain")).toBe("basic");
    expect(parserPayload("markdown")).toBe("basic");
    expect(parserPayload("pdf")).toBe("pypdf");
  });

  it("maps every knowledge parser option to the backend parser contract", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/knowledge/documents") return jsonResponse([]);
      if (String(input) === "/knowledge/ingest") return jsonResponse([]);
      throw new Error(`Unexpected request: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<Knowledge />);
    const parser = await screen.findByLabelText("Parser");
    expect(Array.from(parser.querySelectorAll("option")).map((option) => option.value)).toEqual(["auto", "plain", "markdown", "pdf"]);

    fireEvent.change(screen.getByPlaceholderText("/path/to/docs"), { target: { value: "/workspace/knowledge" } });
    fireEvent.click(screen.getByRole("button", { name: "Run ingest" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/knowledge/ingest",
      expect.objectContaining({
        body: JSON.stringify({ path: "/workspace/knowledge", parser: "", ocr: true })
      })
    ));
  });

  it("guides onboarding through real configuration screens before optional ingest and demo calls", async () => {
    const onDone = vi.fn();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/knowledge/ingest") {
        return jsonResponse([{ path: "runbook.md" }]);
      }
      if (path === "/tickets/TCK-1001/summary") {
        return jsonResponse({
          ticket_id: "TCK-1001",
          classification: "service",
          summary: "Printer offline",
          suggested_response: "A technician will follow up.",
          sources: []
        });
      }
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <OnboardingWizard onDone={onDone} onDismiss={vi.fn()} />
      </MemoryRouter>
    );

    expect(screen.getByText("Create a client")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open client configuration" })).toHaveAttribute("href", "/clients?onboarding=1&step=0");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Open connector instance configuration" })).toHaveAttribute("href", "/integrations/connector-instances?onboarding=1&step=1");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByRole("link", { name: "Open mapping verification" })).toHaveAttribute("href", "/integrations/connector-instances?onboarding=1&step=2#connector-mappings-heading");

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByPlaceholderText("/path/to/knowledge")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("/path/to/knowledge"), { target: { value: "/workspace/knowledge" } });

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByLabelText("Demo ticket id")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Run ticket summary" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/tickets/TCK-1001/summary", expect.anything()));
    fireEvent.click(screen.getByRole("button", { name: "Complete" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());

    expect(fetchMock).toHaveBeenCalledWith("/knowledge/ingest", expect.objectContaining({ method: "POST" }));
    expect(fetchMock).toHaveBeenCalledWith("/knowledge/ingest", expect.objectContaining({
      body: JSON.stringify({ path: "/workspace/knowledge", parser: "basic" })
    }));
  });

  it("links connector setup to the real connector surface", async () => {
    render(
      <MemoryRouter>
        <OnboardingWizard initialStep={1} onDone={vi.fn()} onDismiss={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.getByRole("link", { name: "Open connector instance configuration" })).toHaveAttribute("href", "/integrations/connector-instances?onboarding=1&step=1");
  });

  it("renders the friendly Founder Pack install state for a 501 response", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ error: "founder pack not installed" }, 501));
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <FounderJourney />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByPlaceholderText("/path/to/your-project"), { target: { value: "/workspace/launcher" } });
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

  it("requires explicit acknowledgement before restoring local state", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/settings/providers") return jsonResponse({ local_model_provider: "demo", vector_backend: "local" });
      if (path === "/settings/security") return jsonResponse({ api_token_configured: false, demo_mode: true });
      if (path === "/packs" || path === "/secrets") return jsonResponse([]);
      if (path === "/update-status") return jsonResponse({ status: "current", detail: "No update available." });
      if (path === "/founder/lp-status") return jsonResponse({ error: "launch passport not configured" }, 409);
      if (path === "/backups/restore") return jsonResponse({ restored: "/workspace/state.db", encrypted: false });
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <MemoryRouter>
        <Settings />
      </MemoryRouter>
    );

    await screen.findByText("Settings loaded.");
    const restoreButton = screen.getByRole("button", { name: "Restore" });
    expect(restoreButton).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "/workspace/state.db" } });
    expect(restoreButton).toBeDisabled();
    fireEvent.click(screen.getByLabelText("I understand this replaces the current local state"));
    expect(restoreButton).toBeEnabled();
    fireEvent.click(restoreButton);

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/backups/restore",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ source: "/workspace/state.db", encrypted: false })
      })
    ));
    expect(await screen.findByText("Restore requested.")).toBeInTheDocument();
  });
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" }
  });
}
