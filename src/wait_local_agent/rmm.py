"""RMM contracts and bounded vendor adapters.

Inventory remains read-first. Script execution is the one supported mutation,
and it is only reachable through an approval request and the write-action
safety gate. Datto RMM is intentionally read-only in this release.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.models import ConnectorReadResult

RmmItem = dict[str, object]
RmmNormalizer = Callable[[Mapping[str, object]], RmmItem | None]


@dataclass(frozen=True)
class RmmReadResponse:
    result: ConnectorReadResult
    items: list[RmmItem]


@dataclass(frozen=True)
class RmmExecutionResult:
    status: str
    message: str
    device_id: str
    script_id: str
    status_code: int | None = None
    remote_id: str = ""


class RmmReadError(Exception):
    """A sanitized RMM adapter failure."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class RmmClient(Protocol):
    """Read-first contract shared by future RMM vendor adapters."""

    def health(self) -> ConnectorReadResult: ...

    def list_devices(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse: ...

    def get_device(self, device_id: str) -> RmmReadResponse: ...

    def list_alerts(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse: ...

    def list_scripts(self) -> RmmReadResponse: ...

    def preview_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
    ) -> RmmReadResponse: ...

    def execute_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
        run_as: str = "",
    ) -> RmmExecutionResult: ...


class RmmExecutionClient(Protocol):
    def execute_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
        run_as: str = "",
    ) -> RmmExecutionResult: ...


