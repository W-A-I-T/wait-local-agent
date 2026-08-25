from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from packs.azure_lighthouse.models import (
    MANAGED_SERVICES_API_VERSION,
    READER_ROLE_DEFINITION_ID,
    AzureLighthouseValidationError,
)
from packs.azure_lighthouse.onboarding import (
    ONBOARDING_FORMAT,
    build_onboarding_bundle,
    validate_onboarding_bundle,
)
from packs.azure_lighthouse.validation import (
    normalize_description,
    normalize_name,
    normalize_resource_group,
    normalize_uuid,
    scope_path,
)
from tests.azure_lighthouse_support import MANAGING_TENANT_ID, PRINCIPAL_ID


def test_subscription_onboarding_bundle_is_reader_only_deterministic_and_reviewable() -> None:
    first = build_onboarding_bundle(
        offer_name="WAIT delegated inventory",
        offer_description="Read-only customer Azure inventory.",
        managing_tenant_id=MANAGING_TENANT_ID,
        principal_id=PRINCIPAL_ID,
        principal_display_name="WAIT Local Agent",
        deployment_scope="subscription",
    )
    second = build_onboarding_bundle(
        offer_name="WAIT delegated inventory",
        offer_description="Read-only customer Azure inventory.",
        managing_tenant_id=MANAGING_TENANT_ID,
        principal_id=PRINCIPAL_ID,
        principal_display_name="WAIT Local Agent",
        deployment_scope="subscription",
    )

    assert first == second
    assert first.format == ONBOARDING_FORMAT
    assert first.role_profile == "inventory-reader"
    assert first.template["$schema"].endswith("subscriptionDeploymentTemplate.json#")
    assert first.parameters["$schema"].endswith("subscriptionDeploymentParameters.json#")
    resources = first.template["resources"]
    assert isinstance(resources, list)
    resource_rows = [cast(dict[str, object], resource) for resource in resources]
    assert [resource["apiVersion"] for resource in resource_rows] == [
        MANAGED_SERVICES_API_VERSION,
        MANAGED_SERVICES_API_VERSION,
    ]
    parameter_rows = cast(dict[str, object], first.parameters["parameters"])
    authorization_parameter = cast(dict[str, object], parameter_rows["authorizations"])
    authorization_values = cast(list[dict[str, str]], authorization_parameter["value"])
    authorization = authorization_values[0]
    assert authorization == {
        "principalId": PRINCIPAL_ID,
        "principalIdDisplayName": "WAIT Local Agent",
        "roleDefinitionId": READER_ROLE_DEFINITION_ID,
    }
    serialized = str(first.to_dict()).casefold()
    assert "client_secret" not in serialized
    assert "owner" not in serialized
    assert "contributor" not in serialized
    assert first.template_sha256.startswith("sha256:")
    assert first.parameters_sha256.startswith("sha256:")
    assert first.bundle_sha256.startswith("sha256:")
    validate_onboarding_bundle(first)


def test_resource_group_onboarding_bundle_uses_resource_group_schema_and_guidance() -> None:
    bundle = build_onboarding_bundle(
        offer_name="WAIT RG delegation",
        offer_description="Reader access to one customer resource group.",
        managing_tenant_id=MANAGING_TENANT_ID,
        principal_id=PRINCIPAL_ID,
        principal_display_name="WAIT Operations Group",
        deployment_scope="resource_group",
    )
    assert bundle.template["$schema"].endswith("deploymentTemplate.json#")
    assert bundle.parameters["$schema"].endswith("deploymentParameters.json#")
    assert "resource group" in " ".join(bundle.deployment_guidance).casefold()
    validate_onboarding_bundle(bundle)


def test_onboarding_bundle_tampering_is_rejected() -> None:
    bundle = build_onboarding_bundle(
        offer_name="WAIT delegation",
        offer_description="Reader inventory.",
        managing_tenant_id=MANAGING_TENANT_ID,
        principal_id=PRINCIPAL_ID,
        principal_display_name="WAIT",
    )
    with pytest.raises(AzureLighthouseValidationError, match="format"):
        validate_onboarding_bundle(replace(bundle, format="other"))
    with pytest.raises(AzureLighthouseValidationError, match="template digest"):
        validate_onboarding_bundle(replace(bundle, template_sha256="sha256:bad"))
    with pytest.raises(AzureLighthouseValidationError, match="parameters digest"):
        validate_onboarding_bundle(replace(bundle, parameters_sha256="sha256:bad"))
    with pytest.raises(AzureLighthouseValidationError, match="bundle digest"):
        validate_onboarding_bundle(replace(bundle, bundle_sha256="sha256:bad"))


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"offer_name": ""}, "offer name"),
        ({"offer_name": "x" * 129}, "offer name"),
        ({"offer_description": ""}, "description"),
        ({"offer_description": "x" * 513}, "description"),
        ({"managing_tenant_id": "bad"}, "managing tenant"),
        ({"principal_id": "bad"}, "principal ID"),
        ({"principal_display_name": ""}, "principal display"),
        ({"deployment_scope": "tenant"}, "deployment scope"),
    ],
)
def test_onboarding_input_validation(kwargs: dict[str, str], message: str) -> None:
    values = {
        "offer_name": "WAIT delegation",
        "offer_description": "Reader inventory.",
        "managing_tenant_id": MANAGING_TENANT_ID,
        "principal_id": PRINCIPAL_ID,
        "principal_display_name": "WAIT",
        "deployment_scope": "subscription",
    }
    values.update(kwargs)
    with pytest.raises(AzureLighthouseValidationError, match=message):
        build_onboarding_bundle(**values)  # type: ignore[arg-type]


def test_validation_helpers_normalize_and_fail_closed() -> None:
    assert normalize_uuid(MANAGING_TENANT_ID.upper(), "tenant") == MANAGING_TENANT_ID
    assert normalize_name("  WAIT  ", "name") == "WAIT"
    assert normalize_description("  Reader.  ") == "Reader."
    assert normalize_resource_group("  App RG  ") == "App RG"
    assert normalize_resource_group(None) == ""
    assert scope_path(MANAGING_TENANT_ID) == f"/subscriptions/{MANAGING_TENANT_ID}"
    assert scope_path(MANAGING_TENANT_ID, "app-rg").endswith("/resourceGroups/app-rg")

    with pytest.raises(AzureLighthouseValidationError):
        normalize_name("bad\x00name", "name")
    with pytest.raises(AzureLighthouseValidationError):
        normalize_description("bad\x00description")
    for value in ("bad/rg", "bad.", "x" * 91):
        with pytest.raises(AzureLighthouseValidationError):
            normalize_resource_group(value)
