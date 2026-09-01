"""Runtime Microsoft 365 connection profiles and token acquisition."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import import_module
from threading import Lock
from typing import Any, Protocol

from wait_local_agent.models import ConnectorInstance

M365_CONNECTOR_TYPE = "m365"
M365_GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
M365_GRAPH_SCOPE = "https://graph.microsoft.com/.default"
M365_TOKEN_AUTHORITY = "login.microsoftonline.com"  # nosec B105: fixed Microsoft endpoint hostname, not a secret.


class M365AuthFailure(Exception):
    """A sanitized failure while resolving or acquiring a Graph token."""


class M365ProfileResolutionError(Exception):
    """Raised when a stored M365 profile cannot be selected safely."""


class TokenProvider(Protocol):
    configured: bool

    def get_token(self) -> str:
        ...


@dataclass(frozen=True)
class M365Connection:
    graph_base_url: str
    token_provider: TokenProvider
    profile_id: str | None = None


class M365TokenProvider:
    """Lazily acquire and cache one profile's app token in process memory."""

    def __init__(
        self,
        credentials: Mapping[str, str],
        *,
        now: Callable[[], float] = time.time,
        credential_factory: Callable[[Mapping[str, str]], Any] | None = None,
    ) -> None:
        mode = credentials.get("mode", "")
        if mode not in {"client_credentials", "static_token"}:
            raise M365AuthFailure("Microsoft 365 credential mode is invalid")
        self._credentials = dict(credentials)
        self._mode = mode
        self._now = now
        self._credential_factory = credential_factory or self._default_credential
        self._credential: Any | None = None
        self._cached_token: str | None = None
        self._expires_on: float | None = None
        self._lock = Lock()
        self.configured = True

    @classmethod
    def from_static_token(cls, token: str) -> M365TokenProvider:
        return cls({"mode": "static_token", "access_token": token})

    def get_token(self) -> str:
        if self._mode == "static_token":
            token = self._credentials.get("access_token", "")
            if not token:
                raise M365AuthFailure("Microsoft Graph access token is not configured")
            return token

        with self._lock:
            if self._cached_token and self._expires_on is not None and self._expires_on > self._now():
                return self._cached_token
            try:
                if self._credential is None:
                    self._credential = self._credential_factory(self._credentials)
                access_token = self._credential.get_token(M365_GRAPH_SCOPE)
                token_value = getattr(access_token, "token", None)
                expires_on = getattr(access_token, "expires_on", None)
                if not isinstance(token_value, str) or not token_value:
                    raise ValueError("token response did not include a token")
                if isinstance(expires_on, bool) or not isinstance(expires_on, (int, float)):
                    raise ValueError("token response did not include an expiry")
            except Exception as exc:
                self._cached_token = None
                self._expires_on = None
                raise M365AuthFailure("Microsoft Graph token acquisition failed") from exc
            token = token_value
            self._cached_token = token
            self._expires_on = float(expires_on)
            return token

    @staticmethod
    def _default_credential(credentials: Mapping[str, str]) -> Any:
        ClientSecretCredential = import_module("azure.identity").ClientSecretCredential

        return ClientSecretCredential(
            tenant_id=credentials["tenant_id"],
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            authority=M365_TOKEN_AUTHORITY,
        )


class _UnconfiguredTokenProvider:
    configured = False

    def get_token(self) -> str:
        raise M365AuthFailure("Microsoft Graph access token is not configured")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate credential key")
        result[key] = value
    return result


