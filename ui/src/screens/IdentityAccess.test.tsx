import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { IdentityAccess } from "./IdentityAccess";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../app/DashboardContext", () => ({
  useDashboard: () => ({
    clients: [
      { client_id: "alpha", name: "Alpha", status: "active" },
      { client_id: "beta", name: "Beta", status: "active" }
    ]
  })
}));

const mockedApiFetch = vi.mocked(apiFetch);

const principal = {
  principal_id: "tech-alpha",
  kind: "staff" as const,
  display_name: "Alpha technician",
  active: true,
  client_roles: [["alpha", "technician"]] as Array<[string, "technician"]>,
  global_roles: [],
  credentials: [{ fingerprint: "sha256:abcdef123456", active: true, created_at: "2026-08-31T00:00:00Z" }]
};

describe("IdentityAccess", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
  });

  it("lists principals and shows a rotated credential only from the mutation response", async () => {
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/packs/operator-control/principals" && !init) return Promise.resolve([principal]) as ReturnType<typeof apiFetch>;
      if (path === "/packs/operator-control/principals/tech-alpha/credentials/rotate" && init?.method === "POST") {
        return Promise.resolve({
          principal: { ...principal, credentials: [{ fingerprint: "sha256:fedcba654321", active: true, created_at: "now" }] },
          credential: "wait_once_only",
          credential_notice: "This credential is returned once."
        }) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<IdentityAccess />);

    expect(await screen.findByText("Alpha technician")).toBeInTheDocument();
    expect(screen.getByText("sha256:abcdef123456")).toBeInTheDocument();
    expect(screen.queryByText("wait_once_only")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Rotate credential" }));

    expect(await screen.findByText("wait_once_only")).toBeInTheDocument();
    expect(screen.getByText("sha256:fedcba654321")).toBeInTheDocument();
  });

  it("creates a scoped staff principal through the operator-control API", async () => {
    let listCalls = 0;
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/packs/operator-control/principals" && !init) {
        listCalls += 1;
        return Promise.resolve(listCalls === 1 ? [] : [principal]) as ReturnType<typeof apiFetch>;
      }
      if (path === "/packs/operator-control/principals" && init?.method === "POST") {
        return Promise.resolve({
          principal,
          credential: "wait_new_token",
          credential_notice: "This credential is returned once."
        }) as ReturnType<typeof apiFetch>;
      }
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<IdentityAccess />);
    await screen.findByText("No database principals");
    fireEvent.change(screen.getByLabelText("Principal ID"), { target: { value: "tech-alpha" } });
    fireEvent.change(screen.getByLabelText("Display name"), { target: { value: "Alpha technician" } });
    fireEvent.click(screen.getByRole("button", { name: "Create & issue credential" }));

    await waitFor(() => expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/operator-control/principals",
      expect.objectContaining({ method: "POST" })
    ));
    const createCall = mockedApiFetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(createCall?.[1]?.body))).toMatchObject({
      principal_id: "tech-alpha",
      kind: "staff",
      client_roles: [{ client_id: "alpha", role: "technician" }],
      issue_credential: true
    });
    expect(await screen.findByText("wait_new_token")).toBeInTheDocument();
  });

  it("shows a recoverable error for invalid principal data", async () => {
    mockedApiFetch.mockResolvedValue({});

    render(<IdentityAccess />);

    expect(await screen.findByRole("status")).toHaveTextContent("invalid principal data");
    expect(screen.getByText("No database principals")).toBeInTheDocument();
  });

  it("reactivates an inactive principal and refreshes its controls", async () => {
    const inactive = { ...principal, active: false, credentials: [] };
    const reactivated = { ...inactive, active: true };
    mockedApiFetch.mockImplementation((path, init) => {
      if (path === "/packs/operator-control/principals" && !init) return Promise.resolve([inactive]) as ReturnType<typeof apiFetch>;
      if (path === "/packs/operator-control/principals/tech-alpha" && init?.method === "PATCH") return Promise.resolve(reactivated) as ReturnType<typeof apiFetch>;
      throw new Error(`Unexpected request: ${path}`);
    });

    render(<IdentityAccess />);

    expect(await screen.findByText("Alpha technician")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reactivate" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Principal reactivated");
    expect(screen.getByRole("button", { name: "Deactivate" })).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/operator-control/principals/tech-alpha",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ active: true }) })
    );
  });
});
