"""Bounded TimeZest scheduling-request adapter.

TimeZest exposes a documented HTTP API for scheduling requests. WAIT uses the
documented list endpoint with one explicit local mapping per WAIT client to an
Autotask or ConnectWise PSA company identifier. The provider filter is fixed
by WAIT, returned records are checked against the mapped associated entity, and
creation is separately gated by the shared approval-aware write runtime.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

DEFAULT_LIMIT = 20
MAX_LIMIT = 20
MAX_CLIENT_ID_LENGTH = 120
MAX_ID_LENGTH = 120
MAX_TEXT_LENGTH = 500
MAX_ENTITIES = 20
MAX_RESOURCES = 20
MAX_RESOURCE_ID_LENGTH = 120
MAX_EMAIL_LENGTH = 320
MAX_URL_LENGTH = 2_000

_CLIENT_MAP_FIELDS = {
    "autotask_company_id": ("autotask/company", "id"),
    "connectwise_psa_company_id": ("connectwise_psa/company", "id"),
}


@dataclass(frozen=True)
class TimeZestSchedulingRequest:
    id: str
    appointment_type_id: str
    status: str
    duration_mins: int | None
    end_user_name: str
    selected_start_time: int | None
    selected_time_zone: str
    scheduled_at: int | None
    created_at: int | None
    updated_at: int | None
    has_scheduling_url: bool
    associated_entities: list[dict[str, object]]
    resources: list[dict[str, object]]


@dataclass(frozen=True)
class TimeZestSchedulingResponse:
    result: ConnectorReadResult
    items: list[TimeZestSchedulingRequest]
    has_more: bool = False


@dataclass(frozen=True)
class TimeZestSchedulingCreateResponse:
    result: ConnectorReadResult
    request: dict[str, object]


class TimeZestReadError(Exception):
    """Safe, operator-facing TimeZest adapter error."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TimeZestReadProvider(Protocol):
    def health(self) -> ConnectorReadResult:
        ...

    def list_scheduling_requests(
        self, *, client_id: str, limit: int = DEFAULT_LIMIT
    ) -> TimeZestSchedulingResponse:
        ...


class TimeZestWriteProvider(TimeZestReadProvider, Protocol):
    def write_health(self) -> ConnectorReadResult:
        ...

    def create_scheduling_request(
        self,
        *,
        client_id: str,
        appointment_type_id: str,
        trigger_mode: str,
        resource_ids: Sequence[str],
        duration_mins: int | None = None,
        earliest_date: str | None = None,
        earliest_time: str | None = None,
        latest_date: str | None = None,
        latest_time: str | None = None,
        end_user_name: str | None = None,
        end_user_email: str | None = None,
        end_user_company: str | None = None,
    ) -> TimeZestSchedulingCreateResponse:
        ...


