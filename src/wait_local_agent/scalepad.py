"""Bounded, read-only ScalePad Core, ControlMap, and Lifecycle adapter.

ScalePad's documented Core API exposes client inventory, its ControlMap API
exposes partner-wide risk summaries, and its Lifecycle Manager API exposes
client goals and assessments with an API key and cursor pagination. WAIT uses
fixed, local
mappings for each provider identifier and an exact provider filter; returned
records are checked against those mappings before they leave the connector
boundary. Core client, ControlMap tenant, and Lifecycle client IDs are kept as
separate mappings because the public documentation does not establish that
they are interchangeable. No ScalePad writes are exposed here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.reports.renderers import redact_value

DEFAULT_PAGE_SIZE = 1
MAX_PAGE_SIZE = 1
RISK_SUMMARY_PAGE_SIZE = 20
MAX_RISK_SUMMARY_ROWS = 20
GOALS_PAGE_SIZE = 20
MAX_GOAL_ROWS = 20
ASSESSMENTS_PAGE_SIZE = 20
MAX_ASSESSMENT_ROWS = 20
MAX_CLIENT_ID_LENGTH = 120
MAX_PROVIDER_ID_LENGTH = 200
MAX_TEXT_LENGTH = 500
MAX_ENDPOINT_LENGTH = 240
MAX_RISK_SUMMARY_DEPTH = 4
MAX_RISK_SUMMARY_FIELDS = 64
MAX_RISK_SUMMARY_LIST_ITEMS = 20
MAX_GOAL_TITLE_LENGTH = 200
_GOAL_STATUSES = frozenset({"AtRisk", "Complete", "OffTrack", "OnHold", "OnTrack"})
_ASSESSMENT_STATUSES = frozenset({"Completed", "InProgress"})


@dataclass(frozen=True)
class ScalePadClientRecord:
    id: str
    name: str
    lifecycle: str
    num_contacts: int | None
    num_hardware_assets: int | None
    record_created_at: str
    record_updated_at: str


@dataclass(frozen=True)
class ScalePadClientResponse:
    result: ConnectorReadResult
    items: list[ScalePadClientRecord]
    next_cursor: str = ""


@dataclass(frozen=True)
class ScalePadRiskSummaryResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]
    next_cursor: str = ""
    total_count: int | None = None


@dataclass(frozen=True)
class ScalePadComplianceHealthResponse:
    result: ConnectorReadResult
    item: dict[str, object] | None = None


@dataclass(frozen=True)
class ScalePadGoalResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]
    next_cursor: str = ""
    total_count: int | None = None


@dataclass(frozen=True)
class ScalePadAssessmentResponse:
    result: ConnectorReadResult
    items: list[dict[str, object]]
    next_cursor: str = ""
    total_count: int | None = None


class ScalePadReadError(Exception):
    """Safe, operator-facing ScalePad adapter error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ScalePadReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def get_client(self, *, client_id: str) -> ScalePadClientResponse:
        ...

    def get_risk_summary(self, *, client_id: str) -> ScalePadRiskSummaryResponse:
        ...

    def get_compliance_health(self, *, client_id: str) -> ScalePadComplianceHealthResponse:
        ...

    def get_goals(
        self,
        *,
        client_id: str,
        status: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
    ) -> ScalePadGoalResponse:
        ...

    def get_assessments(
        self,
        *,
        client_id: str,
        status: str | None = None,
        assessment_template_id: str | None = None,
        cursor: str | None = None,
    ) -> ScalePadAssessmentResponse:
        ...


