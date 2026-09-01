from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient

import wait_local_agent.api.auth_routes as auth_routes
from wait_local_agent.api.app import create_app
from wait_local_agent.oidc import (
    OidcConfig,
    build_oauth_client,
    get_or_create_session_signing_key,
    load_oidc_config,
    resolve_identity,
    validate_next_path,
)
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault, SecretVaultError


def _oidc_settings(settings, tmp_path, monkeypatch):
    monkeypatch.setenv("WAIT_VAULT_KEY", Fernet.generate_key().decode())
    return replace(
        settings,
        demo_mode=False,
        admin_token="bootstrap-admin",
        session_cookie_secure=False,
        secrets_backend="fernet",
        vault_path=tmp_path / "vault",
    )


def _configure(store: Store, vault: SecretVault, *, auto=False, client_id="alpha") -> OidcConfig:
    vault.set("WAIT_OIDC_CLIENT_SECRET", "oidc-fixture-config")
    for key, value in {
        "oidc.enabled": "true",
        "oidc.tenant_id": "tenant.example",
        "oidc.client_id": "application-id",
        "oidc.public_base_url": "http://testserver",
        "oidc.auto_provision_enabled": "true" if auto else "false",
        "oidc.auto_provision_tenant_id": "tenant.example",
        "oidc.auto_provision_client_id": client_id,
    }.items():
        store.set_app_config(key, value)
    return load_oidc_config(replace(_settings_stub(), client_id=client_id), store, vault)


def _settings_stub():
    from wait_local_agent.config import Settings

    return Settings(
        data_path=Path("state.db"),
        allowed_doc_root=Path("."),
        allow_write_actions=False,
        allow_http_probing=False,
        allow_cloud_fallback=False,
        allow_llm_inference=False,
        local_model_provider="deterministic",
        local_model_base_url="http://127.0.0.1:11434/v1",
        local_model_name="local",
        local_model_timeout_seconds=20,
        vector_backend="sqlite",
    )


@pytest.mark.parametrize(
    "raw",
    ["//evil.example", "https://evil.example", r"/ok\\next", "/%5C%5Cevil", "/foo%3A%2F%2Fevil"],
)
def test_validate_next_path_rejects_open_redirect_forms(raw: str) -> None:
    with pytest.raises(ValueError):
        validate_next_path(raw)


def test_validate_next_path_accepts_application_path() -> None:
    assert validate_next_path("/settings/access") == "/settings/access"
    assert validate_next_path(None) == "/"


def test_validate_next_path_allows_a_path_after_decode_loop_exhaustion() -> None:
    raw = "/%2525252525safe"

    assert validate_next_path(raw) == raw


def test_oidc_config_properties_and_oauth_client_are_derived_without_network() -> None:
    config = OidcConfig(
        tenant_id="tenant.example",
        client_id="application-id",
        public_base_url="https://console.example/",
        client_secret="sample-oidc-value",
        enabled=True,
    )

    assert config.issuer == "https://login.microsoftonline.com/tenant.example/v2.0"
    assert config.metadata_url.endswith("/.well-known/openid-configuration")
    assert config.redirect_uri == "https://console.example/auth/oidc/callback"
    assert config.client_secret_configured is True
    assert config.complete is True
    assert build_oauth_client(config) is not None

    incomplete = replace(config, client_secret="", public_base_url="console.example")
    assert incomplete.client_secret_configured is False
    assert incomplete.complete is False


def test_load_oidc_config_uses_settings_defaults_and_fails_closed_for_vault_error(
    settings, tmp_path, monkeypatch
) -> None:
    store = Store(tmp_path / "state.db")
    vault = SecretVault(tmp_path / "vault")
    defaults = replace(
        settings,
        oidc_tenant_id="tenant.example",
        oidc_client_id="application-id",
        oidc_public_base_url="https://console.example/",
        oidc_auto_provision_client_id="client-from-settings",
    )

    loaded = load_oidc_config(defaults, store, vault)

    assert loaded.tenant_id == "tenant.example"
    assert loaded.client_id == "application-id"
    assert loaded.public_base_url == "https://console.example"
    assert loaded.auto_provision_client_id == "client-from-settings"
    assert loaded.enabled is False

    def fail_get(_self, _key):
        raise SecretVaultError("sample vault failure")

    monkeypatch.setattr(SecretVault, "get", fail_get)
    failed = load_oidc_config(defaults, store, vault)
    assert failed.client_secret == ""


