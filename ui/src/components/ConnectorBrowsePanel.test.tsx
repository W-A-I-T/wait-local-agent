import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { ConnectorBrowsePanel } from "./ConnectorBrowsePanel";

vi.mock("../api/client", () => ({
  apiFetch: vi.fn()
}));

const mockedApiFetch = vi.mocked(apiFetch);

function renderPanel(pageSize = 25) {
  return render(
    <ConnectorBrowsePanel
      title="Autotask"
      healthPath="/connectors/autotask/health"
      lists={[
        { label: "Tickets", path: "/connectors/autotask/tickets" },
        { label: "Companies", path: "/connectors/autotask/companies" }
      ]}
      pageSize={pageSize}
    />
  );
}

describe("ConnectorBrowsePanel", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("renders health and auto-derived columns for the first list", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/connectors/autotask/health") return Promise.resolve({ status: "ready", count: 1 }) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ items: [{ external_id: "T-1", subject: "Printer", details: { priority: "high" } }] }) as ReturnType<typeof apiFetch>;
    });

    renderPanel();

    expect(await screen.findByText("ready · 1")).toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "external_id" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "subject" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "details" })).toBeInTheDocument();
    expect(screen.getByText('{"priority":"high"}')).toBeInTheDocument();
  });

  it("switches lists and requests the second endpoint", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/connectors/autotask/health") return Promise.resolve({ status: "ready" }) as ReturnType<typeof apiFetch>;
      if (path.startsWith("/connectors/autotask/companies")) return Promise.resolve({ items: [{ company_code: "C-1" }] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ items: [{ ticket_code: "T-1" }] }) as ReturnType<typeof apiFetch>;
    });

    renderPanel();
    expect(await screen.findByText("ticket_code")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Companies" }));

    expect(await screen.findByText("company_code")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/autotask/companies?page=1&page_size=25");
  });

  it("changes the page query and supports returning to the previous page", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/connectors/autotask/health") return Promise.resolve({ status: "ready" }) as ReturnType<typeof apiFetch>;
      if (path.includes("page=1")) return Promise.resolve({ items: [{ id: 1 }, { id: 2 }] }) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ items: [{ id: 3 }] }) as ReturnType<typeof apiFetch>;
    });

    renderPanel(2);
    const next = await screen.findByRole("button", { name: "Next" });
    fireEvent.click(next);
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/autotask/tickets?page=2&page_size=2"));
    expect(screen.getByText("Page 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Prev" }));
    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith("/connectors/autotask/tickets?page=1&page_size=2"));
    expect(screen.getByText("Page 1")).toBeInTheDocument();
  });

  it("renders empty, not-configured, and error states without write controls", async () => {
    mockedApiFetch.mockRejectedValue(new Error("Autotask is not configured"));

    renderPanel();

    expect(await screen.findByText("Autotask is unavailable or not configured.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Autotask is not configured");
    expect(screen.queryByText("No records.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /post|execute|write/i })).not.toBeInTheDocument();
  });

  it("renders an empty list without assuming provider fields", async () => {
    mockedApiFetch.mockImplementation((path) => {
      if (path === "/connectors/autotask/health") return Promise.resolve({ status: "empty", count: 0 }) as ReturnType<typeof apiFetch>;
      return Promise.resolve({ items: [] }) as ReturnType<typeof apiFetch>;
    });

    renderPanel();

    expect(await screen.findByText("No records.")).toBeInTheDocument();
  });
});
