import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../api/client";
import { ExtensionsPacks } from "../ExtensionsPacks";

vi.mock("../../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../../app/DashboardContext", () => ({ useDashboard: () => ({ isAdmin: true, role: "admin", roleResolved: true }) }));

const mockedApiFetch = vi.mocked(apiFetch);

function configure() {
  mockedApiFetch.mockImplementation((path, init) => {
    if (!path) return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    if (path === "/packs/install" && init?.method === "POST") return Promise.resolve({ pack_name: "Example Pack" }) as ReturnType<typeof apiFetch>;
    if (path === "/packs") return Promise.resolve([{ name: "Example Pack", version: "1.0.0", locked: false, requires_license: false }]) as ReturnType<typeof apiFetch>;
    if (path === "/packs/status") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
    throw new Error(`Unexpected request: ${path}`);
  });
}

describe("Extensions/Packs install", () => {
  beforeEach(() => mockedApiFetch.mockReset());

  it("POSTs the pack install request and refreshes the inventory", async () => {
    configure();
    render(<ExtensionsPacks />);
    await screen.findByText("Example Pack");
    fireEvent.change(screen.getByLabelText("Tarball path"), { target: { value: "/tmp/example.tar.gz" } });
    fireEvent.change(screen.getByLabelText("License key"), { target: { value: "license-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Install pack" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Pack installed: Example Pack.");
    expect(mockedApiFetch).toHaveBeenCalledWith("/packs/install", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tarball_path: "/tmp/example.tar.gz", license_key: "license-1" })
    });
    expect(mockedApiFetch.mock.calls.filter(([path]) => path === "/packs")).toHaveLength(2);
  });

  it("renders install errors inline", async () => {
    configure();
    mockedApiFetch.mockImplementation((path, init) => {
      if (!path) return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/packs/install" && init?.method === "POST") return Promise.reject(new Error("Pack signature invalid.")) as ReturnType<typeof apiFetch>;
      if (path === "/packs") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      if (path === "/packs/status") return Promise.resolve([]) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });
    render(<ExtensionsPacks />);
    await screen.findByText("No packs are installed on this appliance.");
    fireEvent.change(screen.getByLabelText("Tarball path"), { target: { value: "/tmp/bad.tar.gz" } });
    fireEvent.click(screen.getByRole("button", { name: "Install pack" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Pack signature invalid."));
  });
});
