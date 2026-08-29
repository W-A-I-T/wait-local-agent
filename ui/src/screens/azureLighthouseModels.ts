export type LighthouseStatus = {
  status: string;
  message: string;
  read_only: boolean;
  customer_onboarding_deployed_by_wait: boolean;
  supported_scopes: string[];
  supported_operations: string[];
};

export type LighthouseSubscription = {
  subscription_id: string;
  display_name: string;
  customer_tenant_id: string;
  state: string;
  managed_by_tenant_ids: string[];
  verification_status: "verified" | "projected" | "unavailable";
  delegation_count: number;
  verification_message: string;
};

export type LighthouseDiscovery = {
  status: string;
  client_id: string;
  managing_tenant_id: string;
  expected_customer_tenant_id: string;
  subscriptions: LighthouseSubscription[];
  source_errors: Array<{ source: string; code: string; message: string }>;
};

export type LighthouseDelegation = {
  assignment_id: string;
  assignment_name: string;
  definition_id: string;
  definition_name: string;
  managed_by_tenant_id: string;
  provisioning_state: string;
  scope: string;
  authorizations: Array<{
    principal_id: string;
    principal_display_name: string;
    role_definition_id: string;
  }>;
};

export type LighthouseResource = {
  resource_id: string;
  name: string;
  resource_type: string;
  location: string;
  resource_group: string;
  kind: string;
  sku_name: string;
  tags: Record<string, string>;
};

export type LighthouseInventory = {
  status: string;
  client_id: string;
  managing_tenant_id: string;
  customer_tenant_id: string;
  subscription_id: string;
  resource_group: string;
  scope: string;
  delegation_verified: boolean;
  delegations: LighthouseDelegation[];
  resources: LighthouseResource[];
  resource_type_counts: Record<string, number>;
  source_errors: Array<{ source: string; code: string; message: string }>;
};

export type OnboardingBundle = {
  client_id: string;
  format: string;
  deployment_scope: "subscription" | "resource_group";
  role_profile: string;
  template: Record<string, unknown>;
  parameters: Record<string, unknown>;
  template_sha256: string;
  parameters_sha256: string;
  bundle_sha256: string;
  deployment_guidance: string[];
};

export const emptyConnection = {
  credentialRef: "",
  managingTenantId: "",
  customerTenantId: "",
  resourceGroup: ""
};

export function showError(
  error: unknown,
  setMessage: (message: string) => void,
  setDanger: (danger: boolean) => void
) {
  setDanger(true);
  setMessage(error instanceof Error ? error.message : "Azure Lighthouse operation failed.");
}
