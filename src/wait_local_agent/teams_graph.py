"""Bounded Microsoft Graph Teams channel access.

This adapter uses the existing Microsoft Graph token boundary. Reads are
bounded metadata/message reads; channel messages are sent only through an
explicit approval request exposed by the API.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.m365_auth import M365AuthFailure, M365Connection
from wait_local_agent.models import ConnectorReadResult, ConnectorStatusValue
from wait_local_agent.net_security import NetSecurityError, validate_operator_url
from wait_local_agent.reports.renderers import redact_text

DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100
MAX_CURSOR_LENGTH = 4096
MAX_ID_LENGTH = 320
MAX_MESSAGE_LENGTH = 4_000


@dataclass(frozen=True)
class TeamsTeam:
    id: str
    display_name: str
    description: str
    web_url: str


@dataclass(frozen=True)
class TeamsChannel:
    id: str
    team_id: str
    display_name: str
    description: str
    membership_type: str
    web_url: str


@dataclass(frozen=True)
class TeamsMessage:
    id: str
    team_id: str
    channel_id: str
    subject: str
    body: str
    from_display_name: str
    created_at: str
    web_url: str


@dataclass(frozen=True)
class TeamsTeamReadResponse:
    result: ConnectorReadResult
    items: list[TeamsTeam]
    next_cursor: str = ""


@dataclass(frozen=True)
class TeamsChannelReadResponse:
    result: ConnectorReadResult
    items: list[TeamsChannel]
    next_cursor: str = ""


@dataclass(frozen=True)
class TeamsMessageReadResponse:
    result: ConnectorReadResult
    items: list[TeamsMessage]
    next_cursor: str = ""


@dataclass(frozen=True)
class TeamsMessageSendResult:
    status: str
    message: str
    team_id: str = ""
    channel_id: str = ""
    remote_id: str = ""
    status_code: int | None = None


class TeamsGraphReadError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TeamsGraphClient:
    """Read-bounded and approval-gated Microsoft Graph Teams client."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
        connection: M365Connection | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.connection = connection

    def health(self) -> ConnectorReadResult:
        response = self.list_teams(page_size=1)
        if response.result.status == "ready":
            return ConnectorReadResult("ready", "Microsoft Graph Teams reads are ready.")
        return response.result

    def list_teams(
        self,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TeamsTeamReadResponse:
        try:
            params = _list_params(page_size, cursor)
            payload = self._get("me/joinedTeams", params=params)
        except TeamsGraphReadError as exc:
            return TeamsTeamReadResponse(
                ConnectorReadResult(cast(ConnectorStatusValue, _status(exc.message)), exc.message), []
            )
        items = [team for row in _payload_rows(payload) if (team := _normalize_team(row)) is not None]
        return TeamsTeamReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph Teams metadata read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def list_channels(
        self,
        team_id: str,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TeamsChannelReadResponse:
        try:
            safe_team_id = _safe_id(team_id, "team_id")
            payload = self._get(
                f"teams/{quote(safe_team_id, safe='')}/channels",
                params=_list_params(page_size, cursor),
            )
        except TeamsGraphReadError as exc:
            return TeamsChannelReadResponse(
                ConnectorReadResult(cast(ConnectorStatusValue, _status(exc.message)), exc.message), []
            )
        items = [
            channel for row in _payload_rows(payload) if (channel := _normalize_channel(row, safe_team_id)) is not None
        ]
        return TeamsChannelReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph Teams channel metadata read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def list_messages(
        self,
        team_id: str,
        channel_id: str,
        *,
        cursor: str | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TeamsMessageReadResponse:
        try:
            safe_team_id = _safe_id(team_id, "team_id")
            safe_channel_id = _safe_id(channel_id, "channel_id")
            payload = self._get(
                f"teams/{quote(safe_team_id, safe='')}/channels/{quote(safe_channel_id, safe='')}/messages",
                params=_list_params(page_size, cursor),
            )
        except TeamsGraphReadError as exc:
            return TeamsMessageReadResponse(
                ConnectorReadResult(cast(ConnectorStatusValue, _status(exc.message)), exc.message), []
            )
        items = [
            message
            for row in _payload_rows(payload)
            if (message := _normalize_message(row, safe_team_id, safe_channel_id)) is not None
        ]
        return TeamsMessageReadResponse(
            ConnectorReadResult("ready", "Microsoft Graph Teams message metadata read succeeded.", len(items)),
            items,
            _next_cursor(payload),
        )

    def send_message(self, *, team_id: str, channel_id: str, body: str) -> TeamsMessageSendResult:
        health = self.write_health()
        if health.status != "ready":
            return TeamsMessageSendResult("blocked", health.message)
        try:
            safe_team_id = _safe_id(team_id, "team_id")
            safe_channel_id = _safe_id(channel_id, "channel_id")
            safe_body = _safe_message(body)
            payload, status_code = self._post(
                f"teams/{quote(safe_team_id, safe='')}/channels/{quote(safe_channel_id, safe='')}/messages",
                {"body": {"contentType": "text", "content": safe_body}},
            )
        except TeamsGraphReadError as exc:
            return TeamsMessageSendResult("failed", exc.message)
        remote_id = _string_value(payload, "id")
        if not remote_id:
            return TeamsMessageSendResult(
                "failed",
                "Microsoft Graph Teams message send returned no message identity.",
                safe_team_id,
                safe_channel_id,
                status_code=status_code,
            )
        return TeamsMessageSendResult(
            "succeeded",
            "Microsoft Graph Teams message send succeeded.",
            safe_team_id,
            safe_channel_id,
            remote_id,
            status_code,
        )

    def write_health(self) -> ConnectorReadResult:
        if not self.settings.allow_http_probing:
            return ConnectorReadResult(
                "blocked", "Microsoft Graph live writes are blocked until WAIT_ALLOW_HTTP_PROBING=true."
            )
        if not self.settings.allow_write_actions:
            return ConnectorReadResult(
                "blocked", "Microsoft Graph live writes are blocked until WAIT_ALLOW_WRITE_ACTIONS=true."
            )
        missing = _missing_configuration(self.settings)
        if missing:
            return ConnectorReadResult("not_configured", missing)
        return ConnectorReadResult("ready", "Microsoft Graph Teams writes are ready.")

    def _get(self, endpoint: str, *, params: dict[str, str | int]) -> object:
        if not self.settings.allow_http_probing:
            raise TeamsGraphReadError("Microsoft Graph live reads are blocked until WAIT_ALLOW_HTTP_PROBING=true.")
        missing = _missing_configuration(self.settings, self.connection)
        if missing:
            raise TeamsGraphReadError(missing)
        return self._request("GET", endpoint, params=params)

    def _post(self, endpoint: str, payload: dict[str, object]) -> tuple[object, int]:
        if not self.settings.allow_http_probing or not self.settings.allow_write_actions:
            raise TeamsGraphReadError(
                "Microsoft Graph Teams writes require HTTP probing and write actions to be enabled."
            )
        missing = _missing_configuration(self.settings)
        if missing:
            raise TeamsGraphReadError(missing)
        result = self._request("POST", endpoint, payload=payload)
        return cast(tuple[object, int], result)

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: dict[str, str | int] | None = None,
        payload: dict[str, object] | None = None,
    ) -> object:
        safe_endpoint = _safe_endpoint(endpoint)
        graph_base_url = (
            self.connection.graph_base_url if self.connection is not None else self.settings.m365_graph_base_url
        )
        try:
            access_token = (
                self.connection.token_provider.get_token()
                if self.connection is not None
                else self.settings.m365_access_token
            )
        except M365AuthFailure as exc:
            raise TeamsGraphReadError("Microsoft Graph Teams token acquisition failed.") from exc
        base_url = _api_base_url(
            graph_base_url,
            allow_insecure_transport=self.settings.allow_insecure_provider_transport,
        )
        try:
            with httpx.Client(timeout=self.settings.connector_timeout_seconds, transport=self.transport) as client:
                response = client.request(
                    method,
                    f"{base_url}/{safe_endpoint}",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    params=params,
                    json=payload,
                )
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise TeamsGraphReadError("Microsoft Graph Teams request failed before receiving a response.") from exc
        except httpx.HTTPError as exc:
            raise TeamsGraphReadError("Microsoft Graph Teams request failed.") from exc
        if response.status_code >= 400:
            raise TeamsGraphReadError(f"Microsoft Graph {method} {safe_endpoint} returned HTTP {response.status_code}.")
        try:
            return (response.json(), response.status_code) if method == "POST" else response.json()
        except ValueError as exc:
            raise TeamsGraphReadError(f"Microsoft Graph {method} {safe_endpoint} returned malformed JSON.") from exc


def _missing_configuration(settings: Settings, connection: M365Connection | None = None) -> str:
    if connection is not None:
        if connection.token_provider.configured and connection.graph_base_url:
            return ""
        return "Microsoft Graph credentials are incomplete."
    missing = [
        key
        for key, value in {
            "WAIT_M365_GRAPH_BASE_URL": settings.m365_graph_base_url,
            "WAIT_M365_ACCESS_TOKEN": settings.m365_access_token,
        }.items()
        if not value
    ]
    return f"Microsoft Graph credentials are incomplete: {', '.join(missing)}." if missing else ""


def _status(message: str) -> str:
    return "not_configured" if "credentials" in message else "blocked" if "blocked" in message else "failed"


def _api_base_url(value: str, *, allow_insecure_transport: bool = False) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise TeamsGraphReadError("Microsoft Graph base URL must be a credential-free HTTP(S) URL.")
    try:
        validate_operator_url(value, allow_insecure_transport=allow_insecure_transport)
    except NetSecurityError as exc:
        raise TeamsGraphReadError(
            "Microsoft Graph base URL must use HTTPS; set "
            "WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT=true to allow plain HTTP."
        ) from exc
    return value.rstrip("/")


def _safe_endpoint(value: str) -> str:
    parts = value.split("/")
    if not parts or any(not part or part in {".", ".."} or not _safe_encoded(part) for part in parts):
        raise TeamsGraphReadError("Microsoft Graph Teams endpoint is invalid.")
    return value


def _safe_encoded(value: str) -> bool:
    from urllib.parse import unquote

    return bool(value) and quote(unquote(value), safe="") == value and not any(ord(char) < 32 for char in value)


def _safe_id(value: str, field: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > MAX_ID_LENGTH or not _safe_encoded(normalized):
        raise TeamsGraphReadError(f"{field} is invalid.")
    return normalized


def _safe_message(value: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > MAX_MESSAGE_LENGTH
        or any(ord(char) < 32 and char not in {"\n", "\t"} for char in normalized)
    ):
        raise TeamsGraphReadError("Teams message body must be 1 to 4000 characters.")
    return normalized


def _list_params(page_size: int, cursor: str | None) -> dict[str, str | int]:
    if isinstance(page_size, bool) or page_size < 1:
        raise TeamsGraphReadError("Teams page_size must be at least 1.")
    params: dict[str, str | int] = {"$top": min(page_size, MAX_PAGE_SIZE)}
    if cursor is not None:
        normalized = cursor.strip()
        if not normalized or len(normalized) > MAX_CURSOR_LENGTH or any(ord(char) < 32 for char in normalized):
            raise TeamsGraphReadError("Teams cursor is invalid.")
        params["$skiptoken"] = normalized
    return params


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    rows = payload.get("value")
    return (
        [cast(Mapping[str, object], item) for item in rows if isinstance(item, Mapping)]
        if isinstance(rows, list)
        else []
    )


def _normalize_team(row: Mapping[str, object]) -> TeamsTeam | None:
    team_id = _string_value(row, "id")
    return (
        TeamsTeam(
            team_id, _string_value(row, "displayName"), _string_value(row, "description"), _string_value(row, "webUrl")
        )
        if team_id
        else None
    )


def _normalize_channel(row: Mapping[str, object], team_id: str) -> TeamsChannel | None:
    channel_id = _string_value(row, "id")
    return (
        TeamsChannel(
            channel_id,
            team_id,
            _string_value(row, "displayName"),
            _string_value(row, "description"),
            _string_value(row, "membershipType"),
            _string_value(row, "webUrl"),
        )
        if channel_id
        else None
    )


def _normalize_message(row: Mapping[str, object], team_id: str, channel_id: str) -> TeamsMessage | None:
    message_id = _string_value(row, "id")
    body = row.get("body")
    sender = row.get("from")
    user = sender.get("user") if isinstance(sender, Mapping) else None
    return (
        TeamsMessage(
            message_id,
            team_id,
            channel_id,
            _string_value(row, "subject"),
            redact_text(_string_value(body, "content")),
            _string_value(user, "displayName"),
            _string_value(row, "createdDateTime"),
            _string_value(row, "webUrl"),
        )
        if message_id
        else None
    )


def _string_value(value: object, key: str) -> str:
    if not isinstance(value, Mapping):
        return ""
    item = value.get(key)
    return item.strip()[:MAX_MESSAGE_LENGTH] if isinstance(item, str) else ""


def _next_cursor(payload: object) -> str:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("@odata.nextLink"), str):
        return ""
    values = parse_qs(urlsplit(cast(str, payload["@odata.nextLink"])).query).get("$skiptoken", [])
    return values[0][:MAX_CURSOR_LENGTH] if values else ""


__all__ = [
    "TeamsChannel",
    "TeamsChannelReadResponse",
    "TeamsGraphClient",
    "TeamsMessage",
    "TeamsMessageReadResponse",
    "TeamsMessageSendResult",
    "TeamsTeam",
    "TeamsTeamReadResponse",
]