def validate_m365_credentials(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise M365ProfileResolutionError("invalid Microsoft 365 credentials")
    mode = value.get("mode")
    if mode == "client_credentials":
        expected = {"mode", "tenant_id", "client_id", "client_secret"}
    elif mode == "static_token":
        expected = {"mode", "access_token"}
    else:
        raise M365ProfileResolutionError(
            "invalid Microsoft 365 credentials; mode must be client_credentials or static_token"
        )
    if set(value) != expected or any(not isinstance(item, str) or not item.strip() for item in value.values()):
        raise M365ProfileResolutionError(
            "invalid Microsoft 365 credentials; fields must exactly match the selected mode"
        )
    return {key: item.strip() for key, item in value.items() if isinstance(item, str)}


def _profile_credentials(instance: ConnectorInstance, vault: Any) -> dict[str, str]:
    if not isinstance(instance.credential_ref, str) or not instance.credential_ref.strip():
        raise M365ProfileResolutionError("connector credential reference is required")
    try:
        secret = vault.get(instance.credential_ref)
    except Exception as exc:
        raise M365ProfileResolutionError("connector credentials could not be read") from exc
    if not isinstance(secret, str) or not secret:
        raise M365ProfileResolutionError("connector credentials were not found")
    try:
        value = json.loads(secret, object_pairs_hook=_reject_duplicate_keys)
    except Exception as exc:
        raise M365ProfileResolutionError("connector credentials must be valid JSON") from exc
    return validate_m365_credentials(value)


def _validate_profile_config(instance: ConnectorInstance) -> None:
    try:
        value = json.loads(instance.config_json or "{}", object_pairs_hook=_reject_duplicate_keys)
    except Exception as exc:
        raise M365ProfileResolutionError("connector config_json must be valid JSON") from exc
    if not isinstance(value, dict) or value:
        raise M365ProfileResolutionError(
            "Microsoft 365 connector config_json must be an empty object; Graph origin is fixed"
        )


class M365ConnectionResolver:
    """Resolve client-scoped, MSP-wide, then environment M365 configuration."""

    def __init__(self, settings: Any, store: Any, vault: Any) -> None:
        self.settings = settings
        self.store = store
        self.vault = vault
        self._providers: dict[tuple[str, str], M365TokenProvider] = {}

    def resolve(self, client_id: str | None = None) -> M365Connection:
        normalized_client_id = client_id.strip() if isinstance(client_id, str) else ""
        try:
            instances = self.store.list_connector_instances()
        except Exception as exc:
            raise M365ProfileResolutionError("Microsoft 365 connector instances could not be loaded") from exc
        active = [
            instance
            for instance in instances
            if str(instance.status).strip().casefold() == "active"
            and str(instance.connector_type).strip().casefold() == M365_CONNECTOR_TYPE
        ]
        candidates = (
            [
                instance
                for instance in active
                if isinstance(instance.client_id, str) and instance.client_id.strip() == normalized_client_id
            ]
            if normalized_client_id
            else []
        )
        tier = "client-scoped"
        if not candidates:
            candidates = [
                instance
                for instance in active
                if not isinstance(instance.client_id, str) or not instance.client_id.strip()
            ]
            tier = "MSP-wide"
        if len(candidates) > 1:
            raise M365ProfileResolutionError(
                f"ambiguous active Microsoft 365 connector instances at the {tier} tier"
            )
        if candidates:
            return self._profile_connection(candidates[0])
        return M365Connection(
            graph_base_url=self.settings.m365_graph_base_url,
            token_provider=(
                M365TokenProvider.from_static_token(self.settings.m365_access_token)
                if self.settings.m365_access_token
                else _UnconfiguredTokenProvider()
            ),
        )

    def _profile_connection(self, instance: ConnectorInstance) -> M365Connection:
        _validate_profile_config(instance)
        credentials = _profile_credentials(instance, self.vault)
        cache_key = (instance.connector_instance_id, instance.credential_ref or "")
        provider = self._providers.get(cache_key)
        if provider is None:
            provider = M365TokenProvider(credentials)
            self._providers[cache_key] = provider
        return M365Connection(
            graph_base_url=M365_GRAPH_BASE_URL,
            token_provider=provider,
            profile_id=instance.connector_instance_id,
        )


def resolve_m365_connection(settings: Any, store: Any, vault: Any, client_id: str | None = None) -> M365Connection:
    return M365ConnectionResolver(settings, store, vault).resolve(client_id)


def env_connection(settings: Any) -> M365Connection:
    return M365Connection(
        graph_base_url=settings.m365_graph_base_url,
        token_provider=(
            M365TokenProvider.from_static_token(settings.m365_access_token)
            if settings.m365_access_token
            else _UnconfiguredTokenProvider()
        ),
    )
