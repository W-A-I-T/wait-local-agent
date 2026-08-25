"""Data contracts and fixed boundaries for the Microsoft administrator pack."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Protocol

from wait_local_agent.models import ConnectorReadResult

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 4096
MAX_IDENTITY_LENGTH = 320
MAX_RECORDS_PER_SURFACE = 100
_STALE_DEVICE_DAYS = 7

_ENDPOINTS = frozenset(
    {
        "admin/serviceAnnouncement/healthOverviews",
        "admin/serviceAnnouncement/issues",
        "security/secureScores",
        "security/incidents",
        "security/alerts_v2",
        "auditLogs/signIns",
        "identity/conditionalAccess/policies",
        "identityProtection/riskyUsers",
        "deviceAppManagement/mobileApps",
        "deviceManagement/deviceCompliancePolicies",
        "deviceManagement/windowsAutopilotDeviceIdentities",
    }
)
_ALLOWED_CURSOR_KEYS = frozenset({"$skip", "$skiptoken"})
_SUCCESS_STATUSES = frozenset({"ready"})
_OPERATIONAL_SERVICE_STATUSES = frozenset({"serviceoperational", "servicerestored"})
_CLOSED_INCIDENT_STATUSES = frozenset({"resolved", "redirected"})
_LOW_RISK_LEVELS = frozenset({"", "none", "hidden", "low", "unknownfuturevalue"})


@dataclass(frozen=True)
class MicrosoftAdminReadResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]
    next_cursor: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "result": asdict(self.result),
            "items": self.items,
            "next_cursor": self.next_cursor,
        }


@dataclass(frozen=True)
class MicrosoftAdminFinding:
    code: str
    severity: str
    summary: str
    evidence: dict[str, object] = field(default_factory=dict)
    recommended_action: str = "review"
    action_id: str | None = None
    approval_required: bool = False


@dataclass(frozen=True)
class MicrosoftAdminDiagnostic:
    user_identity: str
    device_name: str
    generated_at: str
    evidence_completeness: float
    probable_root_cause: str
    findings: tuple[MicrosoftAdminFinding, ...]
    source_statuses: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "user_identity": self.user_identity,
            "device_name": self.device_name,
            "generated_at": self.generated_at,
            "evidence_completeness": self.evidence_completeness,
            "probable_root_cause": self.probable_root_cause,
            "findings": [asdict(finding) for finding in self.findings],
            "source_statuses": self.source_statuses,
        }


class MicrosoftAdminProvider(Protocol):
    def list_service_health(
        self, *, cursor: str | None = None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> MicrosoftAdminReadResponse: ...

    def list_service_issues(
        self, *, cursor: str | None = None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> MicrosoftAdminReadResponse: ...

    def list_secure_scores(
        self, *, cursor: str | None = None, page_size: int = 1
    ) -> MicrosoftAdminReadResponse: ...

    def list_sign_ins(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...

    def list_conditional_access_policies(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...

    def list_risky_users(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...

    def list_intune_apps(
        self, *, cursor: str | None = None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> MicrosoftAdminReadResponse: ...

    def list_compliance_policies(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...

    def list_autopilot_devices(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...

    def list_defender_incidents(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...

    def list_defender_alerts(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse: ...


class MicrosoftAdminError(RuntimeError):
    """Sanitized Microsoft administration read failure."""