class NinjaOneClient:
    """Small NinjaOne Public API adapter with one approval-gated mutation."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self._cached_token: str | None = None
        self._cached_token_expires_at = 0.0

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        try:
            self._access_token()
        except RmmReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "NinjaOne monitoring token request succeeded.")

    def list_devices(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        params: dict[str, str | int] = {"pageSize": _bounded_page_size(page_size or self.settings.ninjaone_page_size)}
        if after:
            params["after"] = after
        return self._list("devices", _normalize_device, params=params)

    def get_device(self, device_id: str) -> RmmReadResponse:
        return self._single(f"device/{_safe_segment(device_id)}", _normalize_device)

    def list_alerts(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        params: dict[str, str | int] = {"pageSize": _bounded_page_size(page_size or self.settings.ninjaone_page_size)}
        if after:
            params["after"] = after
        return self._list("alerts", _normalize_alert, params=params)

    def list_scripts(self) -> RmmReadResponse:
        return self._list("automation/scripts", _normalize_script)

    def preview_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
    ) -> RmmReadResponse:
        """Return a redacted execution proposal without calling a write endpoint."""

        try:
            normalized_device_id = _safe_segment(device_id)
            normalized_script_id = _safe_segment(script_id)
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        variable_names = sorted(key for key in (variables or {}) if isinstance(key, str) and key.strip())
        return RmmReadResponse(
            ConnectorReadResult(
                "ready",
                "NinjaOne script execution preview created; no script was executed.",
            ),
            [
                {
                    "device_id": normalized_device_id,
                    "script_id": normalized_script_id,
                    "operation": "script.run",
                    "approval_required": True,
                    "execution_enabled": False,
                    "variable_names": variable_names,
                }
            ],
        )

    def execute_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
        run_as: str = "",
    ) -> RmmExecutionResult:
        """Run one script after the caller has completed approval checks."""

        if not self.settings.allow_http_probing:
            return RmmExecutionResult(
                "blocked",
                "NinjaOne script execution is blocked until WAIT_ALLOW_HTTP_PROBING=true.",
                device_id,
                script_id,
            )
        if not self.settings.allow_write_actions:
            return RmmExecutionResult(
                "blocked",
                "NinjaOne script execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true.",
                device_id,
                script_id,
            )
        try:
            normalized_device_id = _safe_segment(device_id)
            normalized_script_id = _numeric_script_id(script_id)
            normalized_run_as = _safe_run_as(run_as)
            parameters = _script_parameters(variables)
            token = self._access_token()
            with self._client() as client:
                response = client.post(
                    f"{_api_base_url(self.settings.ninjaone_base_url)}/device/{normalized_device_id}/script/run",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    json={
                        "type": "SCRIPT",
                        "id": normalized_script_id,
                        "parameters": parameters,
                        "runAs": normalized_run_as,
                    },
                )
        except RmmReadError as exc:
            return RmmExecutionResult("failed", exc.message, device_id, script_id)
        except (httpx.TimeoutException, httpx.ConnectError):
            return RmmExecutionResult(
                "failed", "NinjaOne script request failed before receiving a response.", device_id, script_id
            )
        except httpx.HTTPError:
            return RmmExecutionResult("failed", "NinjaOne script request failed.", device_id, script_id)

        if response.status_code >= 400:
            return RmmExecutionResult(
                "failed",
                f"NinjaOne script execution failed with HTTP {response.status_code}.",
                device_id,
                script_id,
                response.status_code,
            )
        remote_id = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            for key in ("jobId", "job_id", "id", "uid"):
                if payload.get(key) not in (None, ""):
                    remote_id = str(payload[key])
                    break
        return RmmExecutionResult(
            "succeeded",
            "NinjaOne script execution accepted.",
            device_id,
            script_id,
            response.status_code,
            remote_id,
        )

    def _list(
        self,
        endpoint: str,
        normalizer: RmmNormalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> RmmReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        return self._request_items(endpoint, normalizer, params=params)

    def _single(self, endpoint: str, normalizer: RmmNormalizer) -> RmmReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        return self._request_items(endpoint, normalizer)

    def _request_items(
        self,
        endpoint: str,
        normalizer: RmmNormalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> RmmReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return RmmReadResponse(
            ConnectorReadResult("ready", f"NinjaOne read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        token = self._access_token()
        try:
            with self._client() as client:
                response = client.get(
                    f"{_api_base_url(self.settings.ninjaone_base_url)}/{_safe_endpoint(endpoint)}",
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise RmmReadError("NinjaOne request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise RmmReadError("NinjaOne request failed.") from exc
        if response.status_code >= 400:
            raise RmmReadError(f"NinjaOne GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise RmmReadError(f"NinjaOne GET {endpoint} returned malformed JSON.") from exc

    def _access_token(self) -> str:
        now = monotonic()
        if self._cached_token and now < self._cached_token_expires_at:
            return self._cached_token
        missing = self._not_configured_result()
        if missing is not None:
            raise RmmReadError(missing.message)
        try:
            with self._client() as client:
                response = client.post(
                    _token_url(self.settings.ninjaone_base_url),
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.settings.ninjaone_client_id,
                        "client_secret": self.settings.ninjaone_client_secret,
                        "scope": self.settings.ninjaone_scope,
                    },
                    headers={"Accept": "application/json"},
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise RmmReadError("NinjaOne token request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise RmmReadError("NinjaOne token request failed.") from exc
        if response.status_code >= 400:
            raise RmmReadError(f"NinjaOne token request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RmmReadError("NinjaOne token response was malformed JSON.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RmmReadError("NinjaOne token response did not contain an access token.")
        expires_in = payload.get("expires_in", 3600)
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            expires_in = 3600
        self._cached_token = payload["access_token"]
        self._cached_token_expires_at = now + max(float(expires_in) - 30.0, 1.0)
        return self._cached_token

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport)

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "NinjaOne live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_NINJAONE_BASE_URL": self.settings.ninjaone_base_url,
                "WAIT_NINJAONE_CLIENT_ID": self.settings.ninjaone_client_id,
                "WAIT_NINJAONE_CLIENT_SECRET": self.settings.ninjaone_client_secret,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"NinjaOne credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> RmmReadResponse | None:
        blocked = self._blocked_result()
        return RmmReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> RmmReadResponse | None:
        missing = self._not_configured_result()
        return RmmReadResponse(missing, []) if missing else None


class DattoRmmClient:
    """Read-only Datto RMM API v2 adapter.

    The Datto API exposes component metadata that can be used to build a safe
    execution preview, but this slice deliberately does not call quick-job or
    other mutation endpoints.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self._cached_token: str | None = None
        self._cached_token_expires_at = 0.0

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        try:
            self._access_token()
        except RmmReadError as exc:
            return ConnectorReadResult("failed", exc.message)
        return ConnectorReadResult("ready", "Datto RMM API token request succeeded.")

    def list_devices(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        return self._list(
            "v2/account/devices",
            _normalize_datto_device,
            page_size=page_size,
            after=after,
        )

    def get_device(self, device_id: str) -> RmmReadResponse:
        try:
            endpoint = f"v2/device/{_safe_segment(device_id, vendor='Datto RMM')}"
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._guarded_request(endpoint, _normalize_datto_device)

    def list_alerts(self, *, page_size: int | None = None, after: str | None = None) -> RmmReadResponse:
        return self._list(
            "v2/account/alerts/open",
            _normalize_datto_alert,
            page_size=page_size,
            after=after,
        )

    def list_scripts(self) -> RmmReadResponse:
        return self._guarded_request(
            "v2/account/components",
            _normalize_datto_script,
            params={"max": _bounded_page_size(self.settings.dattormm_page_size)},
        )

    def preview_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
    ) -> RmmReadResponse:
        try:
            normalized_device_id = _safe_segment(device_id, vendor="Datto RMM")
            normalized_script_id = _safe_segment(script_id, vendor="Datto RMM")
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        variable_names = sorted(key for key in (variables or {}) if isinstance(key, str) and key.strip())
        return RmmReadResponse(
            ConnectorReadResult(
                "ready",
                "Datto RMM component preview created; no component was executed.",
            ),
            [
                {
                    "connector": "dattormm",
                    "device_id": normalized_device_id,
                    "script_id": normalized_script_id,
                    "operation": "component.run",
                    "approval_required": True,
                    "execution_enabled": False,
                    "variable_names": variable_names,
                }
            ],
        )

    def execute_script(
        self,
        device_id: str,
        script_id: str,
        variables: Mapping[str, object] | None = None,
        run_as: str = "",
    ) -> RmmExecutionResult:
        del variables, run_as
        return RmmExecutionResult(
            "blocked",
            "Datto RMM component execution is not available; this adapter is read-only.",
            device_id,
            script_id,
        )

    def _list(
        self,
        endpoint: str,
        normalizer: RmmNormalizer,
        *,
        page_size: int | None,
        after: str | None,
    ) -> RmmReadResponse:
        try:
            params: dict[str, str | int] = {
                "max": _bounded_page_size(page_size if page_size is not None else self.settings.dattormm_page_size)
            }
            if after:
                params["page"] = _positive_page(after)
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        return self._guarded_request(endpoint, normalizer, params=params)

    def _guarded_request(
        self,
        endpoint: str,
        normalizer: RmmNormalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> RmmReadResponse:
        blocked = self._blocked_response()
        if blocked is not None:
            return blocked
        missing = self._not_configured_response()
        if missing is not None:
            return missing
        return self._request_items(endpoint, normalizer, params=params)

    def _request_items(
        self,
        endpoint: str,
        normalizer: RmmNormalizer,
        *,
        params: dict[str, str | int] | None = None,
    ) -> RmmReadResponse:
        try:
            payload = self._get(endpoint, params=params)
        except RmmReadError as exc:
            return RmmReadResponse(ConnectorReadResult("failed", exc.message), [])
        items = [item for row in _payload_rows(payload) if (item := normalizer(row)) is not None]
        return RmmReadResponse(
            ConnectorReadResult("ready", f"Datto RMM read succeeded from {endpoint}.", len(items)),
            items,
        )

    def _get(self, endpoint: str, *, params: dict[str, str | int] | None = None) -> object:
        token = self._access_token()
        try:
            with self._client() as client:
                response = client.get(
                    (
                        f"{_datto_api_base_url(self.settings.dattormm_base_url)}/"
                        f"{_safe_endpoint(endpoint, vendor='Datto RMM')}"
                    ),
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    params=params,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise RmmReadError("Datto RMM request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise RmmReadError("Datto RMM request failed.") from exc
        if response.status_code >= 400:
            raise RmmReadError(f"Datto RMM GET {endpoint} failed with HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise RmmReadError(f"Datto RMM GET {endpoint} returned malformed JSON.") from exc

    def _access_token(self) -> str:
        now = monotonic()
        if self._cached_token and now < self._cached_token_expires_at:
            return self._cached_token
        missing = self._not_configured_result()
        if missing is not None:
            raise RmmReadError(missing.message)
        try:
            with self._client() as client:
                response = client.post(
                    _datto_token_url(self.settings.dattormm_base_url),
                    data={
                        "grant_type": "password",
                        "username": self.settings.dattormm_api_key,
                        "password": self.settings.dattormm_api_secret,
                    },
                    auth=("public-client", "public"),
                    headers={"Accept": "application/json"},
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise RmmReadError("Datto RMM token request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise RmmReadError("Datto RMM token request failed.") from exc
        if response.status_code >= 400:
            raise RmmReadError(f"Datto RMM token request failed with HTTP {response.status_code}.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RmmReadError("Datto RMM token response was malformed JSON.") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise RmmReadError("Datto RMM token response did not contain an access token.")
        expires_in = payload.get("expires_in", 100 * 60 * 60)
        if not isinstance(expires_in, (int, float)) or expires_in <= 0:
            expires_in = 100 * 60 * 60
        self._cached_token = payload["access_token"]
        self._cached_token_expires_at = now + max(float(expires_in) - 30.0, 1.0)
        return self._cached_token

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport)

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Datto RMM live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        missing = [
            key
            for key, value in {
                "WAIT_DATTORMM_BASE_URL": self.settings.dattormm_base_url,
                "WAIT_DATTORMM_API_KEY": self.settings.dattormm_api_key,
                "WAIT_DATTORMM_API_SECRET": self.settings.dattormm_api_secret,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"Datto RMM credentials are incomplete: {', '.join(missing)}.",
        )

    def _blocked_response(self) -> RmmReadResponse | None:
        blocked = self._blocked_result()
        return RmmReadResponse(blocked, []) if blocked else None

    def _not_configured_response(self) -> RmmReadResponse | None:
        missing = self._not_configured_result()
        return RmmReadResponse(missing, []) if missing else None


def _api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    if stripped.endswith("/api/v2") or stripped.endswith("/v2"):
        return stripped
    if stripped.endswith("/api"):
        return f"{stripped}/v2"
    return f"{stripped}/api/v2"


def _token_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    for suffix in ("/api/v2", "/api", "/v2"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return f"{stripped}/ws/oauth/token"


def _datto_api_base_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    for suffix in ("/api/v2", "/api", "/v2"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return f"{stripped}/api"


def _datto_token_url(base_url: str) -> str:
    stripped = base_url.rstrip("/")
    for suffix in ("/api/v2", "/api", "/v2"):
        if stripped.endswith(suffix):
            stripped = stripped[: -len(suffix)]
            break
    return f"{stripped}/auth/oauth/token"


def _safe_endpoint(endpoint: str, *, vendor: str = "NinjaOne") -> str:
    if "://" in endpoint or endpoint.startswith("//"):
        raise RmmReadError(f"{vendor} endpoint overrides must be relative paths.")
    return endpoint.strip("/")


def _safe_segment(value: str, *, vendor: str = "NinjaOne") -> str:
    stripped = value.strip()
    if not stripped or any(character in stripped for character in "/?#"):
        raise RmmReadError(f"{vendor} resource identifiers must be single path segments.")
    return stripped


def _positive_page(value: str) -> int:
    stripped = value.strip()
    if not stripped.isdecimal() or int(stripped) < 1:
        raise RmmReadError("Datto RMM page cursors must be positive integers.")
    return int(stripped)


def _numeric_script_id(value: str) -> int:
    stripped = value.strip()
    if not stripped.isdecimal() or int(stripped) <= 0:
        raise RmmReadError("NinjaOne script identifiers must be positive numeric IDs.")
    return int(stripped)


def _safe_run_as(value: str) -> str:
    if len(value) > 200 or any(character in value for character in "\r\n"):
        raise RmmReadError("NinjaOne runAs must be a bounded single-line value.")
    return value.strip()


def _script_parameters(variables: Mapping[str, object] | None) -> str:
    values = dict(variables or {})
    if len(values) > 50:
        raise RmmReadError("NinjaOne script variables are limited to 50 entries.")
    try:
        encoded = json.dumps(values, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RmmReadError("NinjaOne script variables must be JSON serializable.") from exc
    if len(encoded.encode("utf-8")) > 16_384:
        raise RmmReadError("NinjaOne script variables exceed the 16 KiB limit.")
    return encoded


def _bounded_page_size(value: int) -> int:
    return max(1, min(value, 100))


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    candidates: list[object]
    if isinstance(payload, list):
        candidates = payload
    elif isinstance(payload, dict):
        candidates = []
        found_list = False
        for key in ("data", "results", "devices", "alerts", "scripts", "automationScripts", "components"):
            value = payload.get(key)
            if isinstance(value, list):
                candidates = value
                found_list = True
                break
        if not found_list:
            candidates = [payload]
    else:
        return []
    return [row for row in candidates if isinstance(row, dict)]


def _normalize_device(row: Mapping[str, object]) -> RmmItem | None:
    device_id = _first_value(row, "id", "deviceId", "device_id")
    if device_id in (None, ""):
        return None
    return {
        "id": str(device_id),
        "organization_id": _string_value(row, "organizationId", "organization_id"),
        "location_id": _string_value(row, "locationId", "location_id"),
        "display_name": _string_value(row, "displayName", "display_name", "systemName", "system_name"),
        "system_name": _string_value(row, "systemName", "system_name"),
        "node_class": _string_value(row, "nodeClass", "node_class"),
        "offline": _bool_value(row, "offline"),
        "approval_status": _string_value(row, "approvalStatus", "approval_status"),
        "last_contact": _string_value(row, "lastContact", "last_contact"),
    }


def _normalize_alert(row: Mapping[str, object]) -> RmmItem | None:
    alert_id = _first_value(row, "uid", "id", "alertId", "alert_id")
    if alert_id in (None, ""):
        return None
    return {
        "id": str(alert_id),
        "device_id": _string_value(row, "deviceId", "device_id"),
        "organization_id": _string_value(row, "organizationId", "organization_id"),
        "severity": _string_value(row, "severity", "priority"),
        "message": _string_value(row, "message", "condition", "description"),
        "created_at": _string_value(row, "created", "createdAt", "created_at"),
    }


def _normalize_script(row: Mapping[str, object]) -> RmmItem | None:
    script_id = _first_value(row, "id", "scriptId", "script_id")
    if script_id in (None, ""):
        return None
    return {
        "id": str(script_id),
        "name": _string_value(row, "name", "displayName", "display_name"),
        "language": _string_value(row, "language"),
        "type": _string_value(row, "type", "scriptType", "script_type"),
    }


def _normalize_datto_device(row: Mapping[str, object]) -> RmmItem | None:
    device_id = _first_value(row, "uid", "deviceUid", "id", "deviceId")
    if device_id in (None, ""):
        return None
    offline = _bool_value(row, "offline")
    if "offline" not in row and "online" in row:
        offline = not _bool_value(row, "online")
    return {
        "id": str(device_id),
        "organization_id": _string_value(row, "siteUid", "siteId", "site_id", "accountUid"),
        "location_id": _string_value(row, "siteUid", "siteId", "site_id"),
        "display_name": _string_value(row, "hostname", "deviceName", "name", "displayName"),
        "system_name": _string_value(row, "hostname", "systemName", "system_name"),
        "node_class": _string_value(row, "deviceType", "device_type", "platform"),
        "offline": offline,
        "approval_status": _string_value(row, "status", "deviceStatus", "approvalStatus"),
        "last_contact": _string_value(row, "lastSeen", "lastContact", "last_contact"),
    }


def _normalize_datto_alert(row: Mapping[str, object]) -> RmmItem | None:
    alert_id = _first_value(row, "uid", "alertUid", "id", "alertId")
    if alert_id in (None, ""):
        return None
    return {
        "id": str(alert_id),
        "device_id": _string_value(row, "deviceUid", "deviceId", "device_id"),
        "organization_id": _string_value(row, "siteUid", "siteId", "site_id"),
        "severity": _string_value(row, "priority", "severity", "alertType"),
        "message": _string_value(row, "subject", "message", "condition", "description"),
        "created_at": _string_value(row, "opened", "created", "createdAt", "created_at"),
    }


def _normalize_datto_script(row: Mapping[str, object]) -> RmmItem | None:
    script_id = _first_value(row, "uid", "componentUid", "id", "componentId")
    if script_id in (None, ""):
        return None
    return {
        "id": str(script_id),
        "name": _string_value(row, "name", "componentName", "displayName", "display_name"),
        "language": _string_value(row, "language", "componentType"),
        "type": _string_value(row, "type", "componentType", "category"),
    }


def _first_value(row: Mapping[str, object], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _string_value(row: Mapping[str, object], *keys: str) -> str:
    value = _first_value(row, *keys)
    return "" if value is None else str(value)


def _bool_value(row: Mapping[str, object], *keys: str) -> bool:
    value = _first_value(row, *keys)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value) if value is not None else False
