import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PaginatedEvidenceTable } from "./PaginatedEvidenceTable";

describe("PaginatedEvidenceTable", () => {
  it("loads pages, supports cursor previous/next navigation, and opens raw details", async () => {
    const loadPage = vi.fn()
      .mockResolvedValueOnce({
        result: { status: "ready", message: "ok", count: 1 },
        items: [{ id: "user-1", name: "Adele Vance", risk_level: "high" }],
        next_cursor: "$skiptoken=next"
      })
      .mockResolvedValueOnce({
        result: { status: "ready", message: "ok", count: 1 },
        items: [{ id: "user-2", name: "Maya Patel", risk_level: "medium" }],
        next_cursor: ""
      })
      .mockResolvedValueOnce({
        result: { status: "ready", message: "ok", count: 1 },
        items: [{ id: "user-1", name: "Adele Vance", risk_level: "high" }],
        next_cursor: "$skiptoken=next"
      });

    render(
      <PaginatedEvidenceTable
        title="Risky users"
        columns={[{ key: "name", label: "Name" }, { key: "risk_level", label: "Risk" }]}
        loadPage={loadPage}
        onClose={vi.fn()}
      />
    );

    expect(await screen.findByText("Adele Vance")).toBeInTheDocument();
    expect(loadPage).toHaveBeenNthCalledWith(1, null);
    fireEvent.click(screen.getByRole("button", { name: "Show details for Adele Vance" }));
    expect(screen.getByRole("dialog")).toHaveTextContent('"risk_level": "high"');
    fireEvent.click(screen.getByRole("button", { name: "Close details" }));

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Maya Patel")).toBeInTheDocument();
    expect(loadPage).toHaveBeenNthCalledWith(2, "$skiptoken=next");
    fireEvent.click(screen.getByRole("button", { name: "Previous" }));
    expect(await screen.findByText("Adele Vance")).toBeInTheDocument();
    expect(loadPage).toHaveBeenNthCalledWith(3, null);
  });

  it("renders empty and access-gated states", async () => {
    const emptyLoad = vi.fn().mockResolvedValue({ result: { status: "ready", count: 0 }, items: [], next_cursor: "" });
    const { unmount } = render(
      <PaginatedEvidenceTable
        title="Service issues"
        columns={[{ key: "title", label: "Issue" }]}
        loadPage={emptyLoad}
        onClose={vi.fn()}
      />
    );
    expect(await screen.findByText("No service issues records")).toBeInTheDocument();
    unmount();

    render(
      <PaginatedEvidenceTable
        title="Secure Score"
        columns={[{ key: "current_score", label: "Score" }]}
        loadPage={vi.fn().mockResolvedValue({ result: { status: "blocked", message: "blocked" }, items: [] })}
        onClose={vi.fn()}
      />
    );
    await waitFor(() => expect(screen.getByText("Evidence access is not available")).toBeInTheDocument());
    expect(screen.queryByText("No secure score records")).not.toBeInTheDocument();
  });
});
