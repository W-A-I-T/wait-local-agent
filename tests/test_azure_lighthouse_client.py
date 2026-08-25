from __future__ import annotations

from typing import cast

import httpx
import pytest

from packs.azure_lighthouse.client import AzureLighthouseClient
from packs.azure_lighthouse.models import (
    ARM_SCOPE,
    MAX_PAGES,
    AzureLighthouseAuthorizationError,
    AzureLighthouseBlockedError,
    AzureLighthouseProviderError,
    AzureLighthouseValidationError,
)
from packs.azure_lighthouse.normalizers import (
    aggregate_status,
    definition_scope,
    normalized_optional_uuid,
    resource_group_from_id,
    scope_from_assignment_id,
    validate_definition_id,
)
from packs.azure_lighthouse.transport import initial_url, validated_next_link
from tests.azure_lighthouse_support import (
    ASSIGNMENT_ID,
    CUSTOMER_TENANT_ID,
    DEFINITION_ID,
    MANAGING_TENANT_ID,
    OTHER_TENANT_ID,
    PRINCIPAL_ID,
    SUBSCRIPTION_ID,
    FakeCredential,
    assignment_payload,
    configured_settings,
    resource_payload,
    subscription_payload,
)


def test_discovery_verifies_subscription_level_lighthouse_assignment(settings) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer access-token"
        if request.url.path == "/subscriptions":
            return httpx.Response(
                200,
                json={
                    "value": [
                        subscription_payload(),
                        subscription_payload(customer_tenant_id=OTHER_TENANT_ID, subscription_id=OTHER_TENANT_ID),
                    ]
                },
            )
        if request.url.path.endswith("/registrationAssignments"):
            assert request.url.params["$expandRegistrationDefinition"] == "true"
            return httpx.Response(200, json={"value": [assignment_payload()]})
        raise AssertionError(request.url)

    credential = FakeCredential()
    client = AzureLighthouseClient(
        configured_settings(settings),
        credential,
        transport=httpx.MockTransport(handler),
    )
    result = client.discover(
        client_id="client-contoso",
        managing_tenant_id=MANAGING_TENANT_ID,
        expected_customer_tenant_id=CUSTOMER_TENANT_ID,
    )

    assert result.status == "ready"
    assert len(result.subscriptions) == 1
    subscription = result.subscriptions[0]
    assert subscription.subscription_id == SUBSCRIPTION_ID
    assert subscription.verification_status == "verified"
    assert subscription.delegation_count == 1
    assert subscription.managed_by_tenant_ids == (MANAGING_TENANT_ID,)
    assert credential.scopes == [(ARM_SCOPE,), (ARM_SCOPE,)]
    assert len(requests) == 2


def test_discovery_preserves_projected_and_unavailable_verification_states(settings) -> None:
    calls = 0

    def projected_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/subscriptions":
            return httpx.Response(200, json={"value": [subscription_payload()]})
        return httpx.Response(200, json={"value": []})

    projected = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(projected_handler),
    ).discover(
        client_id="client-contoso",
        managing_tenant_id=MANAGING_TENANT_ID,
        expected_customer_tenant_id=CUSTOMER_TENANT_ID,
    )
    assert projected.subscriptions[0].verification_status == "projected"
    assert projected.source_errors == ()

    def unavailable_handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.path == "/subscriptions":
            return httpx.Response(200, json={"value": [subscription_payload()]})
        return httpx.Response(403, json={"error": {"message": "secret body"}})

    unavailable = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(unavailable_handler),
    ).discover(
        client_id="client-contoso",
        managing_tenant_id=MANAGING_TENANT_ID,
        expected_customer_tenant_id=CUSTOMER_TENANT_ID,
    )
    assert unavailable.status == "partial"
    assert unavailable.subscriptions[0].verification_status == "unavailable"
    assert unavailable.source_errors[0]["code"] == "delegation_verification_unavailable"
    assert "secret body" not in unavailable.source_errors[0]["message"]
    assert calls == 2


def test_discovery_ignores_unmapped_tenants_and_records_invalid_subscription_ids(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    subscription_payload(subscription_id="not-a-guid"),
                    subscription_payload(managing_tenant_id=OTHER_TENANT_ID),
                    {"subscriptionId": "", "tenantId": CUSTOMER_TENANT_ID},
                ]
            },
        )

    result = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).discover(
        client_id="client-contoso",
        managing_tenant_id=MANAGING_TENANT_ID,
        expected_customer_tenant_id=CUSTOMER_TENANT_ID,
    )
    assert result.status == "failed"
    assert result.subscriptions == ()
    assert result.source_errors[0]["code"] == "invalid_subscription_id"


