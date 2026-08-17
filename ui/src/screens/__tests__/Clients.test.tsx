import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api/client";
import type { ClientDirectoryEntry } from "../../api/types";
import { Clients } from "../Clients";

vi.mock("../../api/client", () => ({
  apiFetch: vi.fn()
}));

const mockedApiFetch = vi.mocked(apiFetch);

type Deferred<T> = {
  promise: Promise<T>;
  resolve: (value: T) => void;
};

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("Clients", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("renders active and archived clients while excluding quarantine", async () => {
    mockedApiFetch.mockImplementation(() => Promise.resolve([
      { client_id: "acme", name: "Acme", status: "active" },
      { client_id: "legacy", name: "Legacy Co", status: "archived" },
      { client_id: "__quarantine__", name: "Quarantine", status: "quarantine" }
    ]) as ReturnType<typeof apiFetch>);

    render(<Clients />);

    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByText("acme")).toBeInTheDocument();
    expect(screen.getByText("Legacy Co")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.queryByText("__quarantine__")).not.toBeInTheDocument();
  });

  it("shows loading and empty states", async () => {
    const pending = deferred<ClientDirectoryEntry[]>();
    mockedApiFetch.mockImplementation(() => pending.promise as ReturnType<typeof apiFetch>);

    render(<Clients />);

    expect(screen.getByText("Loading Clients…")).toBeInTheDocument();
    expect(screen.getByText("Loading Clients…").parentElement).toHaveAttribute("aria-busy", "true");

    await act(async () => {
      pending.resolve([]);
    });

    expect(await screen.findByText("No clients are visible.")).toBeInTheDocument();
  });

  it("shows a retryable error", async () => {
    mockedApiFetch.mockImplementation(() => Promise.reject(new Error("Clients unavailable.")) as ReturnType<typeof apiFetch>);

    render(<Clients />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Clients unavailable."));
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