def test_session_signing_key_fails_for_fernet_vault_and_is_ephemeral_for_env(settings, monkeypatch) -> None:
    def fail_initialized(_self):
        raise SecretVaultError("sample vault unavailable")

    monkeypatch.setattr(SecretVault, "is_initialized", fail_initialized)
    vault = SecretVault(Path("sample-vault"))

    with pytest.raises(SecretVaultError):
        get_or_create_session_signing_key(replace(settings, secrets_backend="fernet"), vault)

    ephemeral = get_or_create_session_signing_key(replace(settings, secrets_backend="env"), vault)
    assert ephemeral


def test_oidc_status_and_disabled_login_callback_are_fail_closed(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    app = create_app(secure)
    del app.state.vault
    client = TestClient(app)

    assert client.get("/auth/oidc/status").json() == {"enabled": False}
    login = client.get("/auth/oidc/login", follow_redirects=False)
    callback = client.get("/auth/oidc/callback", follow_redirects=False)
    assert login.status_code == 404
    assert callback.status_code == 404


def test_oidc_login_rejects_bad_next_and_hides_authorize_failure(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    _configure(store, vault)
    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: object())
    client = TestClient(create_app(secure))

    bad_next = client.get("/auth/oidc/login?next=https://evil.example", follow_redirects=False)
    assert bad_next.status_code == 400

    class FailingClient:
        async def authorize_redirect(self, request, redirect_uri):
            raise RuntimeError("sample provider failure")

    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: FailingClient())
    failed = client.get("/auth/oidc/login?next=/settings", follow_redirects=False)
    assert failed.status_code == 502
    assert failed.json()["detail"] == "Microsoft sign-in is unavailable"


@pytest.mark.parametrize(
    ("token", "expected_detail"),
    [
        ("sample-provider-error", "Microsoft sign-in could not be completed"),
        ("sample-state-error", "invalid sign-in transaction"),
        ("sample-non-dict-token", "Microsoft sign-in returned no identity"),
        ({"userinfo": "sample-non-dict-claims"}, "Microsoft sign-in returned no identity"),
    ],
)
def test_oidc_callback_maps_provider_and_claim_errors(settings, tmp_path, monkeypatch, token, expected_detail) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)

    class FailingClient:
        async def authorize_access_token(self, request):
            if token == "sample-provider-error":
                raise RuntimeError("sample provider response failure")
            if token == "sample-state-error":
                class MismatchingStateError(Exception):
                    pass

                raise MismatchingStateError("sample state mismatch")
            return token

    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: FailingClient())
    response = TestClient(create_app(secure)).get("/auth/oidc/callback", follow_redirects=False)
    assert response.status_code == 400
    assert response.json()["detail"] == expected_detail
    assert config.tenant_id


def test_oidc_callback_rejects_issuer_mismatch(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)

    class StubClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"tid": config.tenant_id, "iss": "https://issuer.example", "oid": "object-issuer"}}

    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: StubClient())
    response = TestClient(create_app(secure)).get("/auth/oidc/callback", follow_redirects=False)
    assert response.status_code == 403


def test_oidc_auto_provision_guard_rejects_disabled_and_unknown_client(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault, auto=True)

    assert resolve_identity(
        store,
        {"tid": config.tenant_id, "oid": "object-disabled"},
        replace(config, auto_provision_enabled=False),
    ) is None
    assert resolve_identity(
        store,
        {"tid": config.tenant_id, "oid": "object-unknown-client"},
        replace(config, auto_provision_client_id="missing-client"),
    ) is None

    assert resolve_identity(store, {"tid": config.tenant_id}, config) is None
    assert resolve_identity(
        store,
        {"tid": config.tenant_id, "oid": "object-no-invite", "email": "nobody@example.test"},
        replace(config, auto_provision_enabled=False),
    ) is None


def test_oidc_auto_provision_handles_concurrent_identity_creation(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault, auto=True)

    def fail_add_identity(*args, **kwargs):
        raise sqlite3.IntegrityError("sample concurrent identity")

    calls = 0

    def find_existing(*args, **kwargs):
        nonlocal calls
        calls += 1
        return None if calls == 1 else "operator"

    monkeypatch.setattr(Store, "add_principal_identity", fail_add_identity)
    monkeypatch.setattr(Store, "find_principal_by_identity", find_existing)

    assert resolve_identity(store, {"tid": config.tenant_id, "oid": "object-concurrent"}, config) == "operator"


