import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../api/client";
import { AzureLighthouse } from "./AzureLighthouse";

vi.mock("../api/client", () => ({ apiFetch: vi.fn() }));

const dashboard = {
  role: "admin",
  roleResolved: true,
  clients: [{ client_id: "client-contoso", name: "Contoso", status: "active" }],
  selectedClientId: "client-contoso",
  setSelectedClientId: vi.fn()
};
vi.mock("../app/DashboardContext", () => ({ useDashboard: () => dashboard }));

const mockedApiFetch = vi.mocked(apiFetch);
const managingTenant = "11111111-1111-1111-1111-111111111111";
const customerTenant = "22222222-2222-2222-2222-222222222222";
const subscriptionId = "33333333-3333-3333-3333-333333333333";
const principalId = "66666666-6666-6666-6666-666666666666";

const statusResponse = {
  status: "ready",
  message: "Azure Lighthouse read-only discovery is enabled.",
  read_only: true,
  customer_onboarding_deployed_by_wait: false,
  supported_scopes: ["subscription", "resource_group"],
  supported_operations: ["discover delegated subscriptions"]
};

const discoveryResponse = {
  status: "ready",
  client_id: "client-contoso",
  managing_tenant_id: managingTenant,
  expected_customer_tenant_id: customerTenant,
  subscriptions: [
    {
      subscription_id: subscriptionId,
      display_name: "Contoso Production",
      customer_tenant_id: customerTenant,
      state: "Enabled",
      managed_by_tenant_ids: [managingTenant],
      verification_status: "verified" as const,
      delegation_count: 1,
      verification_message: "Subscription-level Azure Lighthouse registration assignment is verified."
    }
  ],
  source_errors: []
};

const inventoryResponse = {
  status: "ready",
  client_id: "client-contoso",
  managing_tenant_id: managingTenant,
  customer_tenant_id: customerTenant,
  subscription_id: subscriptionId,
  resource_group: "",
  scope: `/subscriptions/${subscriptionId}`,
  delegation_verified: true,
  delegations: [
    {
      assignment_id: "assignment-id",
      assignment_name: "assignment",
      definition_id: "definition-id",
      definition_name: "WAIT Reader",
      managed_by_tenant_id: managingTenant,
      provisioning_state: "Succeeded",
      scope: `/subscriptions/${subscriptionId}`,
      authorizations: []
    }
  ],
  resources: [
    {
      resource_id: "resource-1",
      name: "app-vm",
      resource_type: "Microsoft.Compute/virtualMachines",
      location: "canadacentral",
      resource_group: "app-rg",
      kind: "",
      sku_name: "Standard_D2s_v5",
      tags: {}
    }
  ],
  resource_type_counts: { "Microsoft.Compute/virtualMachines": 1 },
  source_errors: []
};

const onboardingResponse = {
  client_id: "client-contoso",
  format: "wait.azure-lighthouse.onboarding/v1",
  deployment_scope: "subscription" as const,
  role_profile: "inventory-reader",
  template: { resources: [] },
  parameters: { parameters: {} },
  template_sha256: "sha256:template",
  parameters_sha256: "sha256:parameters",
  bundle_sha256: "sha256:bundle",
  deployment_guidance: ["Customer reviews the artifacts."]
};

function renderScreen() {
  return render(
    <MemoryRouter>
      <AzureLighthouse />
    </MemoryRouter>
  );
}

function fillConnection() {
  fireEvent.change(screen.getByLabelText("Vault credential reference"), {
    target: { value: "cloud/lighthouse" }
  });
  fireEvent.change(screen.getByLabelText("Managing tenant ID"), {
    target: { value: managingTenant }
  });
  fireEvent.change(screen.getByLabelText("Expected customer tenant ID"), {
    target: { value: customerTenant }
  });
}

