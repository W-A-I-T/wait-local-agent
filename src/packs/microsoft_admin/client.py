"""SSRF-safe, allowlisted Microsoft Graph read client."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.m365_auth import (
    M365AuthFailure,
    M365Connection,
    M365ConnectionResolver,
    M365ProfileResolutionError,
    env_connection,
)
from wait_local_agent.models import ConnectorReadResult
from wait_local_agent.net_security import NetSecurityError, build_pinned_client, validate_operator_url

from .models import (
    _ALLOWED_CURSOR_KEYS,
    _ENDPOINTS,
    DEFAULT_PAGE_SIZE,
    MAX_CURSOR_LENGTH,
    MAX_IDENTITY_LENGTH,
    MAX_PAGE_SIZE,
    MAX_RECORDS_PER_SURFACE,
    MicrosoftAdminError,
    MicrosoftAdminReadResponse,
)
from .normalizers import (
    _normalize_autopilot_device,
    _normalize_compliance_policy,
    _normalize_conditional_access_policy,
    _normalize_intune_app,
    _normalize_risky_user,
    _normalize_secure_score,
    _normalize_security_alert,
    _normalize_security_incident,
    _normalize_service_health,
    _normalize_service_issue,
    _normalize_sign_in,
)


class MicrosoftAdminGraphClient:
    """Bounded Microsoft Graph reads for the Microsoft administrator pack."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        connection: M365Connection | None = None,
        connection_resolver: M365ConnectionResolver | None = None,
        client_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.connection = connection
        self.connection_resolver = connection_resolver
        self.client_id = client_id

    def health(self) -> ConnectorReadResult:
        blocked = self._blocked_result()
        if blocked is not None:
            return blocked
        missing = self._not_configured_result()
        if missing is not None:
            return missing
        response = self.list_service_health(page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult(
                "ready",
                "Microsoft administrator Graph read prerequisites are ready.",
                response.result.count,
            )
        return response.result

    def list_service_health(
        self, *, cursor: str | None = None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "admin/serviceAnnouncement/healthOverviews",
            page_size=page_size,
            select="id,service,status",
            normalizer=_normalize_service_health,
            success_message="Microsoft 365 service health read succeeded.",
            cursor=cursor,
        )

    def list_service_issues(
        self, *, cursor: str | None = None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "admin/serviceAnnouncement/issues",
            page_size=page_size,
            select=(
                "id,title,service,status,classification,origin,impactDescription,startDateTime,"
                "endDateTime,lastModifiedDateTime,feature,featureGroup"
            ),
            orderby="lastModifiedDateTime desc",
            normalizer=_normalize_service_issue,
            success_message="Microsoft 365 service issue read succeeded.",
            cursor=cursor,
        )

    def list_secure_scores(
        self, *, cursor: str | None = None, page_size: int = 1
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "security/secureScores",
            page_size=page_size,
            select=None,
            normalizer=_normalize_secure_score,
            success_message="Microsoft Secure Score read succeeded.",
            cursor=cursor,
        )

    def list_sign_ins(
        self,
        *,
        identity: str | None = None,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        filter_expression = None
        if identity is not None:
            try:
                filter_expression = f"userPrincipalName eq '{_odata_literal(identity)}'"
            except MicrosoftAdminError as exc:
                return _failed_response(str(exc))
        return self._list(
            "auditLogs/signIns",
            page_size=page_size,
            select=None,
            filter_expression=filter_expression,
            normalizer=_normalize_sign_in,
            success_message="Microsoft Entra sign-in read succeeded.",
            cursor=cursor,
        )

    def list_conditional_access_policies(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "identity/conditionalAccess/policies",
            page_size=page_size,
            select=(
                "id,displayName,state,createdDateTime,modifiedDateTime,conditions,grantControls,"
                "sessionControls"
            ),
            normalizer=_normalize_conditional_access_policy,
            success_message="Microsoft Entra Conditional Access policy read succeeded.",
            cursor=cursor,
        )

    def list_risky_users(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "identityProtection/riskyUsers",
            page_size=page_size,
            select=(
                "id,userDisplayName,userPrincipalName,riskDetail,riskLevel,riskState,"
                "riskLastUpdatedDateTime,isDeleted,isProcessing"
            ),
            normalizer=_normalize_risky_user,
            success_message="Microsoft Entra risky-user read succeeded.",
            cursor=cursor,
        )

    def list_intune_apps(
        self, *, cursor: str | None = None, page_size: int = DEFAULT_PAGE_SIZE
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "deviceAppManagement/mobileApps",
            page_size=page_size,
            select=(
                "id,displayName,publisher,createdDateTime,lastModifiedDateTime,isFeatured,owner,developer"
            ),
            orderby="lastModifiedDateTime desc",
            normalizer=_normalize_intune_app,
            success_message="Microsoft Intune application inventory read succeeded.",
            cursor=cursor,
        )

    def list_compliance_policies(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "deviceManagement/deviceCompliancePolicies",
            page_size=page_size,
            select="id,displayName,description,createdDateTime,lastModifiedDateTime,version",
            orderby="lastModifiedDateTime desc",
            normalizer=_normalize_compliance_policy,
            success_message="Microsoft Intune compliance policy read succeeded.",
            cursor=cursor,
        )

    def list_autopilot_devices(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "deviceManagement/windowsAutopilotDeviceIdentities",
            page_size=page_size,
            select=(
                "id,displayName,groupTag,manufacturer,model,enrollmentState,lastContactedDateTime,"
                "azureActiveDirectoryDeviceId,managedDeviceId"
            ),
            orderby="lastContactedDateTime desc",
            normalizer=_normalize_autopilot_device,
            success_message="Microsoft Intune Autopilot inventory read succeeded.",
            cursor=cursor,
        )

    def list_defender_incidents(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "security/incidents",
            page_size=page_size,
            select=None,
            normalizer=_normalize_security_incident,
            success_message="Microsoft Defender incident read succeeded.",
            cursor=cursor,
        )

    def list_defender_alerts(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MicrosoftAdminReadResponse:
        return self._list(
            "security/alerts_v2",
            page_size=page_size,
            select=None,
            normalizer=_normalize_security_alert,
            success_message="Microsoft Defender alert read succeeded.",
            cursor=cursor,
        )

    def _list(
        self,
        endpoint: str,
        *,
        page_size: int,
        select: str | None,
        normalizer: Callable[[Mapping[str, object]], dict[str, object] | None],
        success_message: str,
        filter_expression: str | None = None,
        orderby: str | None = None,
        cursor: str | None = None,
    ) -> MicrosoftAdminReadResponse:
        blocked = self._blocked_result()
        if blocked is not None:
            return MicrosoftAdminReadResponse(blocked, [])
        missing = self._not_configured_result()
        if missing is not None:
            return MicrosoftAdminReadResponse(missing, [])
        try:
            safe_endpoint = _safe_endpoint(endpoint)
            params = _list_params(
                page_size=page_size,
                select=select,
                filter_expression=filter_expression,
                orderby=orderby,
                cursor=cursor,
            )
            payload = self._get(safe_endpoint, params)
            rows = _payload_rows(payload)[:MAX_RECORDS_PER_SURFACE]
            items = [item for row in rows if (item := normalizer(row)) is not None]
        except MicrosoftAdminError as exc:
            return _failed_response(str(exc))
        return MicrosoftAdminReadResponse(
            ConnectorReadResult("ready", success_message, len(items)),
            items,
            _next_cursor(payload),
        )

    def _get(self, endpoint: str, params: dict[str, str | int]) -> object:
        try:
            connection = self._connection()
            base_url = _graph_base_url(
                connection.graph_base_url,
                allow_insecure_transport=self.settings.allow_insecure_provider_transport,
            )
            url = f"{base_url}/{endpoint}"
            headers = {
                "Authorization": f"Bearer {connection.token_provider.get_token()}",
                "Accept": "application/json",
            }
            if self.transport is not None:
                client = httpx.Client(
                    timeout=self.settings.connector_timeout_seconds,
                    transport=self.transport,
                    trust_env=False,
                    follow_redirects=False,
                )
            else:
                host = urlsplit(base_url).hostname
                if host is None:
                    raise MicrosoftAdminError("Microsoft Graph base URL is invalid.")
                client = build_pinned_client(
                    allowed_hosts=(host,),
                    timeout=self.settings.connector_timeout_seconds,
                    allow_loopback=host.casefold() in {"localhost", "127.0.0.1", "::1"},
                )
            with client:
                response = client.get(url, headers=headers, params=params)
        except (MicrosoftAdminError, M365ProfileResolutionError):
            raise
        except M365AuthFailure as exc:
            raise MicrosoftAdminError("Microsoft administrator Graph token acquisition failed.") from exc
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise MicrosoftAdminError(
                "Microsoft administrator Graph request failed before receiving a response."
            ) from exc
        except (httpx.HTTPError, NetSecurityError) as exc:
            raise MicrosoftAdminError("Microsoft administrator Graph request failed safely.") from exc
        if response.status_code >= 400:
            raise MicrosoftAdminError(
                f"Microsoft Graph GET {endpoint} failed with HTTP {response.status_code}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise MicrosoftAdminError(f"Microsoft Graph GET {endpoint} returned malformed JSON.") from exc

    def _blocked_result(self) -> ConnectorReadResult | None:
        if self.settings.allow_http_probing:
            return None
        return ConnectorReadResult(
            "blocked",
            "Microsoft administrator live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.",
        )

    def _not_configured_result(self) -> ConnectorReadResult | None:
        try:
            connection = self._connection()
        except (M365ProfileResolutionError, MicrosoftAdminError) as exc:
            return ConnectorReadResult("failed", str(exc))
        if connection.token_provider.configured and connection.graph_base_url:
            return None
        missing = [
            key
            for key, value in {
                "WAIT_M365_GRAPH_BASE_URL": connection.graph_base_url,
                "WAIT_M365_ACCESS_TOKEN": self.settings.m365_access_token,
            }.items()
            if not value
        ]
        if not missing:
            return None
        return ConnectorReadResult(
            "not_configured",
            f"Microsoft administrator Graph credentials are missing: {', '.join(missing)}.",
        )

    def _connection(self) -> M365Connection:
        if self.connection_resolver is not None:
            try:
                return self.connection_resolver.resolve(self.client_id)
            except M365ProfileResolutionError as exc:
                raise MicrosoftAdminError(str(exc)) from exc
        return self.connection or env_connection(self.settings)


def _graph_base_url(value: str, *, allow_insecure_transport: bool) -> str:
    candidate = value.strip().rstrip("/")
    try:
        validate_operator_url(candidate, allow_insecure_transport=allow_insecure_transport)
    except NetSecurityError as exc:
        raise MicrosoftAdminError("Microsoft Graph base URL is invalid.") from exc
    parsed = urlsplit(candidate)
    if parsed.query or parsed.fragment:
        raise MicrosoftAdminError("Microsoft Graph base URL cannot contain a query or fragment.")
    if not parsed.path.rstrip("/").endswith("/v1.0"):
        raise MicrosoftAdminError("Microsoft administrator pack requires a Microsoft Graph v1.0 base URL.")
    return candidate


def _safe_endpoint(endpoint: str) -> str:
    candidate = endpoint.strip().strip("/")
    if candidate not in _ENDPOINTS:
        raise MicrosoftAdminError("Microsoft administrator Graph endpoint is not allowlisted.")
    return candidate


def _list_params(
    *,
    page_size: int,
    select: str | None,
    filter_expression: str | None,
    orderby: str | None,
    cursor: str | None,
) -> dict[str, str | int]:
    params: dict[str, str | int] = {"$top": _bounded_page_size(page_size)}
    if select:
        params["$select"] = select
    if filter_expression:
        params["$filter"] = filter_expression
    if orderby:
        params["$orderby"] = orderby
    if cursor:
        params.update(_cursor_params(cursor))
    return params


def _cursor_params(cursor: str) -> dict[str, str]:
    candidate = cursor.strip()
    if not candidate or len(candidate) > MAX_CURSOR_LENGTH:
        raise MicrosoftAdminError("Microsoft administrator pagination cursor is invalid.")
    if any(ord(character) < 32 for character in candidate):
        raise MicrosoftAdminError("Microsoft administrator pagination cursor is invalid.")
    query = candidate[1:] if candidate.startswith("?") else candidate
    if not query or "://" in query or any(character in query for character in ("/", "\\", "#", "?")):
        raise MicrosoftAdminError("Microsoft administrator pagination cursor must contain query parameters only.")
    pairs = parse_qsl(query, keep_blank_values=True)
    if not pairs or any(key not in _ALLOWED_CURSOR_KEYS for key, _ in pairs):
        raise MicrosoftAdminError("Microsoft administrator pagination cursor contains unsupported fields.")
    return {key: value for key, value in pairs}


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, Mapping):
        return ""
    next_link = payload.get("@odata.nextLink")
    if not isinstance(next_link, str) or not next_link:
        return ""
    parsed = urlsplit(next_link)
    if not parsed.query:
        return ""
    pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key in _ALLOWED_CURSOR_KEYS
    ]
    if not pairs:
        return ""
    cursor = urlencode(pairs, safe="$")
    return cursor[:MAX_CURSOR_LENGTH]


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        raise MicrosoftAdminError("Microsoft administrator Graph response is not an object.")
    rows = payload.get("value")
    if not isinstance(rows, list):
        raise MicrosoftAdminError("Microsoft administrator Graph response is missing a value collection.")
    return [cast(Mapping[str, object], row) for row in rows if isinstance(row, Mapping)]


def _bounded_page_size(value: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise MicrosoftAdminError("Microsoft administrator page size must be a positive integer.")
    return min(value, MAX_PAGE_SIZE)


def _bounded_identity(value: str) -> str:
    candidate = value.strip()
    if not candidate or len(candidate) > MAX_IDENTITY_LENGTH:
        raise MicrosoftAdminError("Microsoft administrator user identity is invalid.")
    if any(ord(character) < 32 for character in candidate):
        raise MicrosoftAdminError("Microsoft administrator user identity is invalid.")
    return candidate


def _odata_literal(value: str) -> str:
    return _bounded_identity(value).replace("'", "''")


def _failed_response(message: str) -> MicrosoftAdminReadResponse:
    return MicrosoftAdminReadResponse(ConnectorReadResult("failed", message), [])
