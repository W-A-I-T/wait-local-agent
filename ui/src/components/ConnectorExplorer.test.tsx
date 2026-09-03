import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import type { ConnectorStatus } from "../api/types";
import { ConnectorExplorer } from "./ConnectorExplorer";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const mockedApiFetch = vi.mocked(apiFetch);
const fixtureConnectors: ConnectorStatus[] = [
  { id: "servicenow", name: "ServiceNow", status: "ready", message: "configured" },
  { id: "scalepad", name: "ScalePad", status: "ready", message: "configured" }
];

describe("ConnectorExplorer", () => {
  beforeEach(() => mockedApiFetch.mockReset());

  it("loads a fixture connector, paginates, and opens row detail", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/connectors/servicenow/health") return Promise.resolve({ status: "ready", message: "healthy" }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/servicenow/incidents?page=1&page_size=25") return Promise.resolve({ items: Array.from({ length: 25 }, (_, index) => ({ sys_id: index === 0 ? "inc-1" : `inc-${index + 1}`, number: `INC${String(index + 1).padStart(3, "0")}`, short_description: "Printer" })) }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/servicenow/incidents?page=2&page_size=25") return Promise.resolve({ items: [{ sys_id: "inc-2", number: "INC002", short_description: "Laptop" }] }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/servicenow/incidents/inc-1") return Promise.resolve({ items: [{ sys_id: "inc-1", number: "INC001", detail: "Full incident" }] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ items: [] }) as ReturnType<typeof apiFetch>;
    });

    render(<ConnectorExplorer connectors={fixtureConnectors} />);

    expect(await screen.findByRole("columnheader", { name: "number" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open Incidents record inc-1" }));
    expect(await screen.findByText(/Full incident/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/servicenow/incidents?page=2&page_size=25"));
    expect(screen.getByText("INC002")).toBeInTheDocument();
  });

  it("shows posture guidance without requesting an empty table when blocked", async () => {
    render(<ConnectorExplorer connectors={[{ id: "hudu", name: "Hudu", status: "blocked", message: "not configured" }]} />);

    expect(await screen.findByText(/Hudu is unavailable or not configured/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("Technical details"));
    expect(screen.getByText("WAIT_HUDU_BASE_URL")).toBeInTheDocument();
    expect(screen.queryByText("No records returned.")).not.toBeInTheDocument();
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it("renders ScalePad QBR fixture tables", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/connectors/scalepad/health") return Promise.resolve({ status: "ready", message: "healthy" }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/scalepad/risk-summaries") return Promise.resolve({ items: [{ risk_level: "high", risk_score: 82 }] }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/scalepad/compliance-health") return Promise.resolve({ item: { health_score: 94, status: "healthy" } }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/scalepad/goals") return Promise.resolve({ items: [{ title: "MFA", status: "OnTrack" }] }) as ReturnType<typeof apiFetch>;
      if (path === "/connectors/scalepad/assessments") return Promise.resolve({ items: [{ title: "Baseline", status: "Completed" }] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ items: [] }) as ReturnType<typeof apiFetch>;
    });

    render(<ConnectorExplorer connectors={fixtureConnectors} />);
    fireEvent.click(screen.getByRole("tab", { name: "ScalePad QBR" }));

    expect(await screen.findByText("ScalePad QBR data")).toBeInTheDocument();
    expect(await screen.findByText("high")).toBeInTheDocument();
    expect(await screen.findByText("94")).toBeInTheDocument();
    expect(await screen.findByText("MFA")).toBeInTheDocument();
    expect(await screen.findByText("Baseline")).toBeInTheDocument();
  });
});