def test_inventory_verifies_resource_group_scope_and_normalizes_resources(settings) -> None:
    resource_group = "app-rg"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/subscriptions":
            return httpx.Response(200, json={"value": [subscription_payload()]})
        if request.url.path.endswith("/registrationAssignments"):
            assert f"/resourceGroups/{resource_group}/" in request.url.path
            return httpx.Response(
                200,
                json={"value": [assignment_payload(resource_group=resource_group)]},
            )
        if request.url.path.endswith(f"/resourceGroups/{resource_group}/resources"):
            return httpx.Response(200, json={"value": [resource_payload(), {"name": "incomplete"}]})
        raise AssertionError(request.url)

    result = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).inventory(
        client_id="client-contoso",
        managing_tenant_id=MANAGING_TENANT_ID,
        expected_customer_tenant_id=CUSTOMER_TENANT_ID,
        subscription_id=SUBSCRIPTION_ID,
        resource_group=resource_group,
        limit=10,
    )

    assert result.status == "partial"
    assert result.delegation_verified is True
    assert result.source_errors[0]["code"] == "invalid_resource_records"
    assert result.scope.endswith(f"/resourceGroups/{resource_group}")
    assert result.delegations[0].assignment_name == ASSIGNMENT_ID
    assert result.delegations[0].authorizations[0]["principal_id"] == PRINCIPAL_ID
    assert len(result.resources) == 1
    resource = result.resources[0]
    assert resource.resource_group == resource_group
    assert resource.sku_name == "Standard_D2s_v5"
    assert resource.tags == {"owner": "operations", "costCenter": "42"}
    assert result.resource_type_counts == {"Microsoft.Compute/virtualMachines": 1}


def test_resource_group_assignment_accepts_subscription_scoped_definition(settings) -> None:
    resource_group = "app-rg"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    assignment_payload(
                        resource_group=resource_group,
                        definition_at_subscription=True,
                    )
                ]
            },
        )

    delegations = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).list_delegations(
        subscription_id=SUBSCRIPTION_ID,
        managing_tenant_id=MANAGING_TENANT_ID,
        resource_group=resource_group,
    )

    assert len(delegations) == 1
    assert delegations[0].scope.endswith(f"/resourceGroups/{resource_group}")
    assert delegations[0].definition_id.startswith(f"/subscriptions/{SUBSCRIPTION_ID}/providers/")


def test_delegation_falls_back_to_exact_registration_definition_read(settings) -> None:
    definition_path = (
        f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.ManagedServices/"
        f"registrationDefinitions/{DEFINITION_ID}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/registrationAssignments"):
            return httpx.Response(
                200,
                json={"value": [assignment_payload(include_definition=False)]},
            )
        if request.url.path == definition_path:
            return httpx.Response(
                200,
                json={
                    "id": definition_path,
                    "properties": {
                        "registrationDefinitionName": "Fallback Definition",
                        "managedByTenantId": MANAGING_TENANT_ID,
                        "authorizations": [],
                    },
                },
            )
        raise AssertionError(request.url)

    delegations = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).list_delegations(
        subscription_id=SUBSCRIPTION_ID,
        managing_tenant_id=MANAGING_TENANT_ID,
    )
    assert len(delegations) == 1
    assert delegations[0].definition_name == "Fallback Definition"


def test_delegation_skips_non_terminal_and_wrong_managing_tenant(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "value": [
                    assignment_payload(provisioning_state="Pending"),
                    assignment_payload(managing_tenant_id=OTHER_TENANT_ID),
                ]
            },
        )

    delegations = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).list_delegations(
        subscription_id=SUBSCRIPTION_ID,
        managing_tenant_id=MANAGING_TENANT_ID,
    )
    assert delegations == ()


def test_delegation_rejects_assignments_or_definitions_from_a_different_scope(settings) -> None:
    other_subscription = OTHER_TENANT_ID
    wrong_assignment = assignment_payload()
    wrong_assignment["id"] = (
        f"/subscriptions/{other_subscription}/providers/Microsoft.ManagedServices/"
        f"registrationAssignments/{ASSIGNMENT_ID}"
    )
    wrong_definition = assignment_payload()
    properties = cast(dict[str, object], wrong_definition["properties"])
    properties["registrationDefinitionId"] = (
        f"/subscriptions/{other_subscription}/providers/Microsoft.ManagedServices/"
        f"registrationDefinitions/{DEFINITION_ID}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"value": [wrong_assignment, wrong_definition]})

    delegations = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).list_delegations(
        subscription_id=SUBSCRIPTION_ID,
        managing_tenant_id=MANAGING_TENANT_ID,
    )
    assert delegations == ()
