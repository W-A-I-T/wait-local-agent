"""Stable contracts for the Azure Lighthouse integration pack."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Protocol

ARM_BASE_URL = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
SUBSCRIPTIONS_API_VERSION = "2022-12-01"
MANAGED_SERVICES_API_VERSION = "2022-10-01"
RESOURCES_API_VERSION = "2021-04-01"
READER_ROLE_DEFINITION_ID = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
MAX_PAGES = 20
MAX_RECORDS = 500
MAX_NAME_LENGTH = 128
MAX_DESCRIPTION_LENGTH = 512
MAX_RESOURCE_GROUP_LENGTH = 90

VerificationStatus = Literal["verified", "projected", "unavailable"]
SourceStatus = Literal["ready", "partial", "blocked", "not_configured", "failed"]


class TokenLike(Protocol):
    token: str


class TokenCredential(Protocol):
    def get_token(self, *scopes: str, **kwargs: object) -> TokenLike: ...


@dataclass(frozen=True)
class LighthouseDelegation:
    assignment_id: str
    assignment_name: str
    definition_id: str
    definition_name: str
    managed_by_tenant_id: str
    provisioning_state: str
    scope: str
    authorizations: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LighthouseSubscription:
    subscription_id: str
    display_name: str
    customer_tenant_id: str
    state: str
    managed_by_tenant_ids: tuple[str, ...]
    verification_status: VerificationStatus
    delegation_count: int = 0
    verification_message: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LighthouseResource:
    resource_id: str
    name: str
    resource_type: str
    location: str
    resource_group: str
    kind: str
    sku_name: str
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class LighthouseDiscoveryResult:
    status: SourceStatus
    client_id: str
    managing_tenant_id: str
    expected_customer_tenant_id: str
    subscriptions: tuple[LighthouseSubscription, ...]
    source_errors: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "client_id": self.client_id,
            "managing_tenant_id": self.managing_tenant_id,
            "expected_customer_tenant_id": self.expected_customer_tenant_id,
            "subscriptions": [subscription.to_dict() for subscription in self.subscriptions],
            "source_errors": list(self.source_errors),
        }


@dataclass(frozen=True)
class LighthouseInventoryResult:
    status: SourceStatus
    client_id: str
    managing_tenant_id: str
    customer_tenant_id: str
    subscription_id: str
    resource_group: str
    scope: str
    delegation_verified: bool
    delegations: tuple[LighthouseDelegation, ...]
    resources: tuple[LighthouseResource, ...]
    resource_type_counts: dict[str, int]
    source_errors: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "client_id": self.client_id,
            "managing_tenant_id": self.managing_tenant_id,
            "customer_tenant_id": self.customer_tenant_id,
            "subscription_id": self.subscription_id,
            "resource_group": self.resource_group,
            "scope": self.scope,
            "delegation_verified": self.delegation_verified,
            "delegations": [delegation.to_dict() for delegation in self.delegations],
            "resources": [resource.to_dict() for resource in self.resources],
            "resource_type_counts": self.resource_type_counts,
            "source_errors": list(self.source_errors),
        }


class AzureLighthouseError(RuntimeError):
    """Base class for sanitized Azure Lighthouse failures."""


class AzureLighthouseBlockedError(AzureLighthouseError):
    """The local policy prevents an outbound Azure operation."""


class AzureLighthouseCredentialError(AzureLighthouseError):
    """A vault-backed Azure credential cannot be resolved safely."""


class AzureLighthouseAuthorizationError(AzureLighthouseError):
    """Azure rejected access to the requested delegated scope."""


class AzureLighthouseProviderError(AzureLighthouseError):
    """Azure returned an unavailable or malformed provider result."""


class AzureLighthouseValidationError(AzureLighthouseError):
    """A caller supplied an unsupported identifier or onboarding value."""
