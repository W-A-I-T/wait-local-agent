import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useMicrosoftAdminAccess } from "../hooks/useMicrosoftAdminAccess";
import { MicrosoftAdminCapabilityGate } from "./MicrosoftAdminCapabilityGate";

vi.mock("../hooks/useMicrosoftAdminAccess", () => ({
  useMicrosoftAdminAccess: vi.fn()
}));

const mockedAccess = vi.mocked(useMicrosoftAdminAccess);

function renderGate() {
  return render(
    <MemoryRouter>
      <MicrosoftAdminCapabilityGate><div>protected content</div></MicrosoftAdminCapabilityGate>
    </MemoryRouter>
  );
}

describe("MicrosoftAdminCapabilityGate", () => {
  beforeEach(() => {
    mockedAccess.mockReset();
  });

  it("fails closed while the capability is unresolved", () => {
    mockedAccess.mockReturnValue({ allowed: false, resolved: false, grants: [], error: "", refresh: vi.fn() });
    renderGate();

    expect(screen.getByText("Checking Microsoft Admin access…")).toBeInTheDocument();
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("renders a direct-route denial when the selected client is not granted", () => {
    mockedAccess.mockReturnValue({ allowed: false, resolved: true, grants: [], error: "", refresh: vi.fn() });
    renderGate();

    expect(screen.getByRole("alert")).toHaveTextContent("Microsoft Admin access denied");
    expect(screen.queryByText("protected content")).not.toBeInTheDocument();
  });

  it("renders protected content only after a capability grant resolves", () => {
    mockedAccess.mockReturnValue({ allowed: true, resolved: true, grants: [], error: "", refresh: vi.fn() });
    renderGate();

    expect(screen.getByText("protected content")).toBeInTheDocument();
  });
});