class ScalePadClient:
    """Normalize the documented ScalePad Core client-list contract."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_base_result()
        if missing is not None:
            return missing
        configured_surfaces = (
            (self.settings.scalepad_client_map_json, self._client_mapping),
            (self.settings.scalepad_risk_tenant_map_json, self._risk_tenant_mapping),
            (
                self.settings.scalepad_compliance_client_map_json,
                self._compliance_client_mapping,
            ),
            (
                self.settings.scalepad_lifecycle_client_map_json,
                self._lifecycle_client_mapping,
            ),
        )
        errors: list[str] = []
        for raw_mapping, mapping_validator in configured_surfaces:
            if not raw_mapping:
                continue
            try:
                mapping = json.loads(raw_mapping)
                if not isinstance(mapping, Mapping) or not mapping:
                    raise ScalePadReadError("ScalePad mapping must contain at least one client mapping.")
                mapping_validator(str(next(iter(mapping))))
            except ScalePadReadError as exc:
                errors.append(exc.message)
        if not any(raw_mapping for raw_mapping, _ in configured_surfaces):
            return ConnectorReadResult(
                "not_configured",
                "ScalePad credentials are incomplete: configure at least one client mapping.",
            )
        if errors and len(errors) == sum(bool(raw_mapping) for raw_mapping, _ in configured_surfaces):
            return ConnectorReadResult("failed", errors[0])
        return ConnectorReadResult("ready", "ScalePad read prerequisites are ready.")

    def get_client(self, *, client_id: str) -> ScalePadClientResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            provider_id = self._client_mapping(client_id)
            payload = self._get(
                "core/v1/clients",
                params={"filter[id]": f"eq:{provider_id}", "page_size": str(DEFAULT_PAGE_SIZE)},
                configuration="client",
            )
        except ScalePadReadError as exc:
            return ScalePadClientResponse(ConnectorReadResult("failed", exc.message), [])
        if not isinstance(payload, Mapping):
            return ScalePadClientResponse(
                ConnectorReadResult("failed", "ScalePad returned a malformed response object."),
                [],
            )
        rows = payload.get("data")
        if not isinstance(rows, list):
            return ScalePadClientResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed client data."), []
            )
        items: list[ScalePadClientRecord] = []
        for row in rows[:MAX_PAGE_SIZE]:
            normalized = _normalize_client(row, provider_id)
            if normalized is not None:
                items.append(normalized)
        next_cursor = _optional_provider_id(payload.get("next_cursor"))
        return ScalePadClientResponse(
            ConnectorReadResult("ready", "ScalePad client read succeeded.", len(items)),
            items,
            next_cursor,
        )

    def get_risk_summary(self, *, client_id: str) -> ScalePadRiskSummaryResponse:
        """Read one explicitly mapped client's documented risk-summary page."""

        blocked = self._blocked_risk_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_risk_response()
        if missing is not None:
            return missing
        try:
            tenant_id = self._risk_tenant_mapping(client_id)
            payload = self._get(
                "controlmap/v1/clients/risks-summary",
                params={
                    "filter[client.tenant_id]": f"eq:{tenant_id}",
                    "page_size": str(RISK_SUMMARY_PAGE_SIZE),
                },
                configuration="risk",
            )
        except ScalePadReadError as exc:
            return ScalePadRiskSummaryResponse(ConnectorReadResult("failed", exc.message), [])
        if not isinstance(payload, Mapping):
            return ScalePadRiskSummaryResponse(
                ConnectorReadResult("failed", "ScalePad returned a malformed response object."),
                [],
            )
        rows = payload.get("data")
        if not isinstance(rows, list):
            return ScalePadRiskSummaryResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed risk-summary data."),
                [],
            )
        items: list[dict[str, object]] = []
        for row in rows[:MAX_RISK_SUMMARY_ROWS]:
            normalized = _normalize_risk_summary(row, tenant_id)
            if normalized is not None:
                items.append(normalized)
        return ScalePadRiskSummaryResponse(
            ConnectorReadResult("ready", "ScalePad risk-summary read succeeded.", len(items)),
            items,
            _optional_cursor(payload.get("next_cursor")),
            _optional_nonnegative_int(payload.get("total_count")),
        )

    def get_compliance_health(self, *, client_id: str) -> ScalePadComplianceHealthResponse:
        """Read one explicitly mapped client's documented ControlMap health snapshot."""

        blocked = self._blocked_compliance_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_compliance_response()
        if missing is not None:
            return missing
        try:
            provider_id = self._compliance_client_mapping(client_id)
            payload = self._get(
                f"controlmap/v1/clients/{provider_id}/health",
                configuration="compliance",
            )
        except ScalePadReadError as exc:
            return ScalePadComplianceHealthResponse(ConnectorReadResult("failed", exc.message))
        if not isinstance(payload, Mapping):
            return ScalePadComplianceHealthResponse(
                ConnectorReadResult("failed", "ScalePad returned a malformed health response object.")
            )
        bounded = _bound_risk_value(payload, depth=0)
        if not isinstance(bounded, dict):
            return ScalePadComplianceHealthResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed compliance health data.")
            )
        client = bounded.get("client")
        if isinstance(client, Mapping) and "id" in client:
            returned_id = _optional_provider_id(client.get("id"))
            if returned_id != provider_id:
                return ScalePadComplianceHealthResponse(
                    ConnectorReadResult("failed", "ScalePad compliance health is outside the mapped client scope.")
                )
        redacted = redact_value(bounded)
        if not isinstance(redacted, dict):
            return ScalePadComplianceHealthResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed compliance health data.")
            )
        return ScalePadComplianceHealthResponse(
            ConnectorReadResult("ready", "ScalePad compliance health read succeeded.", 1),
            redacted,
        )

    def get_goals(
        self,
        *,
        client_id: str,
        status: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
    ) -> ScalePadGoalResponse:
        """Read one explicitly mapped client's Lifecycle Manager goals page."""

        blocked = self._blocked_goal_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_goal_response()
        if missing is not None:
            return missing
        try:
            provider_id = self._lifecycle_client_mapping(client_id)
            params: dict[str, str] = {
                "filter[client.id]": f"eq:{provider_id}",
                "page_size": str(GOALS_PAGE_SIZE),
            }
            if status is not None:
                params["filter[status]"] = f"eq:{_goal_status(status)}"
            if title is not None:
                params["filter[title]"] = f"cont:{_goal_title(title)}"
            if cursor is not None:
                params["cursor"] = _required_cursor(cursor)
            payload = self._get(
                "lifecycle-manager/v1/goals",
                params=params,
                configuration="lifecycle",
            )
        except ScalePadReadError as exc:
            return ScalePadGoalResponse(ConnectorReadResult("failed", exc.message), [])
        if not isinstance(payload, Mapping):
            return ScalePadGoalResponse(
                ConnectorReadResult("failed", "ScalePad returned a malformed response object."),
                [],
            )
        rows = payload.get("data")
        if not isinstance(rows, list):
            return ScalePadGoalResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed goal data."),
                [],
            )
        items: list[dict[str, object]] = []
        for row in rows[:MAX_GOAL_ROWS]:
            normalized = _normalize_goal(row, provider_id)
            if normalized is not None:
                items.append(normalized)
        return ScalePadGoalResponse(
            ConnectorReadResult("ready", "ScalePad goal read succeeded.", len(items)),
            items,
            _optional_cursor(payload.get("next_cursor")),
            _optional_nonnegative_int(payload.get("total_count")),
        )

    def get_assessments(
        self,
        *,
        client_id: str,
        status: str | None = None,
        assessment_template_id: str | None = None,
        cursor: str | None = None,
    ) -> ScalePadAssessmentResponse:
        """Read one explicitly mapped client's Lifecycle assessments page."""

        blocked = self._blocked_assessment_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_assessment_response()
        if missing is not None:
            return missing
        try:
            provider_id = self._lifecycle_client_mapping(client_id)
            params: dict[str, str] = {
                "filter[client.id]": f"eq:{provider_id}",
                "page_size": str(ASSESSMENTS_PAGE_SIZE),
            }
            if status is not None:
                params["filter[status]"] = f"eq:{_assessment_status(status)}"
            if assessment_template_id is not None:
                params["filter[assessment_template_id]"] = (
                    f"eq:{_assessment_template_id(assessment_template_id)}"
                )
            if cursor is not None:
                params["cursor"] = _required_cursor(cursor)
            payload = self._get(
                "lifecycle-manager/v1/assessments",
                params=params,
                configuration="lifecycle",
            )
        except ScalePadReadError as exc:
            return ScalePadAssessmentResponse(ConnectorReadResult("failed", exc.message), [])
        if not isinstance(payload, Mapping):
            return ScalePadAssessmentResponse(
                ConnectorReadResult("failed", "ScalePad returned a malformed response object."),
                [],
            )
        rows = payload.get("data")
        if not isinstance(rows, list):
            return ScalePadAssessmentResponse(
                ConnectorReadResult("failed", "ScalePad returned malformed assessment data."),
                [],
            )
        items: list[dict[str, object]] = []
        for row in rows[:MAX_ASSESSMENT_ROWS]:
            normalized = _normalize_goal(row, provider_id)
            if normalized is not None:
                items.append(normalized)
        return ScalePadAssessmentResponse(
            ConnectorReadResult("ready", "ScalePad assessment read succeeded.", len(items)),
            items,
            _optional_cursor(payload.get("next_cursor")),
            _optional_nonnegative_int(payload.get("total_count")),
        )

    def _get(
        self,
        endpoint: str,
        *,
        params: Mapping[str, str] | None = None,
        configuration: str = "client",
    ) -> object:
        if not self.settings.allow_http_probing:
            raise ScalePadReadError(
                "ScalePad live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if configuration == "risk":
            missing = self._not_configured_risk_result()
        elif configuration == "compliance":
            missing = self._not_configured_compliance_result()
        elif configuration == "lifecycle":
            missing = self._not_configured_lifecycle_result()
        else:
            missing = self._not_configured_result()
        if missing is not None:
            raise ScalePadReadError(missing.message)
        url = _endpoint_url(self.settings.scalepad_base_url, endpoint)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                response = client.get(
                    url,
                    headers={"Accept": "application/json", "x-api-key": self.settings.scalepad_api_key.strip()},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise ScalePadReadError("ScalePad request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise ScalePadReadError("ScalePad request failed.") from exc
        if response.status_code in {401, 403}:
            raise ScalePadReadError("ScalePad request was unauthorized.")
        if response.status_code == 402:
            raise ScalePadReadError("ScalePad request requires an enabled API subscription.")
        if response.status_code == 429:
            raise ScalePadReadError("ScalePad request was rate limited.")
        if response.status_code >= 400:
            raise ScalePadReadError(f"ScalePad request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ScalePadReadError("ScalePad returned malformed JSON.") from exc
        return payload

    def _client_mapping(self, client_id: str) -> str:
        safe_client_id = _safe_client_id(client_id)
        try:
            mapping = json.loads(self.settings.scalepad_client_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise ScalePadReadError("WAIT_SCALEPAD_CLIENT_MAP_JSON is malformed.") from exc
        if not isinstance(mapping, Mapping):
            raise ScalePadReadError("WAIT_SCALEPAD_CLIENT_MAP_JSON must be an object.")
        if safe_client_id not in mapping:
            raise ScalePadReadError("ScalePad client mapping is outside the tenant scope.")
        raw_provider_id = mapping[safe_client_id]
        if not isinstance(raw_provider_id, str) or not raw_provider_id.strip():
            raise ScalePadReadError("ScalePad client mapping must use non-empty strings.")
        return _bounded_provider_id(raw_provider_id)

    def _risk_tenant_mapping(self, client_id: str) -> str:
        safe_client_id = _safe_client_id(client_id)
        try:
            mapping = json.loads(self.settings.scalepad_risk_tenant_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise ScalePadReadError(
                "WAIT_SCALEPAD_RISK_TENANT_MAP_JSON is malformed."
            ) from exc
        if not isinstance(mapping, Mapping):
            raise ScalePadReadError(
                "WAIT_SCALEPAD_RISK_TENANT_MAP_JSON must be an object."
            )
        if safe_client_id not in mapping:
            raise ScalePadReadError(
                "ScalePad risk-summary mapping is outside the tenant scope."
            )
        raw_tenant_id = mapping[safe_client_id]
        if not isinstance(raw_tenant_id, str) or not raw_tenant_id.strip():
            raise ScalePadReadError(
                "ScalePad risk-summary mapping must use non-empty strings."
            )
        return _bounded_provider_id(raw_tenant_id)

    def _lifecycle_client_mapping(self, client_id: str) -> str:
        safe_client_id = _safe_client_id(client_id)
        try:
            mapping = json.loads(self.settings.scalepad_lifecycle_client_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise ScalePadReadError(
                "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON is malformed."
            ) from exc
        if not isinstance(mapping, Mapping):
            raise ScalePadReadError(
                "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON must be an object."
            )
        if safe_client_id not in mapping:
            raise ScalePadReadError(
                "ScalePad Lifecycle client mapping is outside the tenant scope."
            )
        raw_provider_id = mapping[safe_client_id]
        if not isinstance(raw_provider_id, str) or not raw_provider_id.strip():
            raise ScalePadReadError(
                "ScalePad Lifecycle client mapping must use non-empty strings."
            )
        return _bounded_provider_id(raw_provider_id)

    def _compliance_client_mapping(self, client_id: str) -> str:
        safe_client_id = _safe_client_id(client_id)
        try:
            mapping = json.loads(self.settings.scalepad_compliance_client_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise ScalePadReadError(
                "WAIT_SCALEPAD_COMPLIANCE_CLIENT_MAP_JSON is malformed."
            ) from exc
        if not isinstance(mapping, Mapping):
            raise ScalePadReadError(
                "WAIT_SCALEPAD_COMPLIANCE_CLIENT_MAP_JSON must be an object."
            )
        if safe_client_id not in mapping:
            raise ScalePadReadError(
                "ScalePad compliance health mapping is outside the tenant scope."
            )
        raw_provider_id = mapping[safe_client_id]
        if not isinstance(raw_provider_id, str) or not raw_provider_id.strip():
            raise ScalePadReadError(
                "ScalePad compliance health mapping must use non-empty UUID strings."
            )
        return _uuid_provider_id(raw_provider_id, "ScalePad compliance client IDs")

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "ScalePad live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SCALEPAD_BASE_URL": self.settings.scalepad_base_url,
                "WAIT_SCALEPAD_API_KEY": self.settings.scalepad_api_key,
                "WAIT_SCALEPAD_CLIENT_MAP_JSON": self.settings.scalepad_client_map_json,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ScalePad credentials are incomplete: {', '.join(missing)}.",
        )

    def _not_configured_base_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SCALEPAD_BASE_URL": self.settings.scalepad_base_url,
                "WAIT_SCALEPAD_API_KEY": self.settings.scalepad_api_key,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ScalePad credentials are incomplete: {', '.join(missing)}.",
        )

    def _not_configured_risk_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SCALEPAD_BASE_URL": self.settings.scalepad_base_url,
                "WAIT_SCALEPAD_API_KEY": self.settings.scalepad_api_key,
                "WAIT_SCALEPAD_RISK_TENANT_MAP_JSON": self.settings.scalepad_risk_tenant_map_json,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ScalePad risk-summary credentials are incomplete: {', '.join(missing)}.",
        )

    def _not_configured_lifecycle_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SCALEPAD_BASE_URL": self.settings.scalepad_base_url,
                "WAIT_SCALEPAD_API_KEY": self.settings.scalepad_api_key,
                "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON": (
                    self.settings.scalepad_lifecycle_client_map_json
                ),
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ScalePad Lifecycle credentials are incomplete: {', '.join(missing)}.",
        )

    def _not_configured_compliance_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_SCALEPAD_BASE_URL": self.settings.scalepad_base_url,
                "WAIT_SCALEPAD_API_KEY": self.settings.scalepad_api_key,
                "WAIT_SCALEPAD_COMPLIANCE_CLIENT_MAP_JSON": (
                    self.settings.scalepad_compliance_client_map_json
                ),
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"ScalePad compliance health credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> ScalePadClientResponse | None:
        result = self._blocked_result()
        return ScalePadClientResponse(result, []) if result is not None else None

    def _not_configured_response(self) -> ScalePadClientResponse | None:
        result = self._not_configured_result()
        return ScalePadClientResponse(result, []) if result is not None else None

    def _blocked_risk_response(self) -> ScalePadRiskSummaryResponse | None:
        result = self._blocked_result()
        return ScalePadRiskSummaryResponse(result, []) if result is not None else None

    def _not_configured_risk_response(self) -> ScalePadRiskSummaryResponse | None:
        result = self._not_configured_risk_result()
        return ScalePadRiskSummaryResponse(result, []) if result is not None else None

    def _blocked_goal_response(self) -> ScalePadGoalResponse | None:
        result = self._blocked_result()
        return ScalePadGoalResponse(result, []) if result is not None else None

    def _not_configured_goal_response(self) -> ScalePadGoalResponse | None:
        result = self._not_configured_lifecycle_result()
        return ScalePadGoalResponse(result, []) if result is not None else None

    def _blocked_assessment_response(self) -> ScalePadAssessmentResponse | None:
        result = self._blocked_result()
        return ScalePadAssessmentResponse(result, []) if result is not None else None

    def _not_configured_assessment_response(self) -> ScalePadAssessmentResponse | None:
        result = self._not_configured_lifecycle_result()
        return ScalePadAssessmentResponse(result, []) if result is not None else None

    def _blocked_compliance_response(self) -> ScalePadComplianceHealthResponse | None:
        result = self._blocked_result()
        return ScalePadComplianceHealthResponse(result) if result is not None else None

    def _not_configured_compliance_response(self) -> ScalePadComplianceHealthResponse | None:
        result = self._not_configured_compliance_result()
        return ScalePadComplianceHealthResponse(result) if result is not None else None


def _normalize_client(row: object, provider_id: str) -> ScalePadClientRecord | None:
    if not isinstance(row, Mapping):
        return None
    record_id = _optional_provider_id(row.get("id"))
    if record_id is None:
        return None
    if record_id != provider_id:
        return None
    return ScalePadClientRecord(
        id=record_id,
        name=_bounded_text(row.get("name")),
        lifecycle=_bounded_text(row.get("lifecycle")),
        num_contacts=_optional_nonnegative_int(row.get("num_contacts")),
        num_hardware_assets=_optional_nonnegative_int(row.get("num_hardware_assets")),
        record_created_at=_bounded_text(row.get("record_created_at")),
        record_updated_at=_bounded_text(row.get("record_updated_at")),
    )


def _normalize_risk_summary(row: object, tenant_id: str) -> dict[str, object] | None:
    if not isinstance(row, Mapping):
        return None
    client = row.get("client")
    if not isinstance(client, Mapping):
        return None
    returned_tenant_id = _optional_provider_id(client.get("tenant_id"))
    if returned_tenant_id != tenant_id:
        return None
    bounded = _bound_risk_value(row, depth=0)
    if not isinstance(bounded, dict):
        return None
    redacted = redact_value(bounded)
    return redacted if isinstance(redacted, dict) else None


def _normalize_goal(row: object, provider_id: str) -> dict[str, object] | None:
    if not isinstance(row, Mapping):
        return None
    client = row.get("client")
    if not isinstance(client, Mapping):
        return None
    returned_provider_id = _optional_provider_id(client.get("id"))
    if returned_provider_id != provider_id:
        return None
    bounded = _bound_risk_value(row, depth=0)
    if not isinstance(bounded, dict):
        return None
    redacted = redact_value(bounded)
    return redacted if isinstance(redacted, dict) else None


def _safe_client_id(value: str) -> str:
    if not isinstance(value, str):
        raise ScalePadReadError("ScalePad operations require an explicit tenant scope.")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_CLIENT_ID_LENGTH:
        raise ScalePadReadError("ScalePad operations require an explicit tenant scope.")
    return normalized


def _bounded_provider_id(value: object) -> str:
    if not isinstance(value, str):
        raise ScalePadReadError("ScalePad provider client IDs must be non-empty strings.")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_PROVIDER_ID_LENGTH:
        raise ScalePadReadError("ScalePad provider client IDs must be bounded strings.")
    if any(ord(character) < 32 for character in normalized):
        raise ScalePadReadError("ScalePad provider client IDs must not contain control characters.")
    return normalized


def _uuid_provider_id(value: str, label: str) -> str:
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise ScalePadReadError(f"{label} must be valid UUID strings.") from exc


def _optional_provider_id(value: object) -> str:
    if value is None or value == "":
        return ""
    return _bounded_provider_id(value)


def _optional_cursor(value: object) -> str:
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or len(value) > MAX_PROVIDER_ID_LENGTH:
        return ""
    if any(
        character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
        for character in value
    ):
        return ""
    return value


def _required_cursor(value: str) -> str:
    cursor = _optional_cursor(value)
    if not cursor:
        raise ScalePadReadError("ScalePad cursor must be a bounded Base64 string.")
    return cursor


def _goal_status(value: str) -> str:
    normalized = value.strip()
    if normalized not in _GOAL_STATUSES:
        raise ScalePadReadError(
            "ScalePad goal status must be one of AtRisk, Complete, OffTrack, OnHold, or OnTrack."
        )
    return normalized


def _goal_title(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized or len(normalized) > MAX_GOAL_TITLE_LENGTH:
        raise ScalePadReadError(
            "ScalePad goal title must be non-empty and at most 200 characters."
        )
    return normalized


def _assessment_status(value: str) -> str:
    normalized = value.strip()
    if normalized not in _ASSESSMENT_STATUSES:
        raise ScalePadReadError("ScalePad assessment status must be Completed or InProgress.")
    return normalized


def _assessment_template_id(value: str) -> str:
    return _bounded_provider_id(value)


def _bound_risk_value(value: object, *, depth: int) -> object:
    if depth > MAX_RISK_SUMMARY_DEPTH:
        return "[truncated]"
    if isinstance(value, Mapping):
        bounded: dict[str, object] = {}
        for raw_key, raw_value in list(value.items())[:MAX_RISK_SUMMARY_FIELDS]:
            key = _bounded_text(raw_key)
            if key:
                bounded[key] = _bound_risk_value(raw_value, depth=depth + 1)
        return bounded
    if isinstance(value, list):
        return [
            _bound_risk_value(item, depth=depth + 1)
            for item in value[:MAX_RISK_SUMMARY_LIST_ITEMS]
        ]
    if isinstance(value, str):
        return _bounded_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _bounded_text(value)


def _endpoint_url(base_url: str, endpoint: str) -> str:
    if len(base_url) > MAX_ENDPOINT_LENGTH or any(ord(character) < 32 for character in base_url):
        raise ScalePadReadError("ScalePad base URL is invalid.")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ScalePadReadError("ScalePad base URL must be an HTTPS URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ScalePadReadError("ScalePad base URL must not contain credentials or query data.")
    if endpoint not in {
        "core/v1/clients",
        "controlmap/v1/clients/risks-summary",
        "lifecycle-manager/v1/goals",
        "lifecycle-manager/v1/assessments",
    } and not (
        endpoint.startswith("controlmap/v1/clients/")
        and endpoint.endswith("/health")
        and _is_uuid_segment(endpoint[len("controlmap/v1/clients/") : -len("/health")])
    ):
        raise ScalePadReadError("ScalePad endpoint is not supported.")
    return f"{base_url.strip().rstrip('/')}/{endpoint}"


def _bounded_text(value: object) -> str:
    return " ".join(str(value).split())[:MAX_TEXT_LENGTH] if value is not None else ""


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _is_uuid_segment(value: str) -> bool:
    try:
        UUID(value)
    except (AttributeError, ValueError):
        return False
    return True


__all__ = [
    "ScalePadClient",
    "ScalePadClientRecord",
    "ScalePadClientResponse",
    "ScalePadRiskSummaryResponse",
    "ScalePadComplianceHealthResponse",
    "ScalePadGoalResponse",
    "ScalePadAssessmentResponse",
    "ScalePadReadError",
    "ScalePadReadProvider",
]
