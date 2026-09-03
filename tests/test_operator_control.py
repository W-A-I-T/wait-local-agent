from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

from fastapi.testclient import TestClient

from packs.operator_control.activity import activity_to_dict, list_activity
from wait_local_agent.api.app import create_app
from wait_local_agent.client_scope import AllClients, BoundClients
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _secure(settings):
    return replace(settings, demo_mode=False, admin_token="bootstrap-admin", client_id="alpha")


def _seed_staff(store: Store, principal_id: str, token: str, client_id: str, role: str = "viewer") -> None:
    store.create_principal(principal_id, kind="staff", display_name=principal_id)
    store.add_principal_credential(principal_id, token)
    store.add_principal_client_role(principal_id, client_id, role)


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
