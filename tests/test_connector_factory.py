from __future__ import annotations

import json
import socket
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import httpx
import pytest

from wait_local_agent import connector_factory, net_security
from wait_local_agent.autotask import AutotaskClient
from wait_local_agent.connector_factory import (
    _BUILDERS,
    _SECRET_SETTING_FIELDS,
    ConnectorFactoryError,
    _api_base_url,
    _validate_urls,
    build_read_client,
    build_read_client_for,
    build_read_client_for_client,
    validate_connector_instance,
)
from wait_local_agent.connectwise import ConnectWiseClient
from wait_local_agent.dattormm import DattoRmmAdapter
from wait_local_agent.models import ConnectorInstance
from wait_local_agent.ncentral import NCentralRmmAdapter
from wait_local_agent.ninjaone import NinjaOneRmmAdapter
from wait_local_agent.servicenow import ServiceNowClient
from wait_local_agent.syncro import SyncroClient


def _instance(
    *,
    connector_type: str = "halopsa",
    status: str = "active",
    credential_ref: str | None = "credential-ref",
    client_id: str | None = None,
    config: Mapping[str, object] | None = None,
) -> ConnectorInstance:
    return ConnectorInstance(
        connector_instance_id="instance-1",
        connector_type=connector_type,
        display_name="Test connector",
        client_id=client_id,
        credential_ref=credential_ref,
        config_json=json.dumps(
            {"base_url": "https://provider.example.test"} if config is None else config
        ),
        status=status,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


class _Vault:
    def __init__(self, secret: object = None) -> None:
        self.secret = secret
        self.keys: list[str] = []

    def get(self, key: str) -> object:
        self.keys.append(key)
        return self.secret


def _resolver(*addresses: str):
    def resolve(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        del kwargs
        port = args[1] if len(args) > 1 else 443
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                (address, port, 0, 0) if ":" in address else (address, port),
            )
            for address in addresses
        ]

    return resolve


def _base_settings(settings, tmp_path: Path, *, allow_write_actions: bool = False):
    return replace(
        settings,
        allow_http_probing=True,
        allow_write_actions=allow_write_actions,
        connector_timeout_seconds=7.0,
        connector_instance_allowed_hosts=("provider.example.test",),
        vault_path=tmp_path / "vault",
    )


def _halo_secret(**overrides: str) -> str:
    payload = {"client_id": "instance-client", "client_secret": "instance-secret", "tenant": "instance-tenant"}
    payload.update(overrides)
    return json.dumps(payload)


