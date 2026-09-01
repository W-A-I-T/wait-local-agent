from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi.testclient import TestClient

from packs.operator_control.activity import activity_to_dict, list_activity
from packs.operator_control.identity import (
    IdentityConflictError,
    create_principal,
    get_principal_detail,
    remove_client_role,
    set_client_role,
    set_msp_admin,
    update_principal,
)
from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.store import Store, hash_credential


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _secure(settings):
    return replace(settings, demo_mode=False, admin_token="bootstrap-admin", client_id="alpha")


def _seed_staff(store: Store, principal_id: str, token: str, client_id: str, role: str = "viewer") -> None:
    store.create_principal(principal_id, kind="staff", display_name=principal_id)
    store.add_principal_credential(principal_id, token)
    store.add_principal_client_role(principal_id, client_id, role)


def test_operator_can_create_and_rotate_hashed_principal_credential(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    client = TestClient(create_app(secure))

    created = client.post(
        "/packs/operator-control/principals",
        headers=_auth("bootstrap-admin"),
        json={
            "principal_id": "tech-alpha",
            "kind": "staff",
            "display_name": "Alpha technician",
            "client_roles": [{"client_id": "alpha", "role": "technician"}],
            "issue_credential": True,
        },
    )

    assert created.status_code == 200
    token = created.json()["credential"]
    assert isinstance(token, str) and token.startswith("wait_")
    assert token not in str(created.json()["principal"])
    assert created.json()["principal"]["credentials"][0]["fingerprint"].startswith("sha256:")

    with store._connect() as connection:  # noqa: SLF001 - verify persisted credential contract
        row = connection.execute(
            "select credential_hash from principal_credentials where principal_id = ? and active = 1",
            ("tech-alpha",),
        ).fetchone()
    assert row is not None
    assert row["credential_hash"] == hash_credential(token)
    assert row["credential_hash"] != token

    role = client.get("/auth/role", headers=_auth(token))
    assert role.status_code == 200

    rotated = client.post(
        "/packs/operator-control/principals/tech-alpha/credentials/rotate",
        headers=_auth("bootstrap-admin"),
    )
    assert rotated.status_code == 200
    new_token = rotated.json()["credential"]
    assert new_token != token
    assert client.get("/auth/role", headers=_auth(token)).status_code == 401
    assert client.get("/auth/role", headers=_auth(new_token)).status_code == 200


def test_operator_principal_lifecycle_enforces_scope_and_lockout_guards(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_staff(store, "client-admin", "client-admin-token", "alpha", "admin")
    client = TestClient(create_app(secure))

    forbidden = client.get(
        "/packs/operator-control/principals",
        headers=_auth("client-admin-token"),
    )
    assert forbidden.status_code == 403

    invalid_customer = client.post(
        "/packs/operator-control/principals",
        headers=_auth("bootstrap-admin"),
        json={"principal_id": "customer-no-scope", "kind": "customer", "client_roles": []},
    )
    assert invalid_customer.status_code == 409

    first = client.post(
        "/packs/operator-control/principals",
        headers=_auth("bootstrap-admin"),
        json={
            "principal_id": "msp-one",
            "kind": "staff",
            "display_name": "MSP One",
            "client_roles": [],
            "msp_admin": True,
        },
    )
    assert first.status_code == 200
    first_token = first.json()["credential"]

    last_admin_blocked = client.post(
        "/packs/operator-control/principals/msp-one/credentials/revoke-all",
        headers=_auth("bootstrap-admin"),
    )
    assert last_admin_blocked.status_code == 409
    assert "final active msp_admin" in last_admin_blocked.json()["detail"]

    second = client.post(
        "/packs/operator-control/principals",
        headers=_auth("bootstrap-admin"),
        json={
            "principal_id": "msp-two",
            "kind": "staff",
            "display_name": "MSP Two",
            "client_roles": [],
            "msp_admin": True,
        },
    )
    assert second.status_code == 200

    self_revoke = client.post(
        "/packs/operator-control/principals/msp-one/credentials/revoke-all",
        headers=_auth(first_token),
    )
    assert self_revoke.status_code == 409
    assert "cannot revoke or deactivate itself" in self_revoke.json()["detail"]

    revoked = client.post(
        "/packs/operator-control/principals/msp-one/credentials/revoke-all",
        headers=_auth("bootstrap-admin"),
    )
    assert revoked.status_code == 200
    assert all(not credential["active"] for credential in revoked.json()["credentials"])

    added_role = client.put(
        "/packs/operator-control/principals/msp-two/client-roles/beta",
        headers=_auth("bootstrap-admin"),
        json={"role": "admin"},
    )
    assert added_role.status_code == 200
    assert ["beta", "admin"] in added_role.json()["client_roles"]

    removed_role = client.delete(
        "/packs/operator-control/principals/msp-two/client-roles/beta",
        headers=_auth("bootstrap-admin"),
    )
    assert removed_role.status_code == 200
    assert ["beta", "admin"] not in removed_role.json()["client_roles"]


def test_operator_identity_management_is_read_only_in_demo(settings) -> None:
    client = TestClient(create_app(replace(settings, demo_mode=True, client_id="demo")))

    listed = client.get("/packs/operator-control/principals")
    created = client.post(
        "/packs/operator-control/principals",
        json={
            "principal_id": "demo-admin",
            "kind": "staff",
            "client_roles": [],
            "msp_admin": True,
        },
    )

    assert listed.status_code == 200
    assert created.status_code == 403
    assert created.json()["detail"] == "identity management is read-only in demo mode"


def test_unified_activity_route_respects_tenant_scope_and_filters(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    _seed_staff(store, "alpha-viewer", "alpha-viewer-token", "alpha", "viewer")
    with store._connect() as connection:  # noqa: SLF001 - focused activity projection fixture
        connection.execute(
            """
            insert into execution_runs
              (run_kind, source_run_id, actor, client_id, status,
               started_at, finished_at, trigger_source, metadata_json)
            values ('agent', 101, 'alpha-tech', 'alpha', 'completed', '2026-08-30T10:00:00+00:00',
                    '2026-08-30T10:01:00+00:00', 'manual', '{}')
            """
        )
        connection.execute(
            """
            insert into execution_runs
              (run_kind, source_run_id, actor, client_id, status,
               started_at, finished_at, trigger_source, metadata_json)
            values ('workflow', 202, 'beta-tech', 'beta', 'failed', '2026-08-30T11:00:00+00:00',
                    '2026-08-30T11:01:00+00:00', 'event', '{}')
            """
        )
    client = TestClient(create_app(secure))

    alpha = client.get(
        "/packs/operator-control/activity/runs",
        headers=_auth("alpha-viewer-token"),
    )
    assert alpha.status_code == 200
    assert len(alpha.json()) == 1
    assert alpha.json()[0]["client_id"] == "alpha"
    assert alpha.json()[0]["kind"] == "agent"

    all_rows = client.get(
        "/packs/operator-control/activity/runs?limit=10",
        headers=_auth("bootstrap-admin"),
    )
    assert all_rows.status_code == 200
    assert {row["client_id"] for row in all_rows.json()} == {"alpha", "beta"}

    failed_workflows = client.get(
        "/packs/operator-control/activity/runs?kinds=workflow&status=failed",
        headers=_auth("bootstrap-admin"),
    )
    assert failed_workflows.status_code == 200
    assert [(row["kind"], row["status"]) for row in failed_workflows.json()] == [("workflow", "failed")]


def test_unified_activity_projects_all_sources_and_deduplicates_canonical_runs() -> None:
    def execution(run_kind, source_run_id, run_id, client_id, started_at):
        return SimpleNamespace(
            run_kind=run_kind,
            source_run_id=source_run_id,
            id=run_id,
            actor="operator",
            status="completed",
            started_at=started_at,
            finished_at=started_at,
            client_id=client_id,
            trigger_source="manual",
        )

    store = cast(Store, SimpleNamespace(
        list_execution_runs=lambda scope: [
            execution("agent", 1, 10, "alpha", "2026-08-30T10:00:00Z"),
            execution("", None, 11, "alpha", "2026-08-30T09:00:00Z"),
            execution("smart-action", 4, 12, "alpha", "2026-08-30T08:00:00Z"),
        ],
        list_agent_runs=lambda scope: [
            SimpleNamespace(
                id=1, agent_id="duplicate", entity_id="ticket-1", actor="", status="completed",
                started_at="2026-08-30T10:00:00Z", finished_at="", client_id="alpha",
            ),
            SimpleNamespace(
                id=2, agent_id="triage", entity_id="ticket-2", actor="tech", status="failed",
                started_at="2026-08-30T07:00:00Z", finished_at="", client_id="alpha",
            ),
        ],
        list_workflow_runs=lambda scope: [
            SimpleNamespace(
                id=3, template_id="onboarding", ticket_id="ticket-3", status="running",
                created_at="2026-08-30T06:00:00Z", updated_at="", client_id="alpha",
            ),
        ],
        list_smart_action_runs=lambda scope: [
            SimpleNamespace(
                id=4, action_id="duplicate", actor="", status="completed",
                created_at="2026-08-30T08:00:00Z", updated_at="", client_id="alpha",
            ),
            SimpleNamespace(
                id=5, action_id="notify", actor="operator", status="completed",
                created_at="2026-08-30T05:00:00Z", updated_at="", client_id="alpha",
            ),
        ],
        list_collector_runs=lambda scope: [
            SimpleNamespace(
                id=6, module_id="inventory", source_id=6, actor_id=None, status="completed",
                started_at="2026-08-30T04:00:00Z", completed_at="", client_id="alpha",
            ),
        ],
        list_agent_backfills=lambda scope: [
            SimpleNamespace(
                id=7, agent_id="historical", actor="operator", status="completed",
                created_at="2026-08-30T03:00:00Z", updated_at="", client_id="alpha",
            ),
        ],
    ))

    rows = list_activity(store, scope=BoundClients(frozenset({"alpha"})))

    assert [row.kind for row in rows] == [
        "agent", "execution", "smart-action", "agent", "workflow", "smart_action", "collector", "backfill"
    ]
    assert sum(row.activity_id == "agent:1" for row in rows) == 0
    assert sum(row.activity_id == "execution:10" for row in rows) == 1
    assert rows[1].title == "Execution"
    assert activity_to_dict(rows[-1])["detail_path"] == "/backfills"
    assert [
        row.kind for row in list_activity(store, scope=AllClients(), kinds=frozenset({"AGENT"}), status=" FAILED ")
    ] == ["agent"]
    assert len(list_activity(store, scope=AllClients(), limit=2)) == 2


def test_identity_lifecycle_updates_roles_and_rejects_unsafe_shapes(settings) -> None:
    secure = _secure(settings)
    store = Store(secure.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    api = TestClient(create_app(secure))
    status = api.get("/packs/operator-control/status", headers=_auth("bootstrap-admin"))
    assert status.status_code == 200
    assert status.json() == {
        "status": "ready",
        "principal_management": True,
        "credential_rotation": True,
        "unified_activity": True,
    }
    principal, _ = create_principal(
        store,
        principal_id="staff-alpha",
        kind="staff",
        display_name="Alpha staff",
        client_roles=(("alpha", "viewer"),),
        msp_admin=False,
        issue_credential=False,
    )
    assert principal.client_roles == (("alpha", "viewer"),)
    with pytest.raises(KeyError):
        get_principal_detail(store, "missing-principal")
    with pytest.raises(IdentityConflictError, match="already exists"):
        create_principal(
            store,
            principal_id="staff-alpha",
            kind="staff",
            display_name="Duplicate",
            client_roles=(("alpha", "viewer"),),
            msp_admin=False,
            issue_credential=False,
        )
    renamed = update_principal(
        store,
        principal_id="staff-alpha",
        display_name="Renamed",
        active=None,
        actor_principal_id=None,
    )
    assert renamed.display_name == "Renamed"
    with pytest.raises(IdentityConflictError, match="retain a client role"):
        remove_client_role(store, principal_id="staff-alpha", client_id="alpha", actor_principal_id=None)
    updated = set_client_role(store, principal_id="staff-alpha", client_id="beta", role="technician")
    assert updated.client_roles == (("alpha", "viewer"), ("beta", "technician"))
    removed = remove_client_role(store, principal_id="staff-alpha", client_id="beta", actor_principal_id=None)
    assert removed.client_roles == (("alpha", "viewer"),)

    customer, _ = create_principal(
        store,
        principal_id="customer-alpha",
        kind="customer",
        display_name="Customer",
        client_roles=(("alpha", "viewer"),),
        msp_admin=False,
        issue_credential=False,
    )
    with pytest.raises(IdentityConflictError, match="exactly one client"):
        set_client_role(store, principal_id=customer.principal_id, client_id="beta", role="viewer")
    with pytest.raises(IdentityConflictError, match="only staff"):
        set_msp_admin(store, principal_id=customer.principal_id, enabled=True, actor_principal_id=None)