class TimeZestClient:
    """Normalize the documented TimeZest scheduling-request contract."""

    def __init__(self, settings: Settings, *, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.transport = transport

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        try:
            mapping = json.loads(self.settings.timezest_client_map_json or "{}")
            if not isinstance(mapping, Mapping) or not mapping:
                raise TimeZestReadError(
                    "WAIT_TIMEZEST_CLIENT_MAP_JSON must contain at least one client mapping."
                )
            self._client_mapping(str(next(iter(mapping))))
        except TimeZestReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "TimeZest read prerequisites are ready.")

    def list_scheduling_requests(
        self, *, client_id: str, limit: int = DEFAULT_LIMIT
    ) -> TimeZestSchedulingResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        try:
            field, provider_value = self._client_mapping(client_id)
            bounded_limit = _bounded_limit(limit)
        except TimeZestReadError as exc:
            return TimeZestSchedulingResponse(ConnectorReadResult("failed", exc.message), [])

        try:
            payload = self._get(
                "v1/scheduling_requests",
                params={"filter": f"scheduling_request.{field} EQ {provider_value}"},
            )
        except TimeZestReadError as exc:
            return TimeZestSchedulingResponse(ConnectorReadResult("failed", exc.message), [])
        if isinstance(payload, TimeZestSchedulingResponse):
            return payload
        if not isinstance(payload, Mapping):
            return TimeZestSchedulingResponse(
                ConnectorReadResult("failed", "TimeZest returned a malformed response object."),
                [],
            )
        response_payload: Mapping[str, object] = payload
        rows = response_payload.get("data")
        if not isinstance(rows, list):
            return TimeZestSchedulingResponse(
                ConnectorReadResult("failed", "TimeZest returned malformed scheduling-request data."),
                [],
            )
        items = []
        for row in rows:
            normalized = _normalize_request(row, field, provider_value)
            if normalized is not None:
                items.append(normalized)
            if len(items) >= bounded_limit:
                break
        next_page = response_payload.get("next_page")
        has_more = isinstance(next_page, str) and bool(next_page.strip())
        return TimeZestSchedulingResponse(
            ConnectorReadResult("ready", "TimeZest scheduling-request read succeeded.", len(items)),
            items,
            has_more,
        )

    def write_health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult(
                "blocked",
                "TimeZest writes are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
            )
        if not self.settings.allow_write_actions:
            return ConnectorReadResult(
                "blocked",
                "TimeZest writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true.",
            )
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        try:
            mapping = json.loads(self.settings.timezest_client_map_json or "{}")
            if not isinstance(mapping, Mapping) or not mapping:
                raise TimeZestReadError(
                    "WAIT_TIMEZEST_CLIENT_MAP_JSON must contain at least one client mapping."
                )
            self._client_mapping(str(next(iter(mapping))))
        except (TimeZestReadError, StopIteration, TypeError, json.JSONDecodeError) as exc:
            if isinstance(exc, TimeZestReadError):
                return ConnectorReadResult("failed", exc.message)
            return ConnectorReadResult(
                "failed",
                "WAIT_TIMEZEST_CLIENT_MAP_JSON must contain a valid client mapping.",
            )
        return ConnectorReadResult("ready", "TimeZest write prerequisites are ready.")

    def create_scheduling_request(
        self,
        *,
        client_id: str,
        appointment_type_id: str,
        trigger_mode: str,
        resource_ids: Sequence[str],
        duration_mins: int | None = None,
        earliest_date: str | None = None,
        earliest_time: str | None = None,
        latest_date: str | None = None,
        latest_time: str | None = None,
        end_user_name: str | None = None,
        end_user_email: str | None = None,
        end_user_company: str | None = None,
    ) -> TimeZestSchedulingCreateResponse:
        health = self.write_health()
        if health.status != "ready":
            return TimeZestSchedulingCreateResponse(health, {})
        try:
            _validate_create_fields(
                appointment_type_id=appointment_type_id,
                trigger_mode=trigger_mode,
                resource_ids=resource_ids,
                duration_mins=duration_mins,
                earliest_date=earliest_date,
                earliest_time=earliest_time,
                latest_date=latest_date,
                latest_time=latest_time,
                end_user_name=end_user_name,
                end_user_email=end_user_email,
                end_user_company=end_user_company,
            )
            field, provider_value = self._client_mapping(client_id)
            entity_type, _ = _CLIENT_MAP_FIELDS[field]
            request_payload: dict[str, object] = {
                "appointment_type_id": appointment_type_id.strip(),
                "trigger_mode": trigger_mode,
                "associated_entities": [{"type": entity_type, "id": provider_value}],
                "resource_ids": [item.strip() for item in resource_ids],
            }
            for key, value in (
                ("duration_mins", duration_mins),
                ("earliest_date", earliest_date),
                ("earliest_time", earliest_time),
                ("latest_date", latest_date),
                ("latest_time", latest_time),
                ("end_user_name", end_user_name),
                ("end_user_email", end_user_email),
                ("end_user_company", end_user_company),
            ):
                if value is not None:
                    request_payload[key] = value
        except TimeZestReadError as exc:
            return TimeZestSchedulingCreateResponse(
                ConnectorReadResult("failed", exc.message),
                {},
            )
        try:
            response_payload = self._post("v1/scheduling_requests", json_body=request_payload)
        except TimeZestReadError as exc:
            return TimeZestSchedulingCreateResponse(ConnectorReadResult("failed", exc.message), {})
        if not isinstance(response_payload, Mapping):
            return TimeZestSchedulingCreateResponse(
                ConnectorReadResult(
                    "failed", "TimeZest returned a malformed scheduling-request response."
                ),
                {},
            )
        normalized = _normalize_created_request(response_payload)
        if normalized is None:
            return TimeZestSchedulingCreateResponse(
                ConnectorReadResult(
                    "failed", "TimeZest returned an invalid scheduling-request response."
                ),
                {},
            )
        return TimeZestSchedulingCreateResponse(
            ConnectorReadResult("ready", "TimeZest scheduling-request creation succeeded.", 1),
            normalized,
        )

    def _get(self, endpoint: str, *, params: Mapping[str, str] | None = None) -> object:
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, *, json_body: Mapping[str, object]) -> object:
        if not self.settings.allow_write_actions:
            raise TimeZestReadError(
                "TimeZest writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        return self._request("POST", endpoint, json_body=json_body)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: Mapping[str, object] | None = None,
    ) -> object:
        if not self.settings.allow_http_probing:
            raise TimeZestReadError(
                "TimeZest live requests are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        missing = self._not_configured_result()
        if missing is not None:
            raise TimeZestReadError(missing.message)
        url = _endpoint_url(self.settings.timezest_base_url, endpoint)
        try:
            with httpx.Client(
                timeout=self.settings.connector_timeout_seconds,
                transport=self.transport,
            ) as client:
                headers = {
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.settings.timezest_api_key.strip()}",
                }
                if method == "GET":
                    response = client.get(url, headers=headers, params=params)
                elif method == "POST":
                    response = client.post(
                        url,
                        headers={**headers, "Content-Type": "application/json"},
                        json=json_body,
                    )
                else:
                    raise TimeZestReadError("TimeZest HTTP method is not supported.")
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise TimeZestReadError("TimeZest request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise TimeZestReadError("TimeZest request failed.") from exc
        if response.status_code in {401, 403}:
            raise TimeZestReadError("TimeZest request was unauthorized.")
        if response.status_code == 429:
            raise TimeZestReadError("TimeZest request was rate limited.")
        if response.status_code >= 400:
            raise TimeZestReadError(f"TimeZest request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise TimeZestReadError("TimeZest returned malformed JSON.") from exc
        if not isinstance(payload, Mapping):
            raise TimeZestReadError("TimeZest returned a malformed response object.")
        return payload

    def _client_mapping(self, client_id: str) -> tuple[str, int]:
        safe_client_id = _safe_client_id(client_id)
        try:
            mapping = json.loads(self.settings.timezest_client_map_json or "{}")
        except json.JSONDecodeError as exc:
            raise TimeZestReadError("WAIT_TIMEZEST_CLIENT_MAP_JSON is malformed.") from exc
        if not isinstance(mapping, Mapping):
            raise TimeZestReadError("WAIT_TIMEZEST_CLIENT_MAP_JSON must be an object.")
        raw_mapping = mapping.get(safe_client_id)
        if raw_mapping is None:
            raise TimeZestReadError("TimeZest client mapping is outside the tenant scope.")
        if not isinstance(raw_mapping, Mapping) or len(raw_mapping) != 1:
            raise TimeZestReadError("TimeZest client mapping must contain one supported company ID.")
        field, raw_value = next(iter(raw_mapping.items()))
        if field not in _CLIENT_MAP_FIELDS or isinstance(raw_value, bool):
            raise TimeZestReadError("TimeZest client mapping uses an unsupported company ID field.")
        try:
            provider_value = int(str(raw_value))
        except (TypeError, ValueError) as exc:
            raise TimeZestReadError("TimeZest company IDs must be positive integers.") from exc
        if provider_value <= 0 or provider_value > 2_147_483_647:
            raise TimeZestReadError("TimeZest company IDs must be positive integers.")
        return field, provider_value

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "TimeZest live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_TIMEZEST_BASE_URL": self.settings.timezest_base_url,
                "WAIT_TIMEZEST_API_KEY": self.settings.timezest_api_key,
                "WAIT_TIMEZEST_CLIENT_MAP_JSON": self.settings.timezest_client_map_json,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"TimeZest credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> TimeZestSchedulingResponse | None:
        result = self._blocked_result()
        return TimeZestSchedulingResponse(result, []) if result is not None else None

    def _not_configured_response(self) -> TimeZestSchedulingResponse | None:
        result = self._not_configured_result()
        return TimeZestSchedulingResponse(result, []) if result is not None else None


def _normalize_request(
    row: object,
    field: str,
    provider_value: int,
) -> TimeZestSchedulingRequest | None:
    if not isinstance(row, Mapping):
        return None
    request_id = _bounded_text(row.get("id"))
    if not request_id or len(request_id) > MAX_ID_LENGTH:
        return None
    expected_type, expected_key = _CLIENT_MAP_FIELDS[field]
    entities = _normalize_entities(row.get("associated_entities"))
    if not any(
        entity.get("type") == expected_type and entity.get(expected_key) == provider_value
        for entity in entities
    ):
        return None
    return TimeZestSchedulingRequest(
        id=request_id,
        appointment_type_id=_bounded_text(row.get("appointment_type_id")),
        status=_bounded_text(row.get("status")),
        duration_mins=_positive_int(row.get("duration_mins")),
        end_user_name=_bounded_text(row.get("end_user_name")),
        selected_start_time=_optional_int(row.get("selected_start_time")),
        selected_time_zone=_bounded_text(row.get("selected_time_zone")),
        scheduled_at=_optional_int(row.get("scheduled_at")),
        created_at=_optional_int(row.get("created_at")),
        updated_at=_optional_int(row.get("updated_at")),
        has_scheduling_url=bool(_bounded_text(row.get("scheduling_url"))),
        associated_entities=entities,
        resources=_normalize_entities(row.get("resources"), limit=MAX_RESOURCES),
    )


def _normalize_entities(value: object, *, limit: int = MAX_ENTITIES) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    entities: list[dict[str, object]] = []
    for item in value[:limit]:
        if not isinstance(item, Mapping):
            continue
        normalized: dict[str, object] = {}
        for key in ("type", "id", "number", "name"):
            if key not in item:
                continue
            if key == "id":
                parsed_id = _positive_int(item[key])
                if parsed_id is not None:
                    normalized[key] = parsed_id
            else:
                text = _bounded_text(item[key])
                if text:
                    normalized[key] = text
        if normalized:
            entities.append(normalized)
    return entities


def _safe_client_id(value: str) -> str:
    if not isinstance(value, str):
        raise TimeZestReadError("TimeZest operations require an explicit tenant scope.")
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_CLIENT_ID_LENGTH:
        raise TimeZestReadError("TimeZest operations require an explicit tenant scope.")
    return normalized


def _bounded_limit(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_LIMIT:
        raise TimeZestReadError(f"TimeZest limit must be an integer between 1 and {MAX_LIMIT}.")
    return value


def _endpoint_url(base_url: str, endpoint: str) -> str:
    if any(ord(character) < 32 for character in base_url):
        raise TimeZestReadError("TimeZest base URL contains control characters.")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise TimeZestReadError("TimeZest base URL must be an HTTP(S) URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise TimeZestReadError("TimeZest base URL must not contain credentials or query data.")
    if endpoint not in {"v1/scheduling_requests"}:
        raise TimeZestReadError("TimeZest endpoint is not supported.")
    return f"{base_url.strip().rstrip('/')}/{endpoint}"


def _validate_create_fields(
    *,
    appointment_type_id: str,
    trigger_mode: str,
    resource_ids: Sequence[str],
    duration_mins: int | None,
    earliest_date: str | None,
    earliest_time: str | None,
    latest_date: str | None,
    latest_time: str | None,
    end_user_name: str | None,
    end_user_email: str | None,
    end_user_company: str | None,
) -> None:
    _required_text(appointment_type_id, "appointment_type_id", MAX_ID_LENGTH)
    if trigger_mode not in {"pod", "generate_url"}:
        raise TimeZestReadError("trigger_mode must be pod or generate_url.")
    if isinstance(resource_ids, (str, bytes)) or not isinstance(resource_ids, Sequence):
        raise TimeZestReadError("resource_ids must be a non-empty array.")
    if not 1 <= len(resource_ids) <= MAX_RESOURCES:
        raise TimeZestReadError(f"resource_ids must contain between 1 and {MAX_RESOURCES} items.")
    normalized_resources: set[str] = set()
    for resource_id in resource_ids:
        normalized = _required_text(resource_id, "resource_id", MAX_RESOURCE_ID_LENGTH)
        if normalized in normalized_resources:
            raise TimeZestReadError("resource_ids must not contain duplicates.")
        normalized_resources.add(normalized)
    if duration_mins is not None and (
        isinstance(duration_mins, bool)
        or not isinstance(duration_mins, int)
        or not 1 <= duration_mins <= 1_440
    ):
        raise TimeZestReadError("duration_mins must be an integer between 1 and 1440.")
    _optional_date(earliest_date, "earliest_date")
    _optional_date(latest_date, "latest_date")
    _optional_time(earliest_time, "earliest_time")
    _optional_time(latest_time, "latest_time")
    if earliest_date and latest_date and earliest_date > latest_date:
        raise TimeZestReadError("earliest_date must not be after latest_date.")
    if end_user_name is not None:
        _required_text(end_user_name, "end_user_name", MAX_TEXT_LENGTH)
    if end_user_email is not None:
        email = _required_text(end_user_email, "end_user_email", MAX_EMAIL_LENGTH)
        if email.count("@") != 1 or any(character.isspace() for character in email):
            raise TimeZestReadError("end_user_email must be a valid email address.")
    if end_user_company is not None:
        _required_text(end_user_company, "end_user_company", MAX_TEXT_LENGTH)


def _required_text(value: object, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise TimeZestReadError(
            f"{name} must be a non-empty string of at most {maximum} characters."
        )
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized if character not in "\r\n\t"):
        raise TimeZestReadError(f"{name} contains control characters.")
    return normalized


def _optional_date(value: str | None, name: str) -> None:
    if value is None:
        return
    normalized = _required_text(value, name, 10)
    try:
        parsed = date.fromisoformat(normalized)
    except ValueError as exc:
        raise TimeZestReadError(f"{name} must use YYYY-MM-DD format.") from exc
    if parsed.isoformat() != normalized:
        raise TimeZestReadError(f"{name} must use YYYY-MM-DD format.")


def _optional_time(value: str | None, name: str) -> None:
    if value is None:
        return
    normalized = _required_text(value, name, 8)
    try:
        parsed = time.fromisoformat(normalized)
    except ValueError as exc:
        raise TimeZestReadError(f"{name} must use HH:MM:SS format.") from exc
    if parsed.isoformat(timespec="seconds") != normalized:
        raise TimeZestReadError(f"{name} must use HH:MM:SS format.")


def _normalize_created_request(row: Mapping[str, object]) -> dict[str, object] | None:
    if row.get("object") != "scheduling_request":
        return None
    request_id = _bounded_text(row.get("id"))
    if not request_id or len(request_id) > MAX_ID_LENGTH:
        return None
    return {
        "id": request_id,
        "appointment_type_id": _bounded_text(row.get("appointment_type_id")),
        "status": _bounded_text(row.get("status")),
        "duration_mins": _positive_int(row.get("duration_mins")),
        "earliest_date": _bounded_text(row.get("earliest_date")),
        "earliest_time": _bounded_text(row.get("earliest_time")),
        "latest_date": _bounded_text(row.get("latest_date")),
        "latest_time": _bounded_text(row.get("latest_time")),
        "scheduling_url": _safe_scheduling_url(row.get("scheduling_url")),
        "associated_entities": _normalize_entities(row.get("associated_entities")),
        "resources": _normalize_entities(row.get("resources"), limit=MAX_RESOURCES),
        "created_at": _optional_int(row.get("created_at")),
        "updated_at": _optional_int(row.get("updated_at")),
    }


def _safe_scheduling_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > MAX_URL_LENGTH:
        return ""
    normalized = value.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    if any(ord(character) < 32 for character in normalized):
        return ""
    return normalized


def _bounded_text(value: object) -> str:
    return " ".join(str(value).split())[:MAX_TEXT_LENGTH] if value is not None else ""


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return _positive_int(value)


__all__ = [
    "TimeZestClient",
    "TimeZestReadError",
    "TimeZestReadProvider",
    "TimeZestSchedulingCreateResponse",
    "TimeZestSchedulingRequest",
    "TimeZestSchedulingResponse",
    "TimeZestWriteProvider",
]