def _connectwise_secret(**overrides: str) -> str:
    payload = {
        "company": "instance-company",
        "public_key": "instance-public",
        "private_key": "instance-private",
        "client_id": "instance-client",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _autotask_secret(**overrides: str) -> str:
    payload = {"integration_code": "fixture-integration", "username": "fixture-user", "secret": "fixture-value"}
    payload.update(overrides)
    return json.dumps(payload)


def _syncro_secret(**overrides: str) -> str:
    payload = {"api_key": "fixture-key", "subdomain": "fixture-subdomain"}
    payload.update(overrides)
    return json.dumps(payload)


def _servicenow_secret(**overrides: str) -> str:
    payload = {"username": "fixture-user", "password": "fixture-value"}
    payload.update(overrides)
    return json.dumps(payload)


def _rmm_secret(**overrides: str) -> str:
    payload = {"access_token": "fixture-access-value"}
    payload.update(overrides)
    return json.dumps(payload)


def _m365_secret(**overrides: str) -> str:
    payload = {"mode": "static_token", "access_token": "profile-value"}
    payload.update(overrides)
    return json.dumps(payload)


def test_active_gate_precedes_vault_for_all_inactive_states(settings, tmp_path: Path) -> None:
    for status in ("inactive", "disabled", "error"):
        vault = _Vault()
        with pytest.raises(ConnectorFactoryError, match="not active"):
            build_read_client(
                _instance(status=status),
                base_settings=_base_settings(settings, tmp_path),
                vault=vault,
            )
        assert vault.keys == []


def test_unknown_type_does_not_fall_back_to_global_settings(settings, tmp_path: Path) -> None:
    vault = _Vault(_halo_secret())
    with pytest.raises(ConnectorFactoryError, match="unsupported connector_type"):
        build_read_client(
            _instance(connector_type="unknown"),
            base_settings=_base_settings(settings, tmp_path),
            vault=vault,
        )
    assert vault.keys == []


@pytest.mark.parametrize("credential_ref", [None, "", "   "])
def test_missing_credential_ref_is_rejected(settings, tmp_path: Path, credential_ref: str | None) -> None:
    with pytest.raises(ConnectorFactoryError, match="credential reference"):
        build_read_client(
            _instance(credential_ref=credential_ref),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )


@pytest.mark.parametrize("secret", [None, "", "not-json", "[]", '{"client_id":"a","client_id":"b"}'])
def test_vault_payloads_fail_closed_without_echoing_secret_data(settings, tmp_path: Path, secret: object) -> None:
    with pytest.raises(ConnectorFactoryError) as error:
        build_read_client(
            _instance(),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(secret),
        )
    assert "instance-secret" not in str(error.value)
    assert str(error.value) in {
        "connector credentials were not found",
        "connector credentials must be valid JSON",
        "connector credentials must be a JSON object",
    }


def test_vault_exception_is_fixed_and_chained(settings, tmp_path: Path) -> None:
    class FailingVault:
        def get(self, key: str) -> str:
            raise RuntimeError("/private/vault/path and secret-value")

    with pytest.raises(ConnectorFactoryError) as error:
        build_read_client(
            _instance(),
            base_settings=_base_settings(settings, tmp_path),
            vault=FailingVault(),
        )
    assert str(error.value) == "connector credentials could not be read"
    assert error.value.__cause__ is not None
    assert "/private/vault/path" not in str(error.value)


@pytest.mark.parametrize(
    "secret",
    [
        json.dumps({"client_id": "a", "client_secret": "b"}),
        json.dumps({"client_id": "a", "client_secret": "b", "tenant": "c", "extra": "d"}),
        json.dumps({"client_id": "a", "client_secret": "b", "tenant": "   "}),
        json.dumps({"client_id": "a", "client_secret": False, "tenant": "c"}),
    ],
)
def test_halo_schema_is_exact_and_values_are_strings(settings, tmp_path: Path, secret: str) -> None:
    with pytest.raises(ConnectorFactoryError, match="expected keys: client_id, client_secret, tenant"):
        build_read_client(
            _instance(),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(secret),
        )


def test_secret_bytes_are_not_trimmed(settings, tmp_path: Path) -> None:
    secret = _halo_secret(client_id="  meaningful-client  ")
    client = build_read_client(
        _instance(),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(secret),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    assert client.settings.halopsa_client_id == "  meaningful-client  "


@pytest.mark.parametrize(
    "missing",
    ["company", "public_key", "private_key", "client_id"],
)
def test_connectwise_requires_all_credential_fields(settings, tmp_path: Path, missing: str) -> None:
    payload = json.loads(_connectwise_secret())
    del payload[missing]
    with pytest.raises(ConnectorFactoryError, match="expected keys: company, public_key, private_key, client_id"):
        build_read_client(
            _instance(connector_type="connectwise"),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(json.dumps(payload)),
        )


def test_config_rejects_secret_fields_and_token_url(settings, tmp_path: Path) -> None:
    for config in (
        {"base_url": "https://provider.example.test", "token_url": "https://other.example.test"},
        {"base_url": "https://provider.example.test", "nested": {"private_key": "secret"}},
    ):
        with pytest.raises(ConnectorFactoryError, match="must not contain credentials"):
            build_read_client(
                _instance(config=config),
                base_settings=_base_settings(settings, tmp_path),
                vault=_Vault(_halo_secret()),
            )


@pytest.mark.parametrize("config_json", ["not-json", "[]"])
def test_config_json_must_be_an_object(settings, tmp_path: Path, config_json: str) -> None:
    with pytest.raises(ConnectorFactoryError):
        build_read_client(
            replace(_instance(), config_json=config_json),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )


@pytest.mark.parametrize(
    "config",
    [{"base_url": "https://provider.example.test", "unexpected": "value"}, {"unexpected": "value"}],
)
def test_config_json_requires_only_supported_fields(settings, tmp_path: Path, config: Mapping[str, object]) -> None:
    with pytest.raises(ConnectorFactoryError):
        build_read_client(
            _instance(config=config),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )


def test_config_json_requires_nonempty_base_url(settings, tmp_path: Path) -> None:
    with pytest.raises(ConnectorFactoryError, match="requires a base_url"):
        build_read_client(
            _instance(config={"base_url": "   "}),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )


@pytest.mark.parametrize(
    ("connector_type", "requires_base_url"),
    [
        (connector_type, connector_type not in {"syncro", "m365"})
        for connector_type in sorted(_BUILDERS)
    ],
)
def test_config_base_url_requirement_is_per_connector_type(
    connector_type: str, requires_base_url: bool
) -> None:
    if requires_base_url:
        with pytest.raises(ConnectorFactoryError, match="requires a base_url"):
            connector_factory._load_config(
                _instance(connector_type=connector_type, config={}),
                connector_type=connector_type,
            )
    else:
        assert connector_factory._load_config(
            _instance(connector_type=connector_type, config={}),
            connector_type=connector_type,
        ) == {}


@pytest.mark.parametrize(
    "config",
    [
        {"base_url": "https://provider.example.test", "organization_map_json": ""},
        {"base_url": "https://provider.example.test", "organization_map_json": "not-json"},
        {"base_url": "https://provider.example.test", "organization_map_json": "[]"},
        {"base_url": "https://provider.example.test", "page_size": 0},
        {"base_url": "https://provider.example.test", "page_size": True},
    ],
)
def test_rmm_config_rejects_invalid_tenant_maps_and_page_sizes(config: Mapping[str, object]) -> None:
    with pytest.raises(ConnectorFactoryError, match="invalid"):
        connector_factory._load_config(
            _instance(connector_type="ninjaone", config=config),
            connector_type="ninjaone",
        )


def test_base_origin_allowlist_and_same_origin_token_are_enforced(settings, tmp_path: Path, monkeypatch) -> None:
    with pytest.raises(ConnectorFactoryError, match="network policy"):
        build_read_client(
            _instance(config={"base_url": "https://not-allowed.example.test"}),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )

    original = net_security.validate_provider_origin
    calls = 0

    def different_token_origin(url: str, *, allowed_hosts: tuple[str, ...], allow_loopback: bool = False):
        nonlocal calls
        calls += 1
        if calls == 2:
            return httpx.URL("https://other.example.test/auth/token")
        return original(url, allowed_hosts=allowed_hosts, allow_loopback=allow_loopback)

    monkeypatch.setattr(connector_factory, "validate_provider_origin", different_token_origin)
    with pytest.raises(ConnectorFactoryError, match="token origin"):
        build_read_client(
            _instance(),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )


def test_isolation_inherits_operational_fields_and_downgrades_writes(settings, tmp_path: Path) -> None:
    base = _base_settings(settings, tmp_path, allow_write_actions=True)
    base = replace(base, **{name: "global-sentinel" for name in _SECRET_SETTING_FIELDS})
    client = build_read_client(
        _instance(),
        base_settings=base,
        vault=_Vault(_halo_secret()),
    )

    assert client.settings.allow_write_actions is False
    assert client.settings.halopsa_ticket_write_endpoint == ""
    assert client.settings.halopsa_action_write_endpoint == ""
    assert client.settings.allow_http_probing == base.allow_http_probing
    assert client.settings.connector_timeout_seconds == base.connector_timeout_seconds
    assert client.settings.connector_instance_allowed_hosts == base.connector_instance_allowed_hosts
    assert client.settings.vault_path == base.vault_path
    assert all(getattr(client.settings, name) != "global-sentinel" for name in _SECRET_SETTING_FIELDS)
    assert client.settings.halopsa_client_id == "instance-client"
    assert client.settings.halopsa_client_secret == "instance-secret"
    assert client.settings.halopsa_tenant == "instance-tenant"
    assert client.settings.halopsa_token_url == ""


@pytest.mark.parametrize("config_version", ["not-a-version", "2022", "2022.1.2", 2022.1])
def test_connectwise_effective_api_version_is_validated(settings, tmp_path: Path, config_version: object) -> None:
    config = {"base_url": "https://provider.example.test", "api_version": config_version}
    with pytest.raises(ConnectorFactoryError, match="API version"):
        build_read_client(
            _instance(connector_type="connectwise", config=config),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_connectwise_secret()),
        )


def test_connectwise_inherited_api_version_is_validated(settings, tmp_path: Path) -> None:
    base = replace(_base_settings(settings, tmp_path), connectwise_api_version="invalid")
    with pytest.raises(ConnectorFactoryError, match="API version"):
        build_read_client(
            _instance(connector_type="connectwise"),
            base_settings=base,
            vault=_Vault(_connectwise_secret()),
        )

    base = replace(_base_settings(settings, tmp_path), connectwise_api_version=None)
    with pytest.raises(ConnectorFactoryError, match="API version"):
        build_read_client(
            _instance(connector_type="connectwise"),
            base_settings=base,
            vault=_Vault(_connectwise_secret()),
        )


def test_provider_base_url_suffixes_are_preserved(settings, tmp_path: Path) -> None:
    halo = build_read_client(
        _instance(config={"base_url": "https://provider.example.test/api"}),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_halo_secret()),
    )
    cw = build_read_client(
        _instance(
            connector_type="connectwise",
            config={"base_url": "https://provider.example.test/v4_6_release/apis/3.0"},
        ),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_connectwise_secret()),
    )
    assert halo.settings.halopsa_base_url.endswith("/api")
    assert cw.settings.connectwise_base_url.endswith("/v4_6_release/apis/3.0")


