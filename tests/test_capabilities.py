from __future__ import annotations

import sqlite3

import pytest

from wait_local_agent import migrations
from wait_local_agent.capabilities import (
    CAPABILITY_MIGRATION_VERSION,
    MICROSOFT_ADMIN_CAPABILITY,
    active_capability_grants,
    grant_capability,
    list_capability_grants,
    list_principals,
    revoke_capability,
)
from wait_local_agent.store import Store


def _principal_with_client(store: Store, principal_id: str, client_id: str, role: str = "viewer") -> None:
    store.create_principal(principal_id, kind="staff", display_name=principal_id)
    store.add_principal_client_role(principal_id, client_id, role)


def test_client_capability_grant_lifecycle_and_migration(settings) -> None:
    store = Store(settings.data_path)
    store.create_client("alpha", "Alpha")
    _principal_with_client(store, "tech-alpha", "alpha", "technician")

    granted = grant_capability(
        store,
        principal_id="tech-alpha",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="alpha",
        actor_id="admin-one",
    )

    assert granted.active is True
    assert granted.client_id == "alpha"
    assert granted.granted_by == "admin-one"
    assert granted.updated_by == "admin-one"
    assert active_capability_grants(store, "tech-alpha") == frozenset(
        {(MICROSOFT_ADMIN_CAPABILITY, "alpha")}
    )
    listed = list_capability_grants(store, principal_id="tech-alpha")
    assert listed == [granted]
    with sqlite3.connect(store.path) as connection:
        migration = connection.execute(
            "select name from schema_migrations where version = ?",
            (CAPABILITY_MIGRATION_VERSION,),
        ).fetchone()
    assert migration is not None
    assert migration[0] == "principal_capability_grants"

    revoked = revoke_capability(
        store,
        principal_id="tech-alpha",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="alpha",
        actor_id="admin-two",
    )
    assert revoked.active is False
    assert revoked.granted_by == "admin-one"
    assert revoked.updated_by == "admin-two"
    assert active_capability_grants(store, "tech-alpha") == frozenset()

    regranted = grant_capability(
        store,
        principal_id="tech-alpha",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="alpha",
        actor_id="admin-three",
    )
    assert regranted.active is True
    assert regranted.granted_by == "admin-one"
    assert regranted.updated_by == "admin-three"


def test_capability_migration_is_canonical_and_idempotent(tmp_path) -> None:
    path = tmp_path / "state.db"
    store = Store(path)

    declared = store._declared_migrations()
    assert any(migration.version == CAPABILITY_MIGRATION_VERSION for migration in declared)

    with sqlite3.connect(path) as connection:
        before = connection.execute(
            "select version, name from schema_migrations where version = ?",
            (CAPABILITY_MIGRATION_VERSION,),
        ).fetchone()
    assert before == (CAPABILITY_MIGRATION_VERSION, "principal_capability_grants")

    Store(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "select count(*) from schema_migrations where version = ?",
            (CAPABILITY_MIGRATION_VERSION,),
        ).fetchone() == (1,)


def test_capability_reads_do_not_run_migrations_after_startup(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    calls = 0
    original_run = migrations.MigrationRunner.run

    def counted_run(runner, migration_list):
        nonlocal calls
        calls += 1
        return original_run(runner, migration_list)

    monkeypatch.setattr(migrations.MigrationRunner, "run", counted_run)
    for _ in range(5):
        assert active_capability_grants(store, "missing-principal") == frozenset()
    assert calls == 0


def test_capability_grants_fail_closed_for_invalid_targets(settings) -> None:
    store = Store(settings.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _principal_with_client(store, "viewer-alpha", "alpha")

    with pytest.raises(ValueError, match="global capability grants require the msp_admin role"):
        grant_capability(
            store,
            principal_id="viewer-alpha",
            capability_key=MICROSOFT_ADMIN_CAPABILITY,
            client_id=None,
            actor_id="admin",
        )
    with pytest.raises(ValueError, match="no role for the requested client"):
        grant_capability(
            store,
            principal_id="viewer-alpha",
            capability_key=MICROSOFT_ADMIN_CAPABILITY,
            client_id="beta",
            actor_id="admin",
        )
    with pytest.raises(KeyError):
        grant_capability(
            store,
            principal_id="missing",
            capability_key=MICROSOFT_ADMIN_CAPABILITY,
            client_id="alpha",
            actor_id="admin",
        )
    with pytest.raises(KeyError):
        grant_capability(
            store,
            principal_id="viewer-alpha",
            capability_key=MICROSOFT_ADMIN_CAPABILITY,
            client_id="missing",
            actor_id="admin",
        )
    with pytest.raises(ValueError, match="unsupported capability_key"):
        grant_capability(
            store,
            principal_id="viewer-alpha",
            capability_key="not_supported",
            client_id="alpha",
            actor_id="admin",
        )
    with pytest.raises(ValueError, match="capability_key is invalid"):
        list_capability_grants(store, capability_key="Bad Key")
    with pytest.raises(KeyError):
        revoke_capability(
            store,
            principal_id="viewer-alpha",
            capability_key=MICROSOFT_ADMIN_CAPABILITY,
            client_id="alpha",
            actor_id="admin",
        )


def test_global_capability_grant_requires_and_supports_msp_admin(settings) -> None:
    store = Store(settings.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    store.create_principal("msp-admin", kind="staff", display_name="MSP Admin")
    store.add_principal_global_role("msp-admin", "msp_admin")

    grant = grant_capability(
        store,
        principal_id="msp-admin",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id=None,
        actor_id="bootstrap-admin",
    )

    assert grant.client_id is None
    assert active_capability_grants(store, "msp-admin") == frozenset(
        {(MICROSOFT_ADMIN_CAPABILITY, None)}
    )


def test_principal_summary_preserves_roles(settings) -> None:
    store = Store(settings.data_path)
    store.create_client("alpha", "Alpha")
    store.create_principal("tech", kind="staff", display_name="Tech")
    store.add_principal_client_role("tech", "alpha", "technician")
    store.add_principal_global_role("tech", "msp_admin")

    principals = list_principals(store)
    tech = next(item for item in principals if item.principal_id == "tech")

    assert tech.active is True
    assert tech.kind == "staff"
    assert tech.client_roles == (("alpha", "technician"),)
    assert tech.global_roles == ("msp_admin",)
