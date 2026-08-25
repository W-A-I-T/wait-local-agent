"""Bounded Azure Resource Manager client for Azure Lighthouse delegated scopes."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from wait_local_agent.config import Settings

from .models import (
    MANAGED_SERVICES_API_VERSION,
    MAX_RECORDS,
    RESOURCES_API_VERSION,
    SUBSCRIPTIONS_API_VERSION,
    AzureLighthouseAuthorizationError,
    AzureLighthouseBlockedError,
    AzureLighthouseProviderError,
    AzureLighthouseValidationError,
    LighthouseDelegation,
    LighthouseDiscoveryResult,
    LighthouseInventoryResult,
    LighthouseResource,
    LighthouseSubscription,
    TokenCredential,
    VerificationStatus,
)
from .normalizers import (
    aggregate_status,
    definition_scope,
    list_of_mappings,
    mapping,
    normalized_optional_uuid,
    resource_from_payload,
    scope_from_assignment_id,
    string,
    validate_definition_id,
)
from .transport import AzureArmTransport
from .validation import normalize_name, normalize_resource_group, normalize_uuid, scope_path


class AzureLighthouseClient:
    """Read-only Azure Lighthouse discovery and delegated-resource inventory."""

    def __init__(
        self,
        settings: Settings,
        credential: TokenCredential,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.arm = AzureArmTransport(settings, credential, transport=transport)

    def discover(
        self,
        *,
        client_id: str,
        managing_tenant_id: str,
        expected_customer_tenant_id: str,
    ) -> LighthouseDiscoveryResult:
        """Discover customer subscriptions projected into the managing tenant."""

        self._assert_enabled()
        wait_client = normalize_name(client_id, "WAIT client ID")
        managing_tenant = normalize_uuid(managing_tenant_id, "managing tenant ID")
        customer_tenant = normalize_uuid(expected_customer_tenant_id, "customer tenant ID")
        raw_subscriptions = self.arm.collection(
            "/subscriptions",
            {"api-version": SUBSCRIPTIONS_API_VERSION},
        )
        subscriptions: list[LighthouseSubscription] = []
        source_errors: list[dict[str, str]] = []
        for raw in raw_subscriptions[:MAX_RECORDS]:
            subscription_id = string(raw.get("subscriptionId"))
            if not subscription_id:
                continue
            try:
                subscription_id = normalize_uuid(subscription_id, "subscription ID")
            except AzureLighthouseValidationError:
                source_errors.append(
                    {
                        "source": "subscriptions",
                        "code": "invalid_subscription_id",
                        "message": "Azure returned a subscription with an invalid identifier.",
                    }
                )
                continue
            tenant_id = normalized_optional_uuid(raw.get("tenantId"))
            if tenant_id != customer_tenant:
                continue
            managed_by_tenants = tuple(
                sorted(
                    {
                        normalized
                        for entry in list_of_mappings(raw.get("managedByTenants"))
                        if (normalized := normalized_optional_uuid(entry.get("tenantId")))
                    }
                )
            )
            if managing_tenant not in managed_by_tenants:
                continue

            verification_status: VerificationStatus = "projected"
            verification_message = (
                "Subscription projects the managing tenant; verify a registration assignment "
                "at the intended scope."
            )
            delegation_count = 0
            try:
                delegations = self.list_delegations(
                    subscription_id=subscription_id,
                    managing_tenant_id=managing_tenant,
                )
                delegation_count = len(delegations)
                if delegations:
                    verification_status = "verified"
                    verification_message = (
                        "Subscription-level Azure Lighthouse registration assignment is verified."
                    )
            except (AzureLighthouseAuthorizationError, AzureLighthouseProviderError) as exc:
                verification_status = "unavailable"
                verification_message = "Azure Lighthouse assignment verification was unavailable."
                source_errors.append(
                    {
                        "source": f"subscription:{subscription_id}",
                        "code": "delegation_verification_unavailable",
                        "message": str(exc),
                    }
                )
            subscriptions.append(
                LighthouseSubscription(
                    subscription_id=subscription_id,
                    display_name=string(raw.get("displayName")) or subscription_id,
                    customer_tenant_id=tenant_id,
                    state=string(raw.get("state")),
                    managed_by_tenant_ids=managed_by_tenants,
                    verification_status=verification_status,
                    delegation_count=delegation_count,
                    verification_message=verification_message,
                )
            )

        subscriptions.sort(key=lambda item: (item.display_name.casefold(), item.subscription_id))
        return LighthouseDiscoveryResult(
            status=aggregate_status(bool(subscriptions), source_errors),
            client_id=wait_client,
            managing_tenant_id=managing_tenant,
            expected_customer_tenant_id=customer_tenant,
            subscriptions=tuple(subscriptions),
            source_errors=tuple(source_errors),
        )

    def inventory(
        self,
        *,
        client_id: str,
        managing_tenant_id: str,
        expected_customer_tenant_id: str,
        subscription_id: str,
        resource_group: str | None = None,
        limit: int = 200,
    ) -> LighthouseInventoryResult:
        """Verify one delegated scope and inventory its ARM resources."""

        self._assert_enabled()
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_RECORDS:
            raise AzureLighthouseValidationError(
                f"Azure Lighthouse inventory limit must be between 1 and {MAX_RECORDS}."
            )
        wait_client = normalize_name(client_id, "WAIT client ID")
        managing_tenant = normalize_uuid(managing_tenant_id, "managing tenant ID")
        customer_tenant = normalize_uuid(expected_customer_tenant_id, "customer tenant ID")
        subscription = normalize_uuid(subscription_id, "subscription ID")
        group = normalize_resource_group(resource_group)

        raw_subscriptions = self.arm.collection(
            "/subscriptions",
            {"api-version": SUBSCRIPTIONS_API_VERSION},
        )
        raw_subscription = next(
            (
                item
                for item in raw_subscriptions
                if normalized_optional_uuid(item.get("subscriptionId")) == subscription
            ),
            None,
        )
        if raw_subscription is None:
            raise AzureLighthouseAuthorizationError(
                "Azure Lighthouse subscription is not accessible to the managing credential."
            )
        if normalized_optional_uuid(raw_subscription.get("tenantId")) != customer_tenant:
            raise AzureLighthouseAuthorizationError(
                "Azure Lighthouse subscription belongs to a different customer tenant."
            )
        managed_by_tenants = {
            normalized
            for entry in list_of_mappings(raw_subscription.get("managedByTenants"))
            if (normalized := normalized_optional_uuid(entry.get("tenantId")))
        }
        if managing_tenant not in managed_by_tenants:
            raise AzureLighthouseAuthorizationError(
                "Azure Lighthouse managing tenant is not projected on the requested subscription."
            )

        delegations = self.list_delegations(
            subscription_id=subscription,
            managing_tenant_id=managing_tenant,
            resource_group=group,
        )
        if not delegations:
            raise AzureLighthouseAuthorizationError(
                "Azure Lighthouse registration assignment was not verified at the requested scope."
            )

        scope = scope_path(subscription, group)
        raw_resources = self.arm.collection(
            f"{scope}/resources",
            {"api-version": RESOURCES_API_VERSION},
            max_records=limit,
        )
        resources_list: list[LighthouseResource] = []
        invalid_resource_count = 0
        outside_scope_count = 0
        required_prefix = f"{scope.casefold()}/"
        for raw in raw_resources[:limit]:
            resource = resource_from_payload(raw)
            if resource is None:
                invalid_resource_count += 1
                continue
            if not resource.resource_id.casefold().startswith(required_prefix):
                outside_scope_count += 1
                continue
            resources_list.append(resource)
        resources = tuple(resources_list)
        source_errors: list[dict[str, str]] = []
        if invalid_resource_count:
            source_errors.append(
                {
                    "source": scope,
                    "code": "invalid_resource_records",
                    "message": (
                        f"Azure returned {invalid_resource_count} resource record(s) "
                        "without the required identity fields."
                    ),
                }
            )
        if outside_scope_count:
            source_errors.append(
                {
                    "source": scope,
                    "code": "outside_scope_resources",
                    "message": (
                        f"Azure returned {outside_scope_count} resource record(s) "
                        "outside the verified delegated scope."
                    ),
                }
            )
        counts: dict[str, int] = {}
        for resource in resources:
            counts[resource.resource_type] = counts.get(resource.resource_type, 0) + 1
        return LighthouseInventoryResult(
            status=aggregate_status(bool(resources), source_errors),
            client_id=wait_client,
            managing_tenant_id=managing_tenant,
            customer_tenant_id=customer_tenant,
            subscription_id=subscription,
            resource_group=group,
            scope=scope,
            delegation_verified=True,
            delegations=delegations,
            resources=resources,
            resource_type_counts=dict(sorted(counts.items())),
            source_errors=tuple(source_errors),
        )

    def list_delegations(
        self,
        *,
        subscription_id: str,
        managing_tenant_id: str,
        resource_group: str | None = None,
    ) -> tuple[LighthouseDelegation, ...]:
        """List registration assignments at one exact subscription or resource-group scope."""

        subscription = normalize_uuid(subscription_id, "subscription ID")
        managing_tenant = normalize_uuid(managing_tenant_id, "managing tenant ID")
        group = normalize_resource_group(resource_group)
        scope = scope_path(subscription, group)
        assignments = self.arm.collection(
            f"{scope}/providers/Microsoft.ManagedServices/registrationAssignments",
            {
                "api-version": MANAGED_SERVICES_API_VERSION,
                "$expandRegistrationDefinition": "true",
            },
        )
        delegations: list[LighthouseDelegation] = []
        for assignment in assignments:
            properties = mapping(assignment.get("properties"))
            provisioning_state = string(properties.get("provisioningState"))
            if provisioning_state.casefold() not in {"succeeded", "created"}:
                continue
            assignment_id = string(assignment.get("id"))
            assignment_scope = scope_from_assignment_id(assignment_id)
            if not assignment_scope or assignment_scope.casefold() != scope.casefold():
                continue

            definition_id = string(properties.get("registrationDefinitionId"))
            if definition_id:
                subscription_scope = scope_path(subscription)
                allowed_definition_scopes = {
                    subscription_scope.casefold(),
                    scope.casefold(),
                }
                if definition_scope(definition_id).casefold() not in allowed_definition_scopes:
                    continue
            definition = mapping(properties.get("registrationDefinition"))
            definition_properties = mapping(definition.get("properties"))
            if not definition_properties and definition_id:
                definition_properties = mapping(self._definition(definition_id).get("properties"))
            definition_managing_tenant = normalized_optional_uuid(
                definition_properties.get("managedByTenantId")
            )
            if definition_managing_tenant != managing_tenant:
                continue
            authorization_rows: list[dict[str, str]] = []
            for item in list_of_mappings(definition_properties.get("authorizations")):
                principal_id = normalized_optional_uuid(item.get("principalId"))
                role_definition_id = normalized_optional_uuid(item.get("roleDefinitionId"))
                if not principal_id or not role_definition_id:
                    continue
                authorization_rows.append(
                    {
                        "principal_id": principal_id,
                        "principal_display_name": string(item.get("principalIdDisplayName")),
                        "role_definition_id": role_definition_id,
                    }
                )
            authorizations = tuple(authorization_rows)
            delegations.append(
                LighthouseDelegation(
                    assignment_id=assignment_id,
                    assignment_name=string(assignment.get("name")),
                    definition_id=definition_id or string(definition.get("id")),
                    definition_name=string(
                        definition_properties.get("registrationDefinitionName")
                    ),
                    managed_by_tenant_id=definition_managing_tenant,
                    provisioning_state=provisioning_state,
                    scope=assignment_scope,
                    authorizations=authorizations,
                )
            )
        delegations.sort(key=lambda item: (item.scope.casefold(), item.assignment_id))
        return tuple(delegations)

    def _definition(self, definition_id: str) -> Mapping[str, object]:
        path = validate_definition_id(definition_id)
        return self.arm.object(path, {"api-version": MANAGED_SERVICES_API_VERSION})

    def _assert_enabled(self) -> None:
        if not self.settings.allow_http_probing:
            raise AzureLighthouseBlockedError(
                "Azure Lighthouse live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