@pytest.mark.parametrize(
    "connector_type,secret,expected_type,expected_fields",
    [
        (
            "autotask",
            _autotask_secret(),
            AutotaskClient,
            {
                "autotask_base_url": "https://provider.example.test",
                "autotask_username": "fixture-user",
                "autotask_secret": "fixture-value",
                "autotask_integration_code": "fixture-integration",
            },
        ),
        (
            "syncro",
            _syncro_secret(),
            SyncroClient,
            {"syncro_base_url": "https://provider.example.test", "syncro_api_token": "fixture-key"},
        ),
        (
            "servicenow",
            _servicenow_secret(),
            ServiceNowClient,
            {
                "servicenow_base_url": "https://provider.example.test",
                "servicenow_username": "fixture-user",
                "servicenow_password": "fixture-value",
                "servicenow_api_version": "v1",
            },
        ),
    ],
)
def test_new_instance_backed_providers_build_read_only_clients(
    settings,
    tmp_path: Path,
    connector_type: str,
    secret: str,
    expected_type: type,
    expected_fields: Mapping[str, str],
) -> None:
    config = {"base_url": "https://provider.example.test"}
    if connector_type == "servicenow":
        config["api_version"] = "v1"
    client = build_read_client(
        _instance(connector_type=connector_type, config=config),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(secret),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    assert isinstance(client, expected_type)
    assert client.settings.allow_write_actions is False
    for field_name, value in expected_fields.items():
        assert getattr(client.settings, field_name) == value


def test_m365_instance_builds_with_fixed_graph_origin_and_profile_token(settings, tmp_path: Path) -> None:
    instance = _instance(connector_type="m365", config={})
    client = build_read_client(
        instance,
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_m365_secret()),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []})),
    )
    assert client.settings.m365_graph_base_url == "https://graph.microsoft.com/v1.0"
    assert client.settings.m365_access_token == "profile-value"
    assert isinstance(client, connector_factory.M365GraphClient)
    validate_connector_instance(
        instance,
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_m365_secret()),
    )


