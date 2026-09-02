from __future__ import annotations

import json
import sys
import types
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest

from packs.microsoft_admin.client import MicrosoftAdminGraphClient
from wait_local_agent.m365_auth import (
    M365AuthFailure,
    M365Connection,
    M365ConnectionResolver,
    M365ProfileResolutionError,
    M365TokenProvider,
    resolve_m365_connection,
    validate_m365_credentials,
)
from wait_local_agent.m365_graph import M365GraphClient
from wait_local_agent.models import ConnectorInstance


def _instance(
    *,
    instance_id: str,
    client_id: str | None = None,
    status: str = "active",
    mode: str = "static_token",
    config_json: str = "{}",
) -> ConnectorInstance:
    return ConnectorInstance(
        connector_instance_id=instance_id,
        connector_type="m365",
        display_name="M365 profile",
        client_id=client_id,
        credential_ref=f"credential:{instance_id}",
        config_json=config_json,
        status=status,
        created_at="now",
        updated_at="now",
    )


class _Store:
    def __init__(self, instances: list[ConnectorInstance]) -> None:
        self.instances = instances

    def list_connector_instances(self) -> list[ConnectorInstance]:
        return self.instances


class _Vault:
    def __init__(self, instances: list[ConnectorInstance]) -> None:
        self.values = {
            instance.credential_ref: json.dumps(
                {"mode": "static_token", "access_token": "profile-value"}
            )
            for instance in instances
        }

    def get(self, key: str) -> str | None:
        return self.values.get(key)


def test_client_credentials_are_lazy_cached_and_refreshed_at_expiry() -> None:
    clock = [100.0]
    calls: list[tuple[str, ...]] = []

    class Credential:
        def get_token(self, *scopes: str) -> SimpleNamespace:
            calls.append(scopes)
            return SimpleNamespace(token=f"value-{len(calls)}", expires_on=200.0)

    provider = M365TokenProvider(
        {
            "mode": "client_credentials",
            "tenant_id": "tenant-value",
            "client_id": "application-value",
            "client_secret": "credential-value",
        },
        now=lambda: clock[0],
        credential_factory=lambda _: Credential(),
        refresh_skew_seconds=0,
    )

    assert provider.get_token() == "value-1"
    assert provider.get_token() == "value-1"
    clock[0] = 200.0
    assert provider.get_token() == "value-2"
    assert calls == [("https://graph.microsoft.com/.default",)] * 2


def test_client_credentials_refresh_before_expiry_with_configurable_skew() -> None:
    clock = [1_000.0]
    calls = 0

    class Credential:
        def get_token(self, *_scopes: str) -> SimpleNamespace:
            nonlocal calls
            calls += 1
            return SimpleNamespace(token=f"value-{calls}", expires_on=clock[0] + (240 if calls == 1 else 600))

    provider = M365TokenProvider(
        {"mode": "client_credentials", "tenant_id": "t", "client_id": "c", "client_secret": "s"},
        now=lambda: clock[0],
        credential_factory=lambda _: Credential(),
    )

    assert provider.get_token() == "value-1"
    assert calls == 1
    assert provider.get_token() == "value-2"
    assert calls == 2
    clock[0] += 1
    assert provider.get_token() == "value-2"
    assert calls == 2


def test_client_credentials_failure_is_sanitized() -> None:
    provider = M365TokenProvider(
        {
            "mode": "client_credentials",
            "tenant_id": "tenant-value",
            "client_id": "application-value",
            "client_secret": "credential-value",
        },
        credential_factory=lambda _: SimpleNamespace(
            get_token=lambda *_: (_ for _ in ()).throw(RuntimeError("credential-value leaked"))
        ),
    )
    with pytest.raises(M365AuthFailure, match="token acquisition failed") as error:
        provider.get_token()
    assert "credential-value" not in str(error.value)


def test_token_provider_rejects_invalid_mode_and_empty_static_token() -> None:
    with pytest.raises(M365AuthFailure, match="mode is invalid"):
        M365TokenProvider({"mode": "unsupported"})
    with pytest.raises(M365AuthFailure, match="access token is not configured"):
        M365TokenProvider.from_static_token("").get_token()