def test_oidc_auto_provision_returns_none_when_concurrent_identity_is_missing(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault, auto=True)

    def fail_add_identity(*args, **kwargs):
        raise sqlite3.IntegrityError("sample concurrent identity")

    monkeypatch.setattr(Store, "add_principal_identity", fail_add_identity)
    monkeypatch.setattr(Store, "find_principal_by_identity", lambda *args, **kwargs: None)

    assert resolve_identity(store, {"tid": config.tenant_id, "oid": "object-lost"}, config) is None


def test_oidc_config_routes_store_secret_and_round_trip_auto_provision_fields(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    client = TestClient(create_app(secure))
    payload = {
        "enabled": True,
        "tenant_id": "tenant.example",
        "client_id": "application-id",
        "public_base_url": "http://testserver/",
        "client_secret": "sample-oidc-value",
        "auto_provision_enabled": True,
        "auto_provision_tenant_id": "tenant.example",
        "auto_provision_client_id": "alpha",
    }

    incomplete = client.put(
        "/auth/oidc/config",
        headers={"Authorization": "Bearer bootstrap-admin"},
        json={"enabled": True},
    )
    assert incomplete.status_code == 422

    saved = client.put("/auth/oidc/config", headers={"Authorization": "Bearer bootstrap-admin"}, json=payload)
    assert saved.status_code == 200
    assert saved.json()["auto_provision_enabled"] is True
    assert saved.json()["auto_provision_tenant_id"] == "tenant.example"
    assert saved.json()["auto_provision_client_id"] == "alpha"
    assert saved.json()["client_secret_configured"] is True
    assert SecretVault(secure.vault_path).get("WAIT_OIDC_CLIENT_SECRET") == "sample-oidc-value"

    fetched = client.get("/auth/oidc/config", headers={"Authorization": "Bearer bootstrap-admin"})
    assert fetched.status_code == 200
    assert fetched.json() == saved.json()
    assert client.get("/auth/oidc/status").json() == {"enabled": True}


def test_oidc_config_and_identity_routes_enforce_access_and_link_identities(settings, tmp_path, monkeypatch) -> None:
    secure = replace(_oidc_settings(settings, tmp_path, monkeypatch), viewer_token="sample-viewer-token")
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_principal("operator", kind="staff", display_name="Operator")
    store.add_principal_global_role("operator")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)
    client = TestClient(create_app(secure))
    admin_headers = {"Authorization": "Bearer bootstrap-admin"}
    viewer_headers = {"Authorization": "Bearer sample-viewer-token"}
    identity = {"subject": "object-route", "subject_kind": "oid"}

    assert client.get("/auth/oidc/config", headers=viewer_headers).status_code == 403
    assert client.put("/auth/oidc/config", headers=viewer_headers, json={}).status_code == 403
    assert client.post("/auth/principals/missing/identities", headers=admin_headers, json=identity).status_code == 404
    assert (
        client.post(
            "/auth/principals/operator/identities",
            headers=admin_headers,
            json={**identity, "issuer": "https://other-issuer.example"},
        ).status_code
        == 422
    )

    added = client.post("/auth/principals/operator/identities", headers=admin_headers, json=identity)
    assert added.status_code == 200
    assert added.json()["identities"][0]["subject"] == "object-route"
    assert (
        client.post("/auth/principals/operator/identities", headers=admin_headers, json=identity).status_code == 409
    )
    removed = client.request("DELETE", "/auth/principals/operator/identities", headers=admin_headers, json=identity)
    assert removed.status_code == 200
    removed_again = client.request(
        "DELETE", "/auth/principals/operator/identities", headers=admin_headers, json=identity
    )
    assert removed_again.status_code == 404
    assert config.issuer