@pytest.mark.parametrize(
    "connector_type,config,expected_type,expected_fields",
    [
        (
            "ninjaone",
            {
                "base_url": "https://provider.example.test/api/v2",
                "organization_map_json": '{"acme":42}',
                "page_size": 25,
            },
            NinjaOneRmmAdapter,
            {
                "ninjaone_base_url": "https://provider.example.test/api/v2",
                "ninjaone_access_token": "fixture-access-value",
                "ninjaone_organization_map_json": '{"acme":42}',
                "ninjaone_page_size": 25,
            },
        ),
        (
            "dattormm",
            {
                "base_url": "https://provider.example.test/api",
                "site_map_json": '{"acme":"site-42"}',
                "page_size": 25,
            },
            DattoRmmAdapter,
            {
                "datto_rmm_base_url": "https://provider.example.test/api",
                "datto_rmm_access_token": "fixture-access-value",
                "datto_rmm_site_map_json": '{"acme":"site-42"}',
                "datto_rmm_page_size": 25,
            },
        ),
        (
            "ncentral",
            {
                "base_url": "https://provider.example.test",
                "org_unit_map_json": '{"acme":[100]}',
                "page_size": 25,
            },
            NCentralRmmAdapter,
            {
                "ncentral_base_url": "https://provider.example.test",
                "ncentral_access_token": "fixture-access-value",
                "ncentral_org_unit_map_json": '{"acme":[100]}',
                "ncentral_page_size": 25,
            },
        ),
    ],
)
def test_rmm_instance_backed_providers_build_read_only_clients(
    settings,
    tmp_path: Path,
    connector_type: str,
    config: Mapping[str, object],
    expected_type: type,
    expected_fields: Mapping[str, object],
) -> None:
    client = build_read_client(
        _instance(connector_type=connector_type, config=config),
        base_settings=_base_settings(settings, tmp_path, allow_write_actions=True),
        vault=_Vault(_rmm_secret()),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    assert isinstance(client, expected_type)
    assert client.settings.allow_write_actions is False
    for field_name, value in expected_fields.items():
        assert getattr(client.settings, field_name) == value


@pytest.mark.parametrize("connector_type", ["ninjaone", "dattormm", "ncentral"])
def test_rmm_instance_credentials_are_exact(settings, tmp_path: Path, connector_type: str) -> None:
    with pytest.raises(ConnectorFactoryError, match="expected keys: access_token"):
        build_read_client(
            _instance(connector_type=connector_type),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(json.dumps({"token": "fixture-value"})),
        )


@pytest.mark.parametrize(
    "connector_type,config",
    [
        ("ninjaone", {"base_url": "https://not-allowed.example.test", "organization_map_json": "{}"}),
        ("dattormm", {"base_url": "https://not-allowed.example.test", "site_map_json": "{}"}),
        ("ncentral", {"base_url": "https://not-allowed.example.test", "org_unit_map_json": "{}"}),
    ],
)
def test_rmm_instance_origins_use_the_allowlist(
    settings, tmp_path: Path, connector_type: str, config: Mapping[str, object]
) -> None:
    with pytest.raises(ConnectorFactoryError, match="network policy"):
        build_read_client(
            _instance(connector_type=connector_type, config=config),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_rmm_secret()),
        )