describe("AzureLighthouse", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    dashboard.role = "admin";
    dashboard.roleResolved = true;
    dashboard.selectedClientId = "client-contoso";
    dashboard.setSelectedClientId.mockReset();
    mockedApiFetch.mockImplementation(async (path) => {
      if (path === "/packs/microsoft-admin/azure-lighthouse/status") {
        return statusResponse;
      }
      if (path === "/packs/microsoft-admin/azure-lighthouse/discover") {
        return discoveryResponse;
      }
      if (path === "/packs/microsoft-admin/azure-lighthouse/inventory") {
        return inventoryResponse;
      }
      if (path === "/packs/microsoft-admin/azure-lighthouse/onboarding/plan") {
        return onboardingResponse;
      }
      throw new Error(`Unexpected path: ${path}`);
    });
  });

  it("discovers, verifies, inventories, and generates a customer-owned onboarding package", async () => {
    renderScreen();
    expect(await screen.findByText("Azure Lighthouse read-only discovery is enabled.")).toBeInTheDocument();
    fillConnection();

    fireEvent.click(screen.getByRole("button", { name: "Discover delegated subscriptions" }));
    expect(await screen.findByText("Contoso Production")).toBeInTheDocument();
    expect(screen.getByText(/Subscription-level Azure Lighthouse/)).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/microsoft-admin/azure-lighthouse/discover",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          client_id: "client-contoso",
          credential_ref: "cloud/lighthouse",
          managing_tenant_id: managingTenant,
          expected_customer_tenant_id: customerTenant
        })
      })
    );

    fireEvent.click(screen.getByRole("button", { name: "Verify scope and collect inventory" }));
    expect(await screen.findByText("Verified delegated inventory")).toBeInTheDocument();
    expect(screen.getByText("app-vm")).toBeInTheDocument();
    expect(screen.getByText("Standard_D2s_v5")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Managing-tenant principal object ID"), {
      target: { value: principalId }
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate onboarding package" }));
    expect(await screen.findByText("sha256:bundle")).toBeInTheDocument();
    expect(screen.getByText("Customer reviews the artifacts.")).toBeInTheDocument();
    expect(screen.getByText("ARM template")).toBeInTheDocument();
    expect(mockedApiFetch).toHaveBeenCalledWith(
      "/packs/microsoft-admin/azure-lighthouse/onboarding/plan",
      expect.objectContaining({ method: "POST" })
    );
  });

  it("requires administrator access and does not load Azure data for technicians", () => {
    dashboard.role = "technician";
    renderScreen();

    expect(screen.getByText("Administrator access required")).toBeInTheDocument();
    expect(screen.getByText(/Cross-tenant Azure delegation/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Vault credential reference")).toBeNull();
    expect(mockedApiFetch).not.toHaveBeenCalled();
  });

  it("keeps live actions disabled until explicit client and mapping fields are complete", async () => {
    dashboard.selectedClientId = "";
    renderScreen();
    await waitFor(() =>
      expect(mockedApiFetch).toHaveBeenCalledWith("/packs/microsoft-admin/azure-lighthouse/status")
    );

    expect(screen.getByRole("button", { name: "Discover delegated subscriptions" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Verify scope and collect inventory" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Generate onboarding package" })).toBeDisabled();

    fireEvent.change(screen.getByLabelText("WAIT client"), {
      target: { value: "client-contoso" }
    });
    expect(dashboard.setSelectedClientId).toHaveBeenCalledWith("client-contoso");
  });

  it("renders provider errors without exposing a false success state", async () => {
    mockedApiFetch.mockImplementation(async (path) => {
      if (path === "/packs/microsoft-admin/azure-lighthouse/status") {
        return statusResponse;
      }
      throw new Error("Azure Resource Manager rejected access to the requested delegated scope.");
    });
    renderScreen();
    await screen.findByText("Azure Lighthouse read-only discovery is enabled.");
    fillConnection();
    fireEvent.click(screen.getByRole("button", { name: "Discover delegated subscriptions" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("rejected access");
    expect(screen.queryByText("Verified delegated inventory")).toBeNull();
  });

  it("shows partial discovery states for projected resource-group candidates", async () => {
    mockedApiFetch.mockImplementation(async (path) => {
      if (path === "/packs/microsoft-admin/azure-lighthouse/status") {
        return statusResponse;
      }
      if (path === "/packs/microsoft-admin/azure-lighthouse/discover") {
        return {
          ...discoveryResponse,
          status: "partial",
          subscriptions: [
            {
              ...discoveryResponse.subscriptions[0],
              verification_status: "projected",
              verification_message: "Verify the exact resource-group assignment."
            }
          ],
          source_errors: [
            {
              source: `subscription:${subscriptionId}`,
              code: "delegation_verification_unavailable",
              message: "Assignment verification was unavailable."
            }
          ]
        };
      }
      return inventoryResponse;
    });
    renderScreen();
    await screen.findByText("Azure Lighthouse read-only discovery is enabled.");
    fillConnection();
    fireEvent.change(screen.getByLabelText("Resource group for resource-group delegation (optional)"), {
      target: { value: "app-rg" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Discover delegated subscriptions" }));

    expect(await screen.findByText("Verify the exact resource-group assignment.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Assignment verification was unavailable.");
    expect(screen.getByRole("button", { name: "Selected" })).toHaveAttribute("aria-pressed", "true");
  });

  it("surfaces status-loading failures as an alert", async () => {
    mockedApiFetch.mockRejectedValue(new Error("Azure Lighthouse pack unavailable"));
    renderScreen();
    expect(await screen.findByRole("alert")).toHaveTextContent("pack unavailable");
  });
});
