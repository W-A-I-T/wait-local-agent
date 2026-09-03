import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Collectors } from "../src/screens/Collectors";

vi.mock("../src/app/DashboardContext", () => ({
  useDashboard: () => ({ canWrite: true, selectedClientId: "", clients: [], isMspAdmin: true })
}));

const moduleFixture = {
  id: "host-runtime",
  name: "Host Runtime Inventory",
  version: "0.1.0",
  description: "Read-only inventory of the local host.",
  capabilities: ["local_host_inventory"],
  scopes: ["local_host"],
  report_types: ["collector_bundle"],
  platforms: ["linux"],
  config_schema: [
    {
      name: "source_name",
      label: "Source name",
      help: "A friendly name for this source.",
      type: "string",
      required: true
    },
    { name: "limit", label: "Maximum items", type: "number", required: false }
  ]
};

const runRow = {
  id: 7,
  module_id: "host-runtime",
  source_id: 3,
  status: "completed",
  mode: "confirmed",
  result_status: "partial",
  created_at: "2026-08-07T00:00:00Z",
  updated_at: "2026-08-07T00:01:00Z",
  started_at: "2026-08-07T00:00:10Z",
  completed_at: "2026-08-07T00:01:00Z"
};

const runDetail = {
  ...runRow,
  result_json: JSON.stringify({
    status: "partial",
    collection_scope: "container",
    source_outcomes: [
      {
        source_id: "socket:tcp",
        status: "not_authorized",
        record_count: 0,
        error_code: "permission",
        error_detail: "backend PermissionError with private detail",
        remediation_hint: "Check the saved credential for this source."
      }
    ]
  }),
  assets: [],
  observations: [],
  config_snapshots: [],
  config_diffs: [],
  restore_exercises: []
};

describe("Collectors screen", () => {
  let runsAvailable: boolean;
  let validationResponse: { passed: boolean; message: string; errors: string[] };

  beforeEach(() => {
    runsAvailable = false;
    validationResponse = { passed: true, message: "ok", errors: [] };
    window.localStorage.clear();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/collectors/modules") {
        return json([moduleFixture]);
      }
      if (path === "/collectors/runs") {
        return json(runsAvailable ? [runRow] : []);
      }
      if (path === "/collectors/modules/host-runtime/validate") {
        return json({ module_id: "host-runtime", ...validationResponse });
      }
      if (path === "/collectors/modules/host-runtime/preview") {
        return json({
          module_id: "host-runtime",
          source_name: "demo",
          scopes: ["local_host", "network_sockets"],
          estimated_assets: 1,
          estimated_observations: 3,
          expected_reports: ["collector_bundle"],
          metadata: {}
        });
      }
      if (path === "/collectors/modules/host-runtime/run" && init?.method === "POST") {
        runsAvailable = true;
        return json({ ...runRow, id: 7 });
      }
      if (path === "/collectors/runs/7") {
        return json(runDetail);
      }
      if (path === "/collectors/runs/7/export" && init?.method === "POST") {
        return json({ report_type: "collector_bundle", title: "Collector bundle", sections: [] });
      }
      throw new Error(`Unexpected request: ${path}`);
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("walks validate, preview, and a deliberate run with plain-language outcomes", async () => {
    render(<Collectors />);

    // Generated form from the manifest, with an instructive first-run state.
    const sourceName = await screen.findByLabelText("Source name");
    const sourceNameLabel = screen.getByText("Source name", { selector: "label" });
    expect(sourceNameLabel).toHaveAttribute("for", sourceName.id);
    expect(sourceName).toHaveAttribute("id", "collector-host-runtime-source_name");
    expect(sourceName).toBeRequired();
    expect(sourceName).toHaveAttribute("aria-required", "true");
    const limit = screen.getByLabelText("Maximum items");
    const limitLabel = screen.getByText("Maximum items", { selector: "label" });
    expect(limitLabel).toHaveAttribute("for", limit.id);
    expect(limit).toHaveAttribute("id", "collector-host-runtime-limit");
    expect(limit).not.toBeRequired();
    expect(limit).not.toHaveAttribute("aria-required");
    expect(screen.getByText("A friendly name for this source.")).toBeInTheDocument();
    expect(screen.getByText(/No runs yet/)).toBeInTheDocument();

    // Required-field check blocks the call before anything is sent.
    fireEvent.click(screen.getByRole("button", { name: "Check settings" }));
    expect(await screen.findByText("Source name is required.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(
      "/collectors/modules/host-runtime/validate",
      expect.anything()
    );

    fireEvent.change(sourceName, { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: "Check settings" }));
    expect((await screen.findAllByText(/Settings look good/)).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "Preview" }));
    expect(await screen.findByText(/Preview ready/)).toBeInTheDocument();
    expect(screen.getByText(/Covers: This computer, Network connections/)).toBeInTheDocument();
    expect(screen.getByText(/Expects about 1 items and 3 observations/)).toBeInTheDocument();

    // Running stays a deliberate two-step action.
    fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(await screen.findByText(/Run Host Runtime Inventory now\?/)).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(
      "/collectors/modules/host-runtime/run",
      expect.anything()
    );

    fireEvent.click(screen.getByRole("button", { name: "Yes, run it" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/collectors/modules/host-runtime/run",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ config: { source_name: "demo" }, confirm: true })
        })
      );
    });

    // Plain-language statuses, container honesty, and per-source hints.
    expect((await screen.findAllByText("Done")).length).toBeGreaterThan(0);
    expect((await screen.findAllByText("Partly collected")).length).toBeGreaterThan(0);
    expect(screen.getByText("Collected from inside the app's container")).toBeInTheDocument();
    expect(screen.getByText("Network socket (TCP)")).toBeInTheDocument();
    const sourceId = screen.getByText("Source ID: socket:tcp");
    expect(sourceId.closest("details")).toHaveTextContent("Technical details");
    expect(screen.getByText("No permission — check the credentials")).toBeInTheDocument();
    expect(screen.getByText("Check the saved credential for this source.")).toBeInTheDocument();
    expect(screen.queryByText("backend PermissionError with private detail")).not.toBeInTheDocument();
  });

  it("humanizes validation text and keeps the backend wording in technical details", async () => {
    validationResponse = {
      passed: false,
      message: "collector configuration is invalid",
      errors: ["missing network_sockets"]
    };
    render(<Collectors />);

    await screen.findByLabelText("Source name");
    fireEvent.change(screen.getByLabelText("Source name"), { target: { value: "demo" } });
    fireEvent.click(screen.getByRole("button", { name: "Check settings" }));

    expect(await screen.findByText("The collector settings are not valid.")).toBeInTheDocument();
    expect(screen.getByText("Missing network sockets")).toBeInTheDocument();
    const details = screen.getByText("collector configuration is invalid");
    expect(details.closest("details")).toBeInTheDocument();
  });

  it("exports a run with the backend's POST contract and renders the report", async () => {
    runsAvailable = true;
    render(<Collectors />);

    fireEvent.click(await screen.findByRole("button", { name: "Export" }));
    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "/collectors/runs/7/export",
        expect.objectContaining({ method: "POST" })
      );
    });
    const exportCall = vi.mocked(fetch).mock.calls.find(([input]) => String(input) === "/collectors/runs/7/export");
    expect(exportCall?.[1]?.body).toBeUndefined();
    expect(await screen.findByText(/Collector bundle/)).toBeInTheDocument();
  });
});

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" }
  });
}