@pytest.mark.parametrize(
    "connector_type,secret,expected_message",
    [
        ("autotask", json.dumps({"integration_code": "a", "username": "b"}), "integration_code, username, secret"),
        ("syncro", json.dumps({"api_key": "a"}), "api_key, subdomain"),
        ("servicenow", json.dumps({"username": "a", "token": "b"}), "username, password"),
    ],
)
def test_new_provider_credentials_are_exact(
    settings,
    tmp_path: Path,
    connector_type: str,
    secret: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConnectorFactoryError, match=expected_message):
        build_read_client(
            _instance(connector_type=connector_type),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(secret),
        )


@pytest.mark.parametrize(
    "connector_type,secret,expected_message",
    [
        (
            "autotask",
            json.dumps({"integration_code": "fixture-code", "username": "fixture-user", "secret": 7}),
            "integration_code, username, secret",
        ),
        (
            "syncro",
            json.dumps({"api_key": "fixture-key", "subdomain": "fixture_subdomain"}),
            "api_key, subdomain",
        ),
        (
            "servicenow",
            json.dumps({"username": "fixture-user", "password": ""}),
            "username, password",
        ),
    ],
)
def test_new_provider_credential_values_are_nonempty_strings(
    settings,
    tmp_path: Path,
    connector_type: str,
    secret: str,
    expected_message: str,
) -> None:
    with pytest.raises(ConnectorFactoryError, match=expected_message):
        build_read_client(
            _instance(connector_type=connector_type),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(secret),
        )


