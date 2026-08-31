import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { AutomationDiscoveryPanel } from "./AutomationDiscoveryPanel";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
const mockedApiFetch = vi.mocked(apiFetch);

const result = {
  client_id: "acme",
  window_days: 60,
  ticket_count: 120,
  opportunity_count: 1,
  opportunities: [
    {
      category_id: "password-mfa-authentication",
      label: "Password resets, MFA and sign-in",
      ticket_count: 18,
      measured_labor_available: true,
      measured_labor_minutes: 360,
      measured_labor_ticket_count: 18,
      estimated_automation_minutes: 144,
      estimate: true,
      readiness: "ready_for_review",
      workflow_matches: [
        { id: "m365-password-reset-review", name: "Microsoft 365 Password Reset Review", approval_required: true, risk_level: "high", available: true }
      ],
      playbook_matches: [],
      prerequisites: [{ family: "m365", status: "verified" }],
      source_ticket_ids: ["T-1", "T-2"],
      source_ticket_ids_truncated: false,
      reason: "18 historical tickets matched the deterministic service pattern."
    }
  ],
  labor: {
    measured_minutes: 360,
    measured: true,
    measured_ticket_count: 18,
    estimate_minutes: 144,
    estimate: true,
    derivation: "Measured labor uses normalized PSA time entries only."
  },
  mapping_readiness: {
    verified_count: 3,
    unverified_count: 1,
    families: { m365: { verified: 1, unverified: 0 } }
  },
  side_effects: false,
  automation_enabled: false,
  next_step: "Review the opportunity before enabling anything."
};

describe("AutomationDiscoveryPanel", () => {
  beforeEach(() => mockedApiFetch.mockReset());

  it("requires a client before running discovery", () => {
    render(<AutomationDiscoveryPanel />);
    fireEvent.click(screen.getByRole("button", { name: "Analyze ticket history" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Select a client");
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it("loads and renders evidence-backed opportunities", async () => {
    mockedApiFetch.mockResolvedValue(result);
    render(<AutomationDiscoveryPanel />);

    fireEvent.change(screen.getByLabelText("Discovery client ID"), { target: { value: " acme " } });
    fireEvent.change(screen.getByLabelText("History window"), { target: { value: "90" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze ticket history" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/automation-discovery/historical?client_id=acme&days=90&min_tickets=3"
    ));
    expect(await screen.findByText(/Password resets, MFA and sign-in/)).toBeInTheDocument();
    expect(screen.getByText("360 min")).toBeInTheDocument();
    expect(screen.getByText(/Microsoft 365 Password Reset Review/)).toBeInTheDocument();
    expect(screen.getByText(/m365=verified/)).toBeInTheDocument();
    expect(screen.getByText(/T-1, T-2/)).toBeInTheDocument();
    expect(screen.getByText(/Review the opportunity before enabling anything/)).toBeInTheDocument();
  });

  it("renders API failures without retaining stale results", async () => {
    mockedApiFetch.mockImplementation(async () => {
      throw new Error("mapping scope required");
    });
    render(<AutomationDiscoveryPanel />);
    fireEvent.change(screen.getByLabelText("Discovery client ID"), { target: { value: "acme" } });
    fireEvent.click(screen.getByRole("button", { name: "Analyze ticket history" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("mapping scope required");
  });
});