def test_identity_routes_map_store_value_error_and_reject_remove_issuer(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_principal("operator", kind="staff", display_name="Operator")
    store.add_principal_global_role("operator")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)
    client = TestClient(create_app(secure))
    headers = {"Authorization": "Bearer bootstrap-admin"}
    original_add_identity = Store.add_principal_identity

    def fail_add(*args, **kwargs):
        raise ValueError("sample identity failure")

    monkeypatch.setattr(Store, "add_principal_identity", fail_add)
    response = client.post(
        "/auth/principals/operator/identities",
        headers=headers,
        json={"subject": "object-failure", "subject_kind": "oid"},
    )
    assert response.status_code == 422

    monkeypatch.setattr(Store, "add_principal_identity", original_add_identity)
    store.add_principal_identity("operator", config.issuer, "object-remove-issuer", "oid")
    removed = client.request(
        "DELETE",
        "/auth/principals/operator/identities",
        headers=headers,
        json={"subject": "object-remove-issuer", "subject_kind": "oid", "issuer": "https://other-issuer.example"},
    )
    assert removed.status_code == 422


def test_linked_oidc_callback_mints_existing_session(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_principal("operator", kind="staff", display_name="Operator")
    store.add_principal_global_role("operator")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    _configure(store, vault)
    config = _configure(store, vault)

    class StubClient:
        async def authorize_redirect(self, request, redirect_uri):
            request.session["stub_state"] = "present"
            return RedirectResponse(f"https://login.example/authorize?state=present&redirect_uri={redirect_uri}")

        async def authorize_access_token(self, request):
            return {"userinfo": {"tid": config.tenant_id, "iss": config.issuer, "oid": "object-1", "sub": "subject-1"}}

    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: StubClient())
    store.add_principal_identity("operator", config.issuer, "object-1", "oid")
    client = TestClient(create_app(secure))

    login = client.get("/auth/oidc/login?next=/settings/access", follow_redirects=False)
    assert login.status_code == 307
    assert parse_qs(urlsplit(login.headers["location"]).query)["state"] == ["present"]

    callback = client.get("/auth/oidc/callback?code=opaque-code&state=present", follow_redirects=False)
    assert callback.status_code == 303
    assert callback.headers["location"] == "/settings/access"
    assert "wait_session=" in callback.headers["set-cookie"]


def test_unknown_identity_fails_closed_and_does_not_create_principal(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_principal("operator", kind="staff", display_name="Operator")
    store.add_principal_global_role("operator")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)

    class StubClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"tid": config.tenant_id, "iss": config.issuer, "oid": "unknown-object"}}

    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: StubClient())
    client = TestClient(create_app(secure))
    response = client.get("/auth/oidc/callback?code=opaque-code&state=anything", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/#/login?error=not_provisioned"
    assert store.find_principal_by_identity(config.issuer, "unknown-object", "oid") is None


def test_email_invite_is_consumed_and_upgraded_to_oid(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_principal("operator", kind="staff", display_name="Operator")
    store.add_principal_global_role("operator")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)
    store.add_principal_identity("operator", config.issuer, "person@example.test", "email")

    assert resolve_identity(
        store,
        {"tid": config.tenant_id, "oid": "object-2", "preferred_username": "PERSON@example.test"},
        config,
    ) == "operator"
    assert store.find_principal_by_identity(config.issuer, "person@example.test", "email") is None
    assert store.find_principal_by_identity(config.issuer, "object-2", "oid") == "operator"


def test_tid_mismatch_is_rejected(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_principal("operator", kind="staff", display_name="Operator")
    store.add_principal_global_role("operator")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault)

    class StubClient:
        async def authorize_access_token(self, request):
            return {"userinfo": {"tid": "different-tenant", "iss": config.issuer, "oid": "object-3"}}

    monkeypatch.setattr(auth_routes, "build_oauth_client", lambda _config: StubClient())
    response = TestClient(create_app(secure)).get("/auth/oidc/callback?code=opaque-code&state=anything")
    assert response.status_code == 403


def test_auto_provision_requires_matching_tenant_and_adds_viewer(settings, tmp_path, monkeypatch) -> None:
    secure = _oidc_settings(settings, tmp_path, monkeypatch)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    vault = SecretVault.initialize(secure.vault_path, demo_mode=False)
    config = _configure(store, vault, auto=True)
    principal_id = resolve_identity(
        store,
        {"tid": config.tenant_id, "oid": "object-4", "name": "New Operator"},
        config,
    )
    assert principal_id is not None
    record = store.find_principal_auth_record(principal_id)
    assert record is not None
    assert record.client_roles == (("alpha", "viewer"),)

    rejected = replace(config, auto_provision_tenant_id="other-tenant")
    assert resolve_identity(store, {"tid": config.tenant_id, "oid": "object-5"}, rejected) is None