def test_syncro_subdomain_builds_the_canonical_origin(settings, tmp_path: Path) -> None:
    base = replace(_base_settings(settings, tmp_path), connector_instance_allowed_hosts=("fixture.syncromsp.com",))
    client = build_read_client(
        _instance(connector_type="syncro", config={}),
        base_settings=base,
        vault=_Vault(_syncro_secret(subdomain="fixture")),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    assert isinstance(client, SyncroClient)
    assert client.settings.syncro_base_url == "https://fixture.syncromsp.com"


def test_syncro_rejects_invalid_derived_subdomain() -> None:
    with pytest.raises(ConnectorFactoryError, match="valid subdomain"):
        _validate_urls(
            {},
            connector_type="syncro",
            allowed_hosts=("fixture.syncromsp.com",),
            syncro_subdomain="fixture_subdomain",
        )


def test_api_base_url_adds_and_preserves_provider_suffix() -> None:
    assert _api_base_url("https://provider.example.test", connector_type="connectwise") == (
        "https://provider.example.test/v4_6_release/apis/3.0"
    )
    assert _api_base_url(
        "https://provider.example.test/v4_6_release/apis/3.0/",
        connector_type="connectwise",
    ) == "https://provider.example.test/v4_6_release/apis/3.0"


def test_servicenow_api_version_validation_rejects_non_strings_and_bad_values(settings, tmp_path: Path) -> None:
    for version in (7, "bad/version"):
        with pytest.raises(ConnectorFactoryError, match="ServiceNow API version is invalid"):
            build_read_client(
                _instance(
                    connector_type="servicenow",
                    config={"base_url": "https://provider.example.test", "api_version": version},
                ),
                base_settings=_base_settings(settings, tmp_path),
                vault=_Vault(_servicenow_secret()),
            )


def test_servicenow_api_version_validation_rejects_non_string_directly() -> None:
    with pytest.raises(ConnectorFactoryError, match="ServiceNow API version is invalid"):
        connector_factory._validate_servicenow_version(7)


@pytest.mark.parametrize(
    "connector_type,secret,config",
    [
        ("halopsa", _halo_secret(), {"base_url": "https://provider.example.test"}),
        ("connectwise", _connectwise_secret(), {"base_url": "https://provider.example.test"}),
        ("autotask", _autotask_secret(), {"base_url": "https://provider.example.test"}),
        ("syncro", _syncro_secret(), {"base_url": "https://provider.example.test"}),
        (
            "servicenow",
            _servicenow_secret(),
            {"base_url": "https://provider.example.test", "api_version": "v1"},
        ),
        (
            "ninjaone",
            _rmm_secret(),
            {
                "base_url": "https://provider.example.test",
                "organization_map_json": '{"acme":42}',
            },
        ),
        (
            "dattormm",
            _rmm_secret(),
            {"base_url": "https://provider.example.test", "site_map_json": '{"acme":"site-42"}'},
        ),
        (
            "ncentral",
            _rmm_secret(),
            {"base_url": "https://provider.example.test", "org_unit_map_json": '{"acme":[100]}'},
        ),
    ],
)
def test_validate_connector_instance_accepts_supported_providers(
    settings,
    tmp_path: Path,
    connector_type: str,
    secret: str,
    config: Mapping[str, object],
) -> None:
    validate_connector_instance(
        _instance(connector_type=connector_type, config=config),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(secret),
    )


def test_validate_connector_instance_rejects_unsupported_type(settings, tmp_path: Path) -> None:
    with pytest.raises(ConnectorFactoryError, match="unsupported connector_type"):
        validate_connector_instance(
            _instance(connector_type="unsupported"),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )


def test_invalid_base_url_type_is_fixed() -> None:
    with pytest.raises(ConnectorFactoryError, match="base_url is invalid"):
        _validate_urls(
            {"base_url": 123},
            connector_type="halopsa",
            allowed_hosts=("provider.example.test",),
        )


def test_pinned_factory_keeps_strict_https_policy() -> None:
    with pytest.raises(ConnectorFactoryError, match="network policy"):
        _validate_urls(
            {"base_url": "http://provider.example.test"},
            connector_type="halopsa",
            allowed_hosts=("provider.example.test",),
        )


def test_private_resolution_rejects_before_inner_transport(settings, tmp_path: Path) -> None:
    class FailingTransport(httpx.BaseTransport):
        def handle_request(self, request: httpx.Request) -> httpx.Response:
            raise AssertionError("inner transport must not be called")

        def close(self) -> None:
            return None

    client = build_read_client(
        _instance(connector_type="connectwise"),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_connectwise_secret()),
        resolver=_resolver("10.0.0.1"),
        inner_transport=FailingTransport(),
    )
    with pytest.raises(net_security.NetSecurityError):
        assert isinstance(client, ConnectWiseClient)
        client.list_companies()


