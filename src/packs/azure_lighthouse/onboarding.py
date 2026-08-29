"""Deterministic customer-deployable Azure Lighthouse onboarding artifacts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from .models import (
    MANAGED_SERVICES_API_VERSION,
    READER_ROLE_DEFINITION_ID,
    AzureLighthouseValidationError,
)
from .validation import normalize_description, normalize_name, normalize_uuid

DeploymentScope = Literal["subscription", "resource_group"]
ONBOARDING_FORMAT = "wait.azure-lighthouse.onboarding/v1"


@dataclass(frozen=True)
class AzureLighthouseOnboardingBundle:
    format: str
    deployment_scope: DeploymentScope
    role_profile: str
    template: dict[str, object]
    parameters: dict[str, object]
    template_sha256: str
    parameters_sha256: str
    bundle_sha256: str
    deployment_guidance: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def build_onboarding_bundle(
    *,
    offer_name: str,
    offer_description: str,
    managing_tenant_id: str,
    principal_id: str,
    principal_display_name: str,
    deployment_scope: DeploymentScope = "subscription",
) -> AzureLighthouseOnboardingBundle:
    """Generate a reviewable Reader-only onboarding package; never deploy it."""

    if deployment_scope not in {"subscription", "resource_group"}:
        raise AzureLighthouseValidationError(
            "Azure Lighthouse deployment scope must be subscription or resource_group."
        )
    normalized_offer_name = normalize_name(offer_name, "offer name")
    normalized_description = normalize_description(offer_description)
    normalized_managing_tenant = normalize_uuid(managing_tenant_id, "managing tenant ID")
    normalized_principal = normalize_uuid(principal_id, "principal ID")
    normalized_display_name = normalize_name(principal_display_name, "principal display name")
    schema = (
        "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentTemplate.json#"
        if deployment_scope == "subscription"
        else "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
    )
    parameter_schema = (
        "https://schema.management.azure.com/schemas/2018-05-01/subscriptionDeploymentParameters.json#"
        if deployment_scope == "subscription"
        else "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#"
    )
    template: dict[str, object] = {
        "$schema": schema,
        "contentVersion": "1.0.0.0",
        "parameters": {
            "mspOfferName": {"type": "string"},
            "mspOfferDescription": {"type": "string"},
            "managedByTenantId": {"type": "string"},
            "authorizations": {"type": "array"},
        },
        "variables": {
            "mspRegistrationName": "[guid(parameters('mspOfferName'), parameters('managedByTenantId'))]",
            "mspAssignmentName": "[guid(parameters('mspOfferName'), parameters('managedByTenantId'), 'assignment')]",
        },
        "resources": [
            {
                "type": "Microsoft.ManagedServices/registrationDefinitions",
                "apiVersion": MANAGED_SERVICES_API_VERSION,
                "name": "[variables('mspRegistrationName')]",
                "properties": {
                    "registrationDefinitionName": "[parameters('mspOfferName')]",
                    "description": "[parameters('mspOfferDescription')]",
                    "managedByTenantId": "[parameters('managedByTenantId')]",
                    "authorizations": "[parameters('authorizations')]",
                },
            },
            {
                "type": "Microsoft.ManagedServices/registrationAssignments",
                "apiVersion": MANAGED_SERVICES_API_VERSION,
                "name": "[variables('mspAssignmentName')]",
                "dependsOn": [
                    (
                        "[resourceId('Microsoft.ManagedServices/registrationDefinitions', "
                        "variables('mspRegistrationName'))]"
                    )
                ],
                "properties": {
                    "registrationDefinitionId": (
                        "[resourceId('Microsoft.ManagedServices/registrationDefinitions', "
                        "variables('mspRegistrationName'))]"
                    )
                },
            },
        ],
        "outputs": {
            "registrationDefinitionId": {
                "type": "string",
                "value": (
                    "[resourceId('Microsoft.ManagedServices/registrationDefinitions', "
                    "variables('mspRegistrationName'))]"
                ),
            },
            "registrationAssignmentId": {
                "type": "string",
                "value": (
                    "[resourceId('Microsoft.ManagedServices/registrationAssignments', "
                    "variables('mspAssignmentName'))]"
                ),
            },
        },
    }
    parameters: dict[str, object] = {
        "$schema": parameter_schema,
        "contentVersion": "1.0.0.0",
        "parameters": {
            "mspOfferName": {"value": normalized_offer_name},
            "mspOfferDescription": {"value": normalized_description},
            "managedByTenantId": {"value": normalized_managing_tenant},
            "authorizations": {
                "value": [
                    {
                        "principalId": normalized_principal,
                        "principalIdDisplayName": normalized_display_name,
                        "roleDefinitionId": READER_ROLE_DEFINITION_ID,
                    }
                ]
            },
        },
    }
    template_sha = _sha256_json(template)
    parameters_sha = _sha256_json(parameters)
    bundle_basis = {
        "format": ONBOARDING_FORMAT,
        "deployment_scope": deployment_scope,
        "role_profile": "inventory-reader",
        "template_sha256": f"sha256:{template_sha}",
        "parameters_sha256": f"sha256:{parameters_sha}",
    }
    guidance = (
        (
            "Customer reviews both JSON artifacts and deploys the template at the intended subscription scope.",
            "WAIT does not deploy or approve Azure Lighthouse delegation on the customer's behalf.",
            (
                "After deployment, use Azure Lighthouse discovery and exact-scope verification "
                "before collecting inventory."
            ),
        )
        if deployment_scope == "subscription"
        else (
            "Customer reviews both JSON artifacts and deploys the template in the intended resource group.",
            "WAIT does not deploy or approve Azure Lighthouse delegation on the customer's behalf.",
            "After deployment, inventory requests must specify the same resource group for exact-scope verification.",
        )
    )
    return AzureLighthouseOnboardingBundle(
        format=ONBOARDING_FORMAT,
        deployment_scope=deployment_scope,
        role_profile="inventory-reader",
        template=template,
        parameters=parameters,
        template_sha256=f"sha256:{template_sha}",
        parameters_sha256=f"sha256:{parameters_sha}",
        bundle_sha256=f"sha256:{_sha256_json(bundle_basis)}",
        deployment_guidance=guidance,
    )


def validate_onboarding_bundle(bundle: AzureLighthouseOnboardingBundle) -> None:
    """Verify artifact digests before export or display."""

    if bundle.format != ONBOARDING_FORMAT or bundle.role_profile != "inventory-reader":
        raise AzureLighthouseValidationError("Azure Lighthouse onboarding bundle format is unsupported.")
    if bundle.template_sha256 != f"sha256:{_sha256_json(bundle.template)}":
        raise AzureLighthouseValidationError("Azure Lighthouse onboarding template digest is invalid.")
    if bundle.parameters_sha256 != f"sha256:{_sha256_json(bundle.parameters)}":
        raise AzureLighthouseValidationError("Azure Lighthouse onboarding parameters digest is invalid.")
    basis = {
        "format": bundle.format,
        "deployment_scope": bundle.deployment_scope,
        "role_profile": bundle.role_profile,
        "template_sha256": bundle.template_sha256,
        "parameters_sha256": bundle.parameters_sha256,
    }
    if bundle.bundle_sha256 != f"sha256:{_sha256_json(basis)}":
        raise AzureLighthouseValidationError("Azure Lighthouse onboarding bundle digest is invalid.")


def _sha256_json(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
