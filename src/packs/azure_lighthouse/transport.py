"""Pinned, bounded Azure Resource Manager HTTP transport."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.net_security import NetSecurityError, build_pinned_client

from .models import (
    ARM_BASE_URL,
    ARM_SCOPE,
    MAX_PAGES,
    MAX_RECORDS,
    AzureLighthouseAuthorizationError,
    AzureLighthouseProviderError,
    TokenCredential,
)


class AzureArmTransport:
    """GET-only ARM client with pinned host and bounded pagination."""

    def __init__(
        self,
        settings: Settings,
        credential: TokenCredential,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.credential = credential
        self.transport = transport

    def collection(
        self,
        path: str,
        params: dict[str, str],
        *,
        max_records: int = MAX_RECORDS,
    ) -> list[Mapping[str, object]]:
        if not isinstance(max_records, int) or isinstance(max_records, bool) or not 1 <= max_records <= MAX_RECORDS:
            raise AzureLighthouseProviderError(
                f"Azure Resource Manager record limit must be between 1 and {MAX_RECORDS}."
            )
        records: list[Mapping[str, object]] = []
        url = initial_url(path, params)
        for _ in range(MAX_PAGES):
            payload = self.request_json(url)
            if not isinstance(payload, Mapping):
                raise AzureLighthouseProviderError(
                    "Azure Resource Manager returned an invalid collection response."
                )
            response_payload = cast(Mapping[str, object], payload)
            value = response_payload.get("value")
            if not isinstance(value, list):
                raise AzureLighthouseProviderError(
                    "Azure Resource Manager collection response is missing a value array."
                )
            records.extend(
                cast(Mapping[str, object], item)
                for item in value
                if isinstance(item, Mapping)
            )
            if len(records) >= max_records:
                return records[:max_records]
            next_link = response_payload.get("nextLink")
            if not isinstance(next_link, str) or not next_link:
                return records
            url = validated_next_link(next_link)
        raise AzureLighthouseProviderError(
            "Azure Resource Manager pagination exceeded the bounded page limit."
        )

    def mapping_object(self, path: str, params: dict[str, str]) -> Mapping[str, object]:
        payload = self.request_json(initial_url(path, params))
        if not isinstance(payload, Mapping):
            raise AzureLighthouseProviderError(
                "Azure Resource Manager returned an invalid object response."
            )
        return cast(Mapping[str, object], payload)

    def request_json(self, url: str) -> object:
        try:
            token = self.credential.get_token(ARM_SCOPE).token
        except Exception as exc:
            raise AzureLighthouseAuthorizationError(
                "Azure Lighthouse access token could not be acquired."
            ) from exc
        if not isinstance(token, str) or not token:
            raise AzureLighthouseAuthorizationError(
                "Azure Lighthouse access token is unavailable."
            )
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            if self.transport is not None:
                client = httpx.Client(
                    transport=self.transport,
                    timeout=self.settings.connector_timeout_seconds,
                    trust_env=False,
                    follow_redirects=False,
                )
            else:
                client = build_pinned_client(
                    allowed_hosts=("management.azure.com",),
                    timeout=self.settings.connector_timeout_seconds,
                    allow_loopback=False,
                )
            with client:
                response = client.get(url, headers=headers)
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            raise AzureLighthouseProviderError(
                "Azure Resource Manager request failed before receiving a response."
            ) from exc
        except (httpx.HTTPError, NetSecurityError) as exc:
            raise AzureLighthouseProviderError(
                "Azure Resource Manager request failed safely."
            ) from exc
        if response.status_code in {401, 403}:
            raise AzureLighthouseAuthorizationError(
                "Azure Resource Manager rejected access to the requested delegated scope."
            )
        if response.status_code >= 400:
            raise AzureLighthouseProviderError(
                f"Azure Resource Manager returned HTTP {response.status_code}."
            )
        try:
            return response.json()
        except ValueError as exc:
            raise AzureLighthouseProviderError(
                "Azure Resource Manager returned malformed JSON."
            ) from exc


def initial_url(path: str, params: dict[str, str]) -> str:
    if not path.startswith("/") or "?" in path or "#" in path or "\\" in path:
        raise AzureLighthouseProviderError("Azure Resource Manager path is invalid.")
    if path != "/subscriptions" and not path.startswith("/subscriptions/"):
        raise AzureLighthouseProviderError(
            "Azure Resource Manager path is outside the allowed scope."
        )
    return f"{ARM_BASE_URL}{path}?{urlencode(params, safe='$')}"


def validated_next_link(value: str) -> str:
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise AzureLighthouseProviderError(
            "Azure Resource Manager pagination link has an invalid port."
        ) from exc
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() != "management.azure.com"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not parsed.path.startswith("/subscriptions")
        or parsed.fragment
    ):
        raise AzureLighthouseProviderError(
            "Azure Resource Manager pagination link is outside the allowed host or scope."
        )
    query = urlencode(
        parse_qsl(parsed.query, keep_blank_values=True),
        doseq=True,
        safe="$,",
    )
    return urlunsplit(("https", "management.azure.com", parsed.path, query, ""))