def test_public_resolution_reaches_only_pinned_inner_transport(settings, tmp_path: Path) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    client = build_read_client(
        _instance(connector_type="connectwise"),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_connectwise_secret()),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(handler),
    )
    assert isinstance(client, ConnectWiseClient)
    result = client.list_companies()
    assert result.result.status == "ready"
    assert requests
    assert all(request.url.host == "8.8.8.8" for request in requests)


def test_client_construction_errors_are_fixed(settings, tmp_path: Path, monkeypatch) -> None:
    def factory_error(settings, transport):
        raise ConnectorFactoryError("fixed")

    def unexpected_error(settings, transport):
        raise RuntimeError("credential-value")

    monkeypatch.setitem(_BUILDERS, "halopsa", factory_error)
    with pytest.raises(ConnectorFactoryError, match="fixed"):
        build_read_client(
            _instance(),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )
    monkeypatch.setitem(_BUILDERS, "halopsa", unexpected_error)
    with pytest.raises(ConnectorFactoryError, match="could not be constructed") as error:
        build_read_client(
            _instance(),
            base_settings=_base_settings(settings, tmp_path),
            vault=_Vault(_halo_secret()),
        )
    assert "credential-value" not in str(error.value)


@pytest.mark.parametrize("connector_type,secret", [("halopsa", _halo_secret()), ("connectwise", _connectwise_secret())])
def test_both_supported_providers_build(settings, tmp_path: Path, connector_type: str, secret: str) -> None:
    client = build_read_client(
        _instance(connector_type=connector_type),
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(secret),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
    )
    assert client.settings.allow_write_actions is False
    assert isinstance(client.transport, net_security.PinnedIpTransport)


def test_build_read_client_for_repeats_active_gate(settings, tmp_path: Path) -> None:
    class Store:
        def list_connector_instances(self) -> list[ConnectorInstance]:
            return []

        def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance:
            assert connector_instance_id == "instance-1"
            return _instance(status="inactive")

    vault = _Vault()
    with pytest.raises(ConnectorFactoryError, match="not active"):
        build_read_client_for(
            Store(),
            "instance-1",
            base_settings=_base_settings(settings, tmp_path),
            vault=vault,
        )
    assert vault.keys == []


@pytest.mark.parametrize("stored", [None])
def test_build_read_client_for_handles_missing_instance(settings, tmp_path: Path, stored) -> None:
    class Store:
        def list_connector_instances(self) -> list[ConnectorInstance]:
            return []

        def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
            return stored

    with pytest.raises(ConnectorFactoryError, match="not found"):
        build_read_client_for(Store(), "missing", base_settings=_base_settings(settings, tmp_path))


def test_build_read_client_for_builds_loaded_instance(settings, tmp_path: Path) -> None:
    class Store:
        def list_connector_instances(self) -> list[ConnectorInstance]:
            return []

        def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance:
            assert connector_instance_id == "instance-1"
            return _instance()

    vault = _Vault(_halo_secret())
    client = build_read_client_for(
        Store(),
        "instance-1",
        base_settings=_base_settings(settings, tmp_path),
        vault=vault,
        resolver=_resolver("8.8.8.8"),
    )
    assert client.settings.halopsa_base_url == "https://provider.example.test"
    assert vault.keys == ["credential-ref"]


def test_build_read_client_for_redacts_store_errors(settings, tmp_path: Path) -> None:
    class Store:
        def list_connector_instances(self) -> list[ConnectorInstance]:
            return []

        def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
            raise RuntimeError("database path and secret")

    with pytest.raises(ConnectorFactoryError, match="could not be loaded") as error:
        build_read_client_for(Store(), "instance-1", base_settings=_base_settings(settings, tmp_path))
    assert "database path" not in str(error.value)


def test_build_read_client_for_client_allows_explicit_msp_wide_fallback(settings, tmp_path: Path) -> None:
    class Store:
        def list_connector_instances(self) -> list[ConnectorInstance]:
            return [_instance(connector_type="connectwise", client_id=None)]

        def get_connector_instance(self, connector_instance_id: str) -> ConnectorInstance | None:
            return _instance(connector_type="connectwise", client_id=None)

    client = build_read_client_for_client(
        Store(),
        "connectwise",
        "alpha",
        base_settings=_base_settings(settings, tmp_path),
        vault=_Vault(_connectwise_secret()),
        resolver=_resolver("8.8.8.8"),
        inner_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])),
        allow_msp_wide=True,
    )
    assert isinstance(client, ConnectWiseClient)
