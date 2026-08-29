"""Shared Azure Lighthouse test fixtures."""

from __future__ import annotations

from pathlib import Path

MANAGING_TENANT_ID = "11111111-1111-1111-1111-111111111111"
CUSTOMER_TENANT_ID = "22222222-2222-2222-2222-222222222222"
SUBSCRIPTION_ID = "33333333-3333-3333-3333-333333333333"
DEFINITION_ID = "44444444-4444-4444-4444-444444444444"
ASSIGNMENT_ID = "55555555-5555-5555-5555-555555555555"
PRINCIPAL_ID = "66666666-6666-6666-6666-666666666666"
OTHER_TENANT_ID = "77777777-7777-7777-7777-777777777777"


class FakeToken:
    def __init__(self, token: str = "access-token") -> None:
        self.token = token


class FakeCredential:
    def __init__(self, token: str = "access-token", *, error: Exception | None = None) -> None:
        self.token = token
        self.error = error
        self.scopes: list[tuple[str, ...]] = []

    def get_token(self, *scopes: str, **kwargs: object) -> FakeToken:
        self.scopes.append(scopes)
        if self.error is not None:
            raise self.error
        return FakeToken(self.token)


def configured_settings(settings, tmp_path: Path | None = None):
    values = {
        **settings.__dict__,
        "allow_http_probing": True,
        "demo_mode": False,
        "admin_token": "admin-token",
        "tech_token": "tech-token",
        "viewer_token": "viewer-token",
        "api_token": "",
    }
    if tmp_path is not None:
        values["data_path"] = tmp_path / "state.db"
        values["vault_path"] = tmp_path / "vault"
    return settings.__class__(**values)


def subscription_payload(
    *,
    customer_tenant_id: str = CUSTOMER_TENANT_ID,
    managing_tenant_id: str = MANAGING_TENANT_ID,
    subscription_id: str = SUBSCRIPTION_ID,
    display_name: str = "Contoso Production",
) -> dict[str, object]:
    return {
        "subscriptionId": subscription_id,
        "displayName": display_name,
        "tenantId": customer_tenant_id,
        "state": "Enabled",
        "managedByTenants": [{"tenantId": managing_tenant_id}],
    }


def assignment_payload(
    *,
    subscription_id: str = SUBSCRIPTION_ID,
    managing_tenant_id: str = MANAGING_TENANT_ID,
    resource_group: str = "",
    provisioning_state: str = "Succeeded",
    include_definition: bool = True,
    definition_at_subscription: bool = False,
) -> dict[str, object]:
    subscription_scope = f"/subscriptions/{subscription_id}"
    scope = subscription_scope
    if resource_group:
        scope += f"/resourceGroups/{resource_group}"
    definition_scope = subscription_scope if definition_at_subscription else scope
    definition_id = (
        f"{definition_scope}/providers/Microsoft.ManagedServices/registrationDefinitions/{DEFINITION_ID}"
    )
    properties: dict[str, object] = {
        "registrationDefinitionId": definition_id,
        "provisioningState": provisioning_state,
    }
    if include_definition:
        properties["registrationDefinition"] = {
            "id": definition_id,
            "properties": {
                "registrationDefinitionName": "WAIT Reader Delegation",
                "managedByTenantId": managing_tenant_id,
                "authorizations": [
                    {
                        "principalId": PRINCIPAL_ID,
                        "principalIdDisplayName": "WAIT Local Agent",
                        "roleDefinitionId": "acdd72a7-3385-48ef-bd42-f606fba81ae7",
                    }
                ],
            },
        }
    return {
        "id": (
            f"{scope}/providers/Microsoft.ManagedServices/registrationAssignments/{ASSIGNMENT_ID}"
        ),
        "name": ASSIGNMENT_ID,
        "properties": properties,
    }


def resource_payload() -> dict[str, object]:
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/app-rg/providers/"
            "Microsoft.Compute/virtualMachines/app-vm"
        ),
        "name": "app-vm",
        "type": "Microsoft.Compute/virtualMachines",
        "location": "canadacentral",
        "kind": "",
        "sku": {"name": "Standard_D2s_v5"},
        "tags": {"owner": "operations", "costCenter": 42, "ignored": ["value"]},
    }