@pytest.mark.parametrize(
    "access_token",
    [
        SimpleNamespace(token="", expires_on=200),
        SimpleNamespace(token="ok", expires_on=True),
        SimpleNamespace(token="ok", expires_on="later"),
    ],
)
def test_client_credentials_rejects_incomplete_token_responses(access_token: SimpleNamespace) -> None:
    provider = M365TokenProvider(
        {"mode": "client_credentials", "tenant_id": "t", "client_id": "c", "client_secret": "s"},
        credential_factory=lambda _: SimpleNamespace(get_token=lambda *_: access_token),
    )
    with pytest.raises(M365AuthFailure, match="token acquisition failed"):
        provider.get_token()


def test_default_credential_factory_imports_azure_identity_lazily(monkeypatch) -> None:
    calls: list[dict[str, str]] = []

    class ClientSecretCredential:
        def __init__(self, **kwargs: str) -> None:
            calls.append(kwargs)

        def get_token(self, *_: str) -> SimpleNamespace:
            return SimpleNamespace(token="azure-token", expires_on=200)

    azure = types.ModuleType("azure")
    identity = types.ModuleType("azure.identity")
    identity.ClientSecretCredential = ClientSecretCredential  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "azure", azure)
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    provider = M365TokenProvider(
        {"mode": "client_credentials", "tenant_id": "t", "client_id": "c", "client_secret": "s"}
    )
    assert provider.get_token() == "azure-token"
    assert calls == [
        {
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "authority": "login.microsoftonline.com",
        }
    ]


def test_unconfigured_provider_and_duplicate_profile_keys_are_rejected(settings) -> None:
    with pytest.raises(M365AuthFailure, match="not configured"):
        M365ConnectionResolver(settings, _Store([]), _Vault([])).resolve().token_provider.get_token()
    duplicate = _instance(instance_id="duplicate")
    duplicate = replace(duplicate, credential_ref="duplicate-ref")

    class DuplicateVault:
        def get(self, key: str) -> str:
            return '{"mode":"static_token","access_token":"one","access_token":"two"}'

    with pytest.raises(M365ProfileResolutionError, match="valid JSON"):
        M365ConnectionResolver(settings, _Store([duplicate]), DuplicateVault()).resolve()


@pytest.mark.parametrize(
    ("instance", "vault", "message"),
    [
        (replace(_instance(instance_id="bad-ref"), credential_ref=""), _Vault([]), "reference is required"),
        (_instance(instance_id="missing"), _Vault([]), "were not found"),
        (replace(_instance(instance_id="bad-json"), credential_ref="bad-json"), _Vault([]), "valid JSON"),
        (
            replace(_instance(instance_id="bad-config"), config_json="not-json"),
            _Vault([]),
            "config_json must be valid JSON",
        ),
        (
            replace(_instance(instance_id="nonempty-config"), config_json='{"origin":"bad"}'),
            _Vault([]),
            "config_json must be an empty object",
        ),
    ],
)
def test_profile_resolution_errors_are_sanitized(instance, vault, message, settings) -> None:
    if instance.connector_instance_id == "bad-json":
        vault = types.SimpleNamespace(get=lambda _key: "not-json")
    elif instance.connector_instance_id in {"bad-config", "nonempty-config"}:
        vault = _Vault([instance])
    with pytest.raises(M365ProfileResolutionError, match=message):
        M365ConnectionResolver(settings, _Store([instance]), vault).resolve()


def test_resolver_redacts_store_failures_and_public_helper_resolves(settings) -> None:
    class BrokenStore:
        def list_connector_instances(self) -> list[ConnectorInstance]:
            raise RuntimeError("database details")

    with pytest.raises(M365ProfileResolutionError, match="could not be loaded"):
        M365ConnectionResolver(settings, BrokenStore(), _Vault([])).resolve()
    connection = resolve_m365_connection(settings, _Store([]), _Vault([]))
    assert connection.graph_base_url == settings.m365_graph_base_url


