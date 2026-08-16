from __future__ import annotations

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.migrations import Migration, MigrationRunner
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import (
    ClientConnectorMappingConflictError,
    Store,
    _normalize_client_id,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_clients_migration_repairs_and_backfills_existing_directory(tmp_path: Path) -> None:
    path = tmp_path / "state.db"
    store = Store(path)
    with store._connect() as connection:  # noqa: SLF001
        assert [tuple(row) for row in connection.execute("select version, name from schema_migrations")] == [
            (0, "baseline"),
            (1, "principals"),
            (2, "clients_and_connectors"),
        ]
        assert {
            str(row[0])
            for row in connection.execute(
                "select name from sqlite_master where type = 'table' and name in "
                "('clients', 'connector_instances', 'client_connector_mappings')"
            )
        } == {"clients", "connector_instances", "client_connector_mappings"}
        assert connection.execute(
            "select 1 from sqlite_master where type = 'index' and name = 'ux_ccm_verified'"
        ).fetchone() is not None
        assert connection.execute("pragma foreign_key_check").fetchall() == []
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status, client_id) "
            "values ('TCK-BACKFILL', 'Acme', 'subject', 'body', 'Low', 'Open', 'client-a')"
        )
        connection.execute(
            "insert into canonical_assets "
            "(canonical_id, asset_type, display_name, client_id, first_seen, last_seen, attributes_json) "
            "values ('asset-backfill', 'server', 'Server', 'client-b', 'now', 'now', '{}')"
        )

    repaired = Store(path)
    clients = {client.client_id: client for client in repaired.list_clients(AllClients())}
    assert clients["__quarantine__"].status == "quarantine"
    assert clients["client-a"].name == "client-a"
    assert clients["client-b"].name == "client-b"
    assert len(clients) == 3

    Store(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("select count(*) from clients").fetchone()[0] == 3
        assert connection.execute("pragma foreign_key_check").fetchall() == []


def test_client_connector_store_accessors_scope_and_verified_resolution(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    instance = store.create_connector_instance(
        "halopsa",
        "Primary Halo",
        client_id=None,
        credential_ref="vault:halopsa-primary",
        config_json='{"base_url":"https://halo.example"}',
    )
    assert instance.status == "inactive"
    assert store.get_connector_instance(instance.connector_instance_id) == instance
    updated = store.update_connector_instance(
        instance.connector_instance_id,
        status="active",
        client_id="client-a",
        config_json='{"tenant":"acme"}',
    )
    assert updated is not None
    assert updated.status == "active"
    assert updated.client_id == "client-a"
    assert updated.config_json == '{"tenant":"acme"}'

    client_a = BoundClients(frozenset({"client-a"}))
    client_b = BoundClients(frozenset({"client-b"}))
    assert store.get_client(client_a, "client-b") is None
    first = store.create_client_connector_mapping(
        client_a,
        instance.connector_instance_id,
        "company-1",
        "client-a",
        external_company_name="Acme Ltd",
    )
    second = store.create_client_connector_mapping(
        client_a,
        instance.connector_instance_id,
        "company-1",
        "client-a",
    )
    assert [mapping.verified for mapping in store.list_client_connector_mappings(client_a)] == [0, 0]
    with pytest.raises(PermissionError):
        store.create_client_connector_mapping(
            client_a,
            instance.connector_instance_id,
            "company-2",
            "client-b",
        )
    assert store.resolve_client_for(instance.connector_instance_id, "company-1") is None
    verified = store.verify_client_connector_mapping(AllClients(), first.mapping_id)
    assert verified.verified == 1
    assert store.resolve_client_for(instance.connector_instance_id, "company-1") == "client-a"
    with pytest.raises(ClientConnectorMappingConflictError, match="different verified mapping"):
        store.verify_client_connector_mapping(AllClients(), second.mapping_id)
    assert store.list_client_connector_mappings(client_b) == []

    with pytest.raises(ValueError, match="credentials or secrets"):
        store.create_connector_instance("m365", "Unsafe", config_json='{"client_secret":"nope"}')


def test_client_and_connector_api_smoke_and_conflict(settings) -> None:
    client = TestClient(create_app(settings))
    created = client.post("/clients", json={"client_id": "client-a", "name": "Acme"})
    assert created.status_code == 200
    assert created.json()["status"] == "active"
    assert client.get("/clients").status_code == 200
    assert client.get("/clients/client-a").json()["name"] == "Acme"
    assert client.patch("/clients/client-a", json={"status": "archived"}).json()["status"] == "archived"

    connector = client.post(
        "/connector-instances",
        json={
            "connector_type": "halopsa",
            "display_name": "Primary Halo",
            "client_id": "client-a",
            "credential_ref": "vault:halopsa",
            "config_json": '{"base_url":"https://halo.example"}',
        },
    )
    assert connector.status_code == 200
    connector_id = connector.json()["connector_instance_id"]
    assert client.get("/connector-instances").status_code == 200
    assert client.get(f"/connector-instances/{connector_id}").status_code == 200
    updated = client.patch(f"/connector-instances/{connector_id}", json={"status": "active"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "active"

    first = client.post(
        "/client-connector-mappings",
        json={
            "connector_instance_id": connector_id,
            "external_company_id": "company-1",
            "external_company_name": "Acme Ltd",
            "client_id": "client-a",
        },
    )
    second = client.post(
        "/client-connector-mappings",
        json={
            "connector_instance_id": connector_id,
            "external_company_id": "company-1",
            "client_id": "client-a",
        },
    )
    assert first.status_code == 200
    assert first.json()["verified"] == 0
    assert second.status_code == 200
    assert len(client.get("/client-connector-mappings").json()) == 2
    assert client.post(f"/client-connector-mappings/{first.json()['mapping_id']}/verify").status_code == 200
    conflict = client.post(f"/client-connector-mappings/{second.json()['mapping_id']}/verify")
    assert conflict.status_code == 409
    assert client.get("/clients/missing").status_code == 404
    assert client.get("/connector-instances/missing").status_code == 404
    assert client.post("/clients", json={"client_id": "client-a", "name": "Duplicate"}).status_code == 409


def test_bound_admin_is_not_an_operator_and_cannot_cross_clients(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
        api_token="",
    )
    store = Store(secure_settings.data_path)
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    store.create_principal("bound-admin", kind="staff")
    store.add_principal_credential("bound-admin", "bound-secret")
    store.add_principal_client_role("bound-admin", "client-a", "admin")
    client = TestClient(create_app(secure_settings))
    headers = _auth("bound-secret")

    listed = client.get("/clients", headers=headers)
    assert listed.status_code == 200
    assert {item["client_id"] for item in listed.json()} == {"client-a"}
    assert client.get("/clients/client-b", headers=headers).status_code == 404
    assert client.post("/clients", headers=headers, json={"client_id": "client-c", "name": "C"}).status_code == 403
    assert client.get("/connector-instances", headers=headers).status_code == 403
    mapping = client.post(
        "/client-connector-mappings",
        headers=headers,
        json={
            "connector_instance_id": "missing",
            "external_company_id": "company",
            "client_id": "client-b",
        },
    )
    assert mapping.status_code == 403


def test_p1_store_accessors_fail_closed_and_normalize_ids(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")

    assert _normalize_client_id(None) is None
    assert _normalize_client_id("   ") is None
    assert _normalize_client_id(" client-a ") == "client-a"

    with pytest.raises(ValueError, match="client scope is required"):
        store.list_clients(None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="client scope is required"):
        store.list_client_connector_mappings(None)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="client_id must be non-empty"):
        store.create_client("   ", "Acme")
    with pytest.raises(ValueError, match="client name must be non-empty"):
        store.create_client("client-a", "   ")
    with pytest.raises(ValueError, match="reserved"):
        store.create_client("__quarantine__", "Reserved")

    client = store.create_client(" client-a ", " Acme ")
    assert client.client_id == "client-a"
    assert store.get_client(AllClients(), " ") is None
    assert store.get_client(BoundClients(frozenset({"client-b"})), "client-a") is None
    assert store.set_client_status(AllClients(), "missing", "archived") is None
    assert store.set_client_status(BoundClients(frozenset({"client-b"})), "client-a", "archived") is None
    assert store.set_client_status(AllClients(), " ", "archived") is None
    with pytest.raises(ValueError, match="unsupported client status"):
        store.set_client_status(AllClients(), "client-a", "unknown")

    quarantine = store.ensure_quarantine_client()
    assert quarantine == store.get_client(AllClients(), "__quarantine__")
    with store._connect() as connection:  # noqa: SLF001
        assert store.ensure_quarantine_client(connection) == quarantine


def test_p1_store_rejects_invalid_connector_and_mapping_inputs(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    instance = store.create_connector_instance("halopsa", "Primary Halo")

    with pytest.raises(ValueError, match="connector_type must be non-empty"):
        store.create_connector_instance(" ", "Connector")
    with pytest.raises(ValueError, match="display_name must be non-empty"):
        store.create_connector_instance("halopsa", " ")
    with pytest.raises(KeyError, match="missing-client"):
        store.create_connector_instance("halopsa", "Missing Client", client_id="missing-client")
    with pytest.raises(ValueError, match="connector_type must be non-empty"):
        store.update_connector_instance(instance.connector_instance_id, connector_type=None)
    with pytest.raises(ValueError, match="connector_type must be non-empty"):
        store.update_connector_instance(instance.connector_instance_id, connector_type=" ")
    with pytest.raises(ValueError, match="display_name must be non-empty"):
        store.update_connector_instance(instance.connector_instance_id, display_name=None)
    with pytest.raises(ValueError, match="display_name must be non-empty"):
        store.update_connector_instance(instance.connector_instance_id, display_name=" ")
    with pytest.raises(ValueError, match="unsupported connector instance status"):
        store.update_connector_instance(instance.connector_instance_id, status="unknown")
    with pytest.raises(KeyError, match="missing-client"):
        store.update_connector_instance(instance.connector_instance_id, client_id="missing-client")

    with pytest.raises(ValueError, match="connector_instance_id must be non-empty"):
        store.list_client_connector_mappings(AllClients(), connector_instance_id=" ")
    with pytest.raises(ValueError, match="connector_instance_id must be non-empty"):
        store.create_client_connector_mapping(AllClients(), " ", "company", "client-a")
    with pytest.raises(ValueError, match="external_company_id must be non-empty"):
        store.create_client_connector_mapping(AllClients(), instance.connector_instance_id, " ", "client-a")
    with pytest.raises(ValueError, match="client_id must be non-empty"):
        store.create_client_connector_mapping(AllClients(), instance.connector_instance_id, "company", " ")
    with pytest.raises(KeyError, match="missing-client"):
        store.create_client_connector_mapping(AllClients(), instance.connector_instance_id, "company", "missing-client")
    with pytest.raises(KeyError, match="missing-connector"):
        store.create_client_connector_mapping(AllClients(), "missing-connector", "company", "client-a")


def test_p1_connector_instance_updates_cover_each_optional_field(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    instance = store.create_connector_instance(
        "halopsa",
        "Primary Halo",
        client_id="client-a",
        credential_ref="vault:old",
        config_json='{"base_url":"https://halo.example"}',
    )

    assert store.get_connector_instance(" ") is None
    assert store.update_connector_instance(" ", status="active") is None
    assert store.update_connector_instance(instance.connector_instance_id) == instance
    with pytest.raises(ValueError, match="unsupported connector instance fields"):
        store.update_connector_instance(instance.connector_instance_id, unexpected="value")

    updated = store.update_connector_instance(
        instance.connector_instance_id,
        connector_type="  hudu  ",
        display_name="  Primary Hudu  ",
        client_id=None,
        credential_ref="  vault:new  ",
        config_json='{"region":"ca"}',
        status=" ACTIVE ",
    )
    assert updated is not None
    assert updated.connector_type == "hudu"
    assert updated.display_name == "Primary Hudu"
    assert updated.client_id is None
    assert updated.credential_ref == "vault:new"
    assert updated.config_json == '{"region":"ca"}'
    assert updated.status == "active"
    assert store.list_connector_instances() == [updated]


def test_p1_mapping_scope_resolution_and_partial_unique_integrity_conflict(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    instance = store.create_connector_instance("halopsa", "Primary Halo")
    first = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-1", "client-a"
    )
    second = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-1", "client-a"
    )

    assert store.resolve_client_for(instance.connector_instance_id, "unmapped") is None
    assert store.resolve_client_for(instance.connector_instance_id, "company-1") is None
    assert store.resolve_client_for(" ", "company-1") is None
    assert store.resolve_client_for(instance.connector_instance_id, " ") is None
    assert store.list_client_connector_mappings(BoundClients(frozenset({"client-b"}))) == []
    with pytest.raises(PermissionError, match="outside authenticated scope"):
        store.verify_client_connector_mapping(BoundClients(frozenset({"client-b"})), first.mapping_id)
    with pytest.raises(KeyError):
        store.verify_client_connector_mapping(AllClients(), " ")
    with pytest.raises(KeyError):
        store.verify_client_connector_mapping(AllClients(), "missing")

    # The normal conflict pre-check is covered above in the existing smoke test.
    # This trigger creates the race-equivalent SQLite integrity failure after
    # the pre-check and exercises the partial-unique-index exception handler.
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            f"""
            create trigger force_verified_mapping_conflict
            after update of verified on client_connector_mappings
            when new.mapping_id = '{first.mapping_id}' and new.verified = 1
            begin
                update client_connector_mappings
                set verified = 1
                where mapping_id = '{second.mapping_id}';
            end
            """
        )
    with pytest.raises(ClientConnectorMappingConflictError, match="different verified mapping"):
        store.verify_client_connector_mapping(AllClients(), first.mapping_id)
    assert store.resolve_client_for(instance.connector_instance_id, "company-1") is None


@pytest.mark.parametrize(
    "migrations",
    [
        (Migration(2, "later", lambda _connection: None), Migration(1, "earlier", lambda _connection: None)),
        (Migration(1, "first", lambda _connection: None), Migration(1, "duplicate", lambda _connection: None)),
    ],
)
def test_migration_validation_rejects_non_increasing_and_duplicate_versions(migrations) -> None:
    connection = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="unique, strictly increasing"):
        MigrationRunner(connection).run(migrations)
    connection.close()


@pytest.mark.parametrize(
    "migration",
    [
        Migration(-1, "negative", lambda _connection: None),
        Migration(1, "   ", lambda _connection: None),
    ],
)
def test_migration_validation_rejects_negative_versions_and_empty_names(migration) -> None:
    connection = sqlite3.connect(":memory:")
    with pytest.raises(ValueError, match="non-negative version and non-empty name"):
        MigrationRunner(connection).run((migration,))
    connection.close()


def test_p1_api_scope_and_operator_guards(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
    )
    store = Store(secure_settings.data_path)
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    instance = store.create_connector_instance("halopsa", "Primary Halo")
    mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-1", "client-a"
    )
    store.create_principal("bound-admin", kind="staff")
    store.add_principal_credential("bound-admin", "bound-secret")
    store.add_principal_client_role("bound-admin", "client-a", "admin")

    client = TestClient(create_app(secure_settings))
    headers = _auth("bound-secret")
    out_of_scope = client.get("/clients", params={"client_id": "client-b"}, headers=headers)
    assert out_of_scope.status_code == 403
    assert out_of_scope.json()["detail"] == "requested tenant is outside authenticated scope"
    assert client.get("/clients/client-b", headers=headers).status_code == 404
    assert client.get("/clients/missing", headers=headers).status_code == 404
    assert client.post(
        "/clients", headers=headers, json={"client_id": "client-c", "name": "C"}
    ).status_code == 403
    assert client.post(
        "/connector-instances",
        headers=headers,
        json={"connector_type": "hudu", "display_name": "Hudu"},
    ).status_code == 403
    assert client.post(
        f"/client-connector-mappings/{mapping.mapping_id}/verify", headers=headers
    ).status_code == 403


def test_p1_api_client_listing_fails_closed_without_a_tenant(settings, monkeypatch) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
    )
    app = create_app(secure_settings)
    tenantless = AuthContext(
        role=Role.VIEWER,
        presented_token="viewer-token",
        client_id=None,
        client_ids=frozenset(),
        demo_mode=False,
    )
    monkeypatch.setattr(
        "wait_local_agent.rbac.resolve_auth_context",
        lambda *_args, **_kwargs: tenantless,
    )

    response = TestClient(app).get("/clients", headers=_auth("viewer-token"))
    assert response.status_code == 403
    assert response.json()["detail"] == "authenticated principal has no tenant"


def test_p1_api_route_error_branches_and_empty_results(settings, monkeypatch, tmp_path: Path) -> None:
    app = create_app(settings)
    store = app.state.store

    with TestClient(app) as client:
        assert client.get("/connector-instances").json() == []
        assert client.get("/client-connector-mappings").json() == []

        invalid_client = client.post("/clients", json={"client_id": " ", "name": "Acme"})
        assert invalid_client.status_code == 400
        assert invalid_client.json()["detail"] == "client_id must be non-empty"

        created_client = client.post("/clients", json={"client_id": "client-a", "name": "Acme"})
        assert created_client.status_code == 200
        assert client.patch("/clients/missing", json={"status": "archived"}).status_code == 404

        def reject_client_status(*_args, **_kwargs):
            raise ValueError("unsupported client status")

        monkeypatch.setattr(store, "set_client_status", reject_client_status)
        invalid_status = client.patch("/clients/client-a", json={"status": "archived"})
        assert invalid_status.status_code == 400
        assert invalid_status.json()["detail"] == "unsupported client status"
        monkeypatch.undo()

        missing_client_connector = client.post(
            "/connector-instances",
            json={"connector_type": "halopsa", "display_name": "Missing", "client_id": "missing"},
        )
        assert missing_client_connector.status_code == 404
        assert missing_client_connector.json()["detail"] == "client not found"
        invalid_connector = client.post(
            "/connector-instances", json={"connector_type": " ", "display_name": "Invalid"}
        )
        assert invalid_connector.status_code == 400
        assert invalid_connector.json()["detail"] == "connector_type must be non-empty"

        connector_payload = {"connector_type": "halopsa", "display_name": "Primary"}
        connector = client.post("/connector-instances", json=connector_payload)
        assert connector.status_code == 200
        connector_id = connector.json()["connector_instance_id"]
        duplicate_connector = client.post("/connector-instances", json=connector_payload)
        assert duplicate_connector.status_code == 409
        assert duplicate_connector.json()["detail"] == "connector instance already exists"
        assert client.get("/connector-instances/missing").status_code == 404
        assert client.patch("/connector-instances/missing", json={"status": "active"}).status_code == 404

        missing_connector_client = client.patch(
            f"/connector-instances/{connector_id}", json={"client_id": "missing"}
        )
        assert missing_connector_client.status_code == 404
        assert missing_connector_client.json()["detail"] == "client not found"
        invalid_connector_update = client.patch(
            f"/connector-instances/{connector_id}", json={"connector_type": " "}
        )
        assert invalid_connector_update.status_code == 400
        assert invalid_connector_update.json()["detail"] == "connector_type must be non-empty"

        second_connector = client.post(
            "/connector-instances", json={"connector_type": "hudu", "display_name": "Secondary"}
        )
        assert second_connector.status_code == 200
        duplicate_update = client.patch(
            f"/connector-instances/{second_connector.json()['connector_instance_id']}",
            json=connector_payload,
        )
        assert duplicate_update.status_code == 409
        assert duplicate_update.json()["detail"] == "connector instance already exists"

        invalid_mapping_filter = client.get(
            "/client-connector-mappings", params={"connector_instance_id": " "}
        )
        assert invalid_mapping_filter.status_code == 400
        assert invalid_mapping_filter.json()["detail"] == "connector_instance_id must be non-empty"
        missing_mapping_client = client.post(
            "/client-connector-mappings",
            json={
                "connector_instance_id": connector_id,
                "external_company_id": "company",
                "client_id": "missing",
            },
        )
        assert missing_mapping_client.status_code == 404
        assert missing_mapping_client.json()["detail"] == "client not found"
        missing_mapping_connector = client.post(
            "/client-connector-mappings",
            json={
                "connector_instance_id": "missing",
                "external_company_id": "company",
                "client_id": "client-a",
            },
        )
        assert missing_mapping_connector.status_code == 404
        assert missing_mapping_connector.json()["detail"] == "connector instance not found"
        invalid_mapping = client.post(
            "/client-connector-mappings",
            json={
                "connector_instance_id": connector_id,
                "external_company_id": " ",
                "client_id": "client-a",
            },
        )
        assert invalid_mapping.status_code == 400
        assert invalid_mapping.json()["detail"] == "external_company_id must be non-empty"
        assert client.post("/client-connector-mappings/missing/verify").status_code == 404

        def reject_mapping(*_args, **_kwargs):
            raise PermissionError("mapping is outside authenticated scope")

        monkeypatch.setattr(store, "create_client_connector_mapping", reject_mapping)
        forbidden_mapping = client.post(
            "/client-connector-mappings",
            json={
                "connector_instance_id": connector_id,
                "external_company_id": "company-2",
                "client_id": "client-a",
            },
        )
        assert forbidden_mapping.status_code == 403
        assert forbidden_mapping.json()["detail"] == "mapping is outside authenticated scope"
        monkeypatch.undo()

        def missing_pack(*_args, **_kwargs):
            raise OSError("missing pack")

        monkeypatch.setattr(app_module, "install_pack_tarball", missing_pack)
        pack = client.post("/packs/install", json={"tarball_path": str(tmp_path / "missing.tar.gz")})
        assert pack.status_code == 400
        assert pack.json()["detail"] == "pack tarball could not be read"


def test_p1_api_non_msp_admin_is_denied_mutations_and_scoped_verify(settings, monkeypatch) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="client-a",
        admin_token="bootstrap-admin",
    )
    store = Store(secure_settings.data_path)
    store.create_client("client-a", "Acme")
    store.create_client("client-b", "Beta")
    instance = store.create_connector_instance("halopsa", "Primary Halo")
    mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-a", "client-a"
    )
    foreign_mapping = store.create_client_connector_mapping(
        AllClients(), instance.connector_instance_id, "company-b", "client-b"
    )
    store.create_principal("bound-admin", kind="staff")
    store.add_principal_credential("bound-admin", "bound-secret")
    store.add_principal_client_role("bound-admin", "client-a", "admin")

    app = create_app(secure_settings)
    headers = _auth("bound-secret")
    with TestClient(app) as client:
        assert client.post(
            "/clients", headers=headers, json={"client_id": "client-c", "name": "C"}
        ).status_code == 403
        assert client.post(
            "/connector-instances",
            headers=headers,
            json={"connector_type": "hudu", "display_name": "Hudu"},
        ).status_code == 403
        assert client.patch(
            "/clients/client-a", headers=headers, json={"status": "archived"}
        ).status_code == 403
        assert client.patch(
            f"/connector-instances/{instance.connector_instance_id}",
            headers=headers,
            json={"status": "active"},
        ).status_code == 403
        assert client.post(
            f"/client-connector-mappings/{mapping.mapping_id}/verify", headers=headers
        ).status_code == 403

        monkeypatch.setattr(app_module, "_require_msp_operator", lambda _context: None)
        forbidden_verify = client.post(
            f"/client-connector-mappings/{foreign_mapping.mapping_id}/verify", headers=headers
        )
        assert forbidden_verify.status_code == 403
        assert forbidden_verify.json()["detail"] == "mapping is outside authenticated scope"