def test_profile_vault_read_failures_are_sanitized(settings) -> None:
    profile = _instance(instance_id="vault-failure")

    class BrokenVault:
        def get(self, key: str) -> str:
            raise RuntimeError(f"secret backend failure for {key}")

    with pytest.raises(M365ProfileResolutionError, match="credentials could not be read") as error:
        M365ConnectionResolver(settings, _Store([profile]), BrokenVault()).resolve()
    assert "secret backend failure" not in str(error.value)


@pytest.mark.parametrize(
    "value",
    [
        {"mode": "client_credentials", "tenant_id": "t", "client_id": "c"},
        {"mode": "static_token", "access_token": "a", "client_secret": "mixed"},
        {"mode": "unknown", "access_token": "a"},
    ],
)
def test_m365_credentials_are_an_exact_tagged_union(value: dict[str, str]) -> None:
    with pytest.raises(M365ProfileResolutionError):
        validate_m365_credentials(value)


def test_m365_credentials_reject_non_mapping() -> None:
    with pytest.raises(M365ProfileResolutionError, match="invalid Microsoft 365 credentials"):
        validate_m365_credentials(None)


def test_resolver_prefers_client_then_msp_then_environment_and_caches_profile_provider(settings) -> None:
    client_profile = _instance(instance_id="client-profile", client_id="acme")
    msp_profile = _instance(instance_id="msp-profile")
    store = _Store([msp_profile, client_profile])
    resolver = M365ConnectionResolver(
        replace(settings, m365_graph_base_url="https://graph.microsoft.com/v1.0", m365_access_token="env-value"),
        store,
        _Vault([msp_profile, client_profile]),
    )

    assert resolver.resolve("acme").profile_id == "client-profile"
    assert resolver.resolve("other", allow_msp_wide=True).profile_id == "msp-profile"
    assert resolver.resolve("other", allow_msp_wide=True).tier == "MSP-wide"
    assert resolver.resolve("acme").token_provider is resolver.resolve("acme").token_provider

    store.instances = []
    with pytest.raises(M365ProfileResolutionError, match="client-scoped.*acme"):
        resolver.resolve("acme")
    fallback = resolver.resolve("acme", allow_msp_wide=True)
    assert fallback.profile_id is None
    assert fallback.tier == "environment"
    assert fallback.token_provider.get_token() == "env-value"


def test_resolver_reports_client_and_msp_profile_tiers(settings) -> None:
    client_profile = _instance(instance_id="client-profile", client_id="acme")
    msp_profile = _instance(instance_id="msp-profile")
    resolver = M365ConnectionResolver(
        settings,
        _Store([client_profile, msp_profile]),
        _Vault([client_profile, msp_profile]),
    )

    assert resolver.resolve("acme").tier == "client-scoped"
    assert resolver.resolve().tier == "MSP-wide"


def test_resolver_fails_closed_on_same_tier_ambiguity(settings) -> None:
    first = _instance(instance_id="msp-one")
    second = _instance(instance_id="msp-two")
    with pytest.raises(M365ProfileResolutionError, match="ambiguous"):
        M365ConnectionResolver(settings, _Store([first, second]), _Vault([first, second])).resolve()


def test_graph_and_admin_clients_share_profile_connection_and_fixed_origin(settings) -> None:
    connection = M365Connection(
        graph_base_url="https://graph.microsoft.com/v1.0",
        token_provider=M365TokenProvider.from_static_token("profile-value"),
    )
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers["Authorization"]))
        return httpx.Response(200, json={"value": []})

    transport = httpx.MockTransport(handler)
    graph = M365GraphClient(replace(settings, allow_http_probing=True), connection=connection, transport=transport)
    admin = MicrosoftAdminGraphClient(
        replace(settings, allow_http_probing=True), connection=connection, transport=transport
    )
    assert graph.list_users().result.status == "ready"
    assert admin.list_service_health().result.status == "ready"
    assert all(url.startswith("https://graph.microsoft.com/v1.0/") for url, _ in seen)
    assert all(auth == "Bearer profile-value" for _, auth in seen)
