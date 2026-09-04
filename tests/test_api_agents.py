from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from tests.api_helpers import _auth, _provision_bound_principal
from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_event_ingest_route_dispatches_idempotently_and_exposes_delivery_history(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    agent = client.post(
        "/agents",
        json={
            "name": "Created P1 triage",
            "trigger": "event",
            "filters": {"event_type": "ticket.created", "priority": "P1"},
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert agent.status_code == 200
    assert agent.json()["id"]

    event = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-event-1"},
        json={
            "event_type": "ticket.created",
            "entity_id": "TCK-1001",
            "client_id": "acme",
            "max_retries": 2,
            "retry_delay_seconds": 7,
            "payload": {"priority": "P1", "api_token": "secret-value"},
        },
    )
    assert event.status_code == 200
    assert event.json()["duplicate"] is False
    assert event.json()["delivery"]["status"] == "completed"
    assert event.json()["delivery"]["max_retries"] == 2
    assert event.json()["delivery"]["retry_delay_seconds"] == 7
    assert event.json()["run_ids"]
    assert "secret-value" not in event.text

    duplicate = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-event-1"},
        json={
            "event_type": "ticket.created",
            "entity_id": "TCK-1001",
            "client_id": "acme",
            "payload": {"priority": "P1"},
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    deliveries = client.get("/automation/event-deliveries")
    assert deliveries.status_code == 200
    assert deliveries.json()[0]["idempotency_key"] == "api-event-1"
    detail = client.get(f"/automation/event-deliveries/{deliveries.json()[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["event_type"] == "ticket.created"

    missing_key = client.post(
        "/automation/events",
        json={"event_type": "ticket.created", "entity_id": "TCK-1001"},
    )
    assert missing_key.status_code == 422

    invalid_policy = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-invalid-policy"},
        json={
            "event_type": "ticket.created",
            "entity_id": "TCK-1001",
            "max_retries": 11,
        },
    )
    assert invalid_policy.status_code == 422

    unsupported = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-unsupported-event"},
        json={"event_type": "ticket.deleted", "entity_id": "TCK-1001"},
    )
    assert unsupported.status_code == 422

    missing_entity = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-missing-entity"},
        json={"event_type": "ticket.created", "entity_id": "NO-SUCH-TICKET"},
    )
    assert missing_entity.status_code == 404
    missing_delivery = client.get("/automation/event-deliveries/99999")
    assert missing_delivery.status_code == 404

def test_event_delivery_retry_route_is_tenant_scoped_and_bounded(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ?", ("acme",))
    delivery, _ = store.create_event_delivery(
        idempotency_key="api-retry-event",
        event_type="ticket.created",
        entity_type="ticket",
        entity_id="TCK-1001",
        payload={"priority": "P1", "access_token": "do-not-echo"},
        client_id="acme",
    )
    store.update_event_delivery(
        delivery.id or 0,
        status="failed",
        matched_agent_count=0,
        agent_ids=[],
        run_ids=[],
        error_detail="provider access_token=do-not-echo",
        agent_attempts={},
    )
    beta_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "beta",
            "admin_token": "admin-token",
            "tech_token": "beta-token",
        }
    )
    wrong_tenant = TestClient(create_app(beta_settings)).post(
        f"/automation/event-deliveries/{delivery.id}/retry",
        headers={"Authorization": "Bearer beta-token"},
    )
    client = TestClient(create_app(settings))
    retried = client.post(f"/automation/event-deliveries/{delivery.id}/retry")

    assert wrong_tenant.status_code == 404
    assert retried.status_code == 200
    assert retried.json()["delivery"]["status"] == "completed"
    assert retried.json()["delivery"]["retry_count"] == 1
    assert retried.json()["delivery"]["next_retry_at"] is None
    assert "do-not-echo" not in retried.text

def test_workflow_completion_event_filter_is_available_through_api(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    agent = client.post(
        "/agents",
        json={
            "name": "After triage",
            "trigger": "event",
            "filters": {
                "event_type": "workflow.completed",
                "workflow_template_id": "ticket-triage",
            },
            "enabled_tools": ["ticket-summary"],
            "steps": [{"tool_id": "ticket-summary", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert agent.status_code == 200
    assert agent.json()["id"]

    event = client.post(
        "/automation/events",
        headers={"Idempotency-Key": "api-workflow-completion-1"},
        json={
            "event_type": "workflow.completed",
            "entity_id": "TCK-1001",
            "client_id": "acme",
            "payload": {
                "workflow_run_id": "17",
                "workflow_template_id": "ticket-triage",
                "status": "completed",
            },
        },
    )

    assert event.status_code == 200
    assert event.json()["delivery"]["event_type"] == "workflow.completed"
    assert event.json()["run_ids"]

def test_bounded_agent_backfill_supports_pause_cancel_and_failed_reruns(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    agent = client.post(
        "/agents",
        json={
            "name": "Backfill triage",
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    assert agent.status_code == 200
    agent_id = agent.json()["id"]

    preview = client.post(
        "/agent-backfills/preview",
        json={
            "agent_id": agent_id,
            "entity_ids": ["TCK-1001", "TCK-1002"],
            "input": {"api_token": "backfill-secret"},
            "max_concurrency": 2,
            "client_id": "acme",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["entity_count"] == 2
    assert preview.json()["estimated_runs"] == 2
    assert preview.json()["max_concurrency"] == 2
    assert preview.json()["execution_mode"] == "bounded_parallel"
    assert preview.json()["will_persist"] is False
    assert preview.json()["input"]["api_token"] == "[redacted]"
    assert store.list_agent_backfills() == []

    created = client.post(
        "/agent-backfills",
        json={
            "agent_id": agent_id,
            "entity_ids": ["TCK-1001", "TCK-1002"],
            "input": {"api_token": "backfill-secret"},
            "max_concurrency": 2,
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    assert created.json()["status"] == "queued"
    assert "backfill-secret" not in created.text
    backfill_id = created.json()["id"]
    assert client.get("/agent-backfills").json()[0]["id"] == backfill_id
    assert client.get(f"/agent-backfills/{backfill_id}").status_code == 200

    paused = client.post(f"/agent-backfills/{backfill_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/agent-backfills/{backfill_id}/run")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["max_concurrency"] == 2
    assert resumed.json()["succeeded_count"] == 2
    assert client.post(f"/agent-backfills/{backfill_id}/run").status_code == 409
    assert client.post(f"/agent-backfills/{backfill_id}/rerun-failed").status_code == 409
    assert client.post(f"/agent-backfills/{backfill_id}/cancel").status_code == 409
    assert client.post(f"/agent-backfills/{backfill_id}/pause").status_code == 409

    queued_for_cancel = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    cancelled = client.post(f"/agent-backfills/{queued_for_cancel.json()['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    disabled = client.post(
        "/agents",
        json={
            "name": "Disabled backfill target",
            "enabled": False,
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
            "client_id": "acme",
        },
    )
    failed_backfill = client.post(
        "/agent-backfills",
        json={
            "agent_id": disabled.json()["id"],
            "entity_ids": ["TCK-1001"],
            "client_id": "acme",
        },
    )
    failed_run = client.post(f"/agent-backfills/{failed_backfill.json()['id']}/run")
    assert failed_run.status_code == 200
    assert failed_run.json()["status"] == "completed_with_errors"
    assert failed_run.json()["failed_entity_ids"] == ["TCK-1001"]
    rerun = client.post(f"/agent-backfills/{failed_backfill.json()['id']}/rerun-failed")
    assert rerun.status_code == 200
    assert rerun.json()["failed_count"] == 1
    assert client.post(f"/agent-backfills/{failed_backfill.json()['id']}/rerun-failed").status_code == 200

    duplicate = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001", "TCK-1001"], "client_id": "acme"},
    )
    missing_ticket = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["NOPE"], "client_id": "acme"},
    )
    unknown_agent = client.post(
        "/agent-backfills",
        json={"agent_id": "no-such-agent", "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    assert duplicate.status_code == 422
    assert missing_ticket.status_code == 404
    assert unknown_agent.status_code == 404
    preview_duplicate = client.post(
        "/agent-backfills/preview",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001", "TCK-1001"], "client_id": "acme"},
    )
    preview_missing_ticket = client.post(
        "/agent-backfills/preview",
        json={"agent_id": agent_id, "entity_ids": ["NOPE"], "client_id": "acme"},
    )
    preview_unknown_agent = client.post(
        "/agent-backfills/preview",
        json={"agent_id": "no-such-agent", "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    assert preview_duplicate.status_code == 422
    assert preview_missing_ticket.status_code == 404
    assert preview_unknown_agent.status_code == 404
    assert client.get("/agent-backfills/99999").status_code == 404
    assert client.post("/agent-backfills/99999/run").status_code == 404
    assert client.post("/agent-backfills/99999/pause").status_code == 404
    assert client.post("/agent-backfills/99999/cancel").status_code == 404
    assert client.post("/agent-backfills/99999/rerun-failed").status_code == 404

    from wait_local_agent.agents import AgentExecutionResult

    def synthetic_failure(self, definition, *, entity_id, actor, input_payload):
        return AgentExecutionResult(
            run_id=0,
            agent_id=definition.id,
            status="failed",
            current_step=0,
            steps=[],
        )

    monkeypatch.setattr(app_module.AgentService, "run", synthetic_failure)
    synthetic_backfill = client.post(
        "/agent-backfills",
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001"], "client_id": "acme"},
    )
    synthetic_run = client.post(f"/agent-backfills/{synthetic_backfill.json()['id']}/run")
    assert synthetic_run.status_code == 200
    assert synthetic_run.json()["failed_count"] == 1
    assert synthetic_run.json()["run_ids"] == []

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    secure_client = TestClient(create_app(secure))
    assert secure_client.get("/agent-backfills", headers=_auth("viewer-token")).status_code == 403
    assert secure_client.get(
        "/agent-backfills/1", headers=_auth("viewer-token")
    ).status_code == 403
    assert secure_client.post(
        "/agent-backfills",
        headers=_auth("tech-token"),
        json={"agent_id": agent_id, "entity_ids": ["TCK-1001"]},
    ).status_code == 403

def test_event_history_filters_by_client_id(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "viewer_token": "viewer-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    with store._connect() as connection:
        for cid in ("acme", "beta"):
            connection.execute(
                """
                insert or ignore into clients (client_id, name, status, created_at, updated_at)
                values (?, ?, 'active', ?, ?)
                """,
                (cid, cid.title(), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-ACME', 'Acme', 'Subject', 'Body', 'High', 'Open', 'acme')
            """
        )
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-BETA', 'Beta', 'Subject', 'Body', 'Low', 'Open', 'beta')
            """
        )
    store.create_approval_request("TCK-ACME", "ticket.assign", {"ticket_id": "TCK-ACME"}, client_id="acme")
    store.create_approval_request("TCK-BETA", "ticket.assign", {"ticket_id": "TCK-BETA"}, client_id="beta")
    client = TestClient(create_app(secure_settings))

    filtered = client.get("/event-history", params={"client_id": "acme"}, headers=_auth("viewer-token"))
    blank = client.get("/event-history", params={"client_id": ""}, headers=_auth("viewer-token"))
    all_events = client.get("/event-history", headers=_auth("viewer-token"))

    assert filtered.status_code == 200
    assert filtered.json()
    assert all(event["client_id"] == "acme" for event in filtered.json())
    assert len(blank.json()) == len(all_events.json())

def test_smart_action_runs_and_ticket_lookup_are_client_scoped(settings) -> None:
    store = Store(settings.data_path)
    with store._connect() as connection:
        for cid in ("acme", "beta"):
            connection.execute(
                """
                insert or ignore into clients (client_id, name, status, created_at, updated_at)
                values (?, ?, 'active', ?, ?)
                """,
                (cid, cid.title(), "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
        connection.executemany(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("TCK-ACME", "Acme", "MFA reset", "Sign-in blocked", "High", "Open", "acme"),
                ("TCK-BETA", "Beta", "MFA reset", "Sign-in blocked", "High", "Open", "beta"),
            ],
        )
    client = TestClient(create_app(settings))

    acme = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "TCK-ACME"}, "client_id": "acme"},
    )
    beta = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "TCK-BETA"}, "client_id": "beta"},
    )
    listed = client.get("/smart-actions/runs", params={"client_id": "acme"})
    hidden = client.get(
        f"/smart-actions/runs/{beta.json()['run_id']}", params={"client_id": "acme"}
    )
    cross_tenant = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "TCK-BETA"}, "client_id": "acme"},
    )

    assert acme.status_code == 200
    assert acme.json()["run_id"]
    assert beta.status_code == 200
    assert listed.status_code == 200
    assert [run["client_id"] for run in listed.json()] == ["acme"]
    assert hidden.status_code == 404
    assert cross_tenant.json()["status"] == "failed"

def test_smart_action_scope_comes_from_authenticated_tenant(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "client_id": "acme",
        }
    )
    store = Store(secure_settings.data_path)
    _provision_bound_principal(store, "acme-viewer", "acme-viewer-token", "acme", "viewer")
    acme = store.create_smart_action_run(
        "ticket-triage", "acme-actor", "success", "digest-a", {"tenant": "acme"}, [], client_id="acme"
    )
    store.create_smart_action_run(
        "ticket-triage", "beta-actor", "success", "digest-b", {"tenant": "beta"}, [], client_id="beta"
    )
    client = TestClient(create_app(secure_settings))

    omitted = client.get("/smart-actions/runs", headers=_auth("acme-viewer-token"))
    arbitrary = client.get(
        "/smart-actions/runs",
        params={"client_id": "beta"},
        headers=_auth("acme-viewer-token"),
    )
    hidden = client.get(
        f"/smart-actions/runs/{acme.id}",
        params={"client_id": "beta"},
        headers=_auth("acme-viewer-token"),
    )

    assert omitted.status_code == 200
    assert [run["client_id"] for run in omitted.json()] == ["acme"]
    assert arbitrary.status_code == 403
    assert hidden.status_code == 404

def test_smart_action_run_exposes_redacted_failure_detail(settings) -> None:
    client = TestClient(create_app(settings))

    failed = client.post(
        "/smart-actions/ticket-triage/invoke",
        json={"payload": {"ticket_id": "missing"}, "client_id": "acme"},
    )
    listed = client.get("/smart-actions/runs", params={"client_id": "acme"})

    assert failed.status_code == 200
    assert failed.json()["status"] == "failed"
    run = next(item for item in listed.json() if item["id"] == failed.json()["run_id"])
    assert run["error_detail"] == "ticket_id must identify an existing ticket"

def test_nsight_task_run_now_is_exposed_and_approval_gated(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        client_id="acme",
        n_sight_base_url="https://nsight.example.test",
        n_sight_api_key="test-key",
        n_sight_client_map_json='{"acme":123}',
    )
    client = TestClient(create_app(secure_settings))

    tools = client.get("/tools", headers=_auth("tech-token"))
    detail = client.get("/smart-actions/nsight-run-task-now", headers=_auth("tech-token"))
    check_config_detail = client.get(
        "/smart-actions/nsight-check-config", headers=_auth("tech-token")
    )
    antivirus_scans_detail = client.get(
        "/smart-actions/nsight-antivirus-scans", headers=_auth("tech-token")
    )
    antivirus_scan_start_detail = client.get(
        "/smart-actions/nsight-antivirus-scan-start", headers=_auth("tech-token")
    )
    antivirus_scan_cancel_detail = client.get(
        "/smart-actions/nsight-antivirus-scan-cancel", headers=_auth("tech-token")
    )
    antivirus_scan_pause_detail = client.get(
        "/smart-actions/nsight-antivirus-scan-pause", headers=_auth("tech-token")
    )
    antivirus_scan_resume_detail = client.get(
        "/smart-actions/nsight-antivirus-scan-resume", headers=_auth("tech-token")
    )
    antivirus_quarantine_detail = client.get(
        "/smart-actions/nsight-antivirus-quarantine", headers=_auth("tech-token")
    )
    antivirus_quarantine_release_detail = client.get(
        "/smart-actions/nsight-antivirus-quarantine-release", headers=_auth("tech-token")
    )
    antivirus_quarantine_remove_detail = client.get(
        "/smart-actions/nsight-antivirus-quarantine-remove", headers=_auth("tech-token")
    )
    antivirus_products_detail = client.get(
        "/smart-actions/nsight-antivirus-products", headers=_auth("tech-token")
    )
    antivirus_definitions_detail = client.get(
        "/smart-actions/nsight-antivirus-definitions", headers=_auth("tech-token")
    )
    antivirus_update_history_detail = client.get(
        "/smart-actions/nsight-antivirus-update-history", headers=_auth("tech-token")
    )
    software_inventory_detail = client.get(
        "/smart-actions/nsight-software-inventory", headers=_auth("tech-token")
    )
    hardware_inventory_detail = client.get(
        "/smart-actions/nsight-hardware-inventory", headers=_auth("tech-token")
    )
    preview = client.post(
        "/smart-actions/nsight-run-task-now/invoke",
        headers=_auth("tech-token"),
        json={
            "client_id": "acme",
            "payload": {"device_id": "server:49324", "check_id": "1304847"},
        },
    )
    scan_preview = client.post(
        "/smart-actions/nsight-antivirus-scan-start/invoke",
        headers=_auth("tech-token"),
        json={"client_id": "acme", "payload": {"device_id": "server:49324"}},
    )
    cancel_preview = client.post(
        "/smart-actions/nsight-antivirus-scan-cancel/invoke",
        headers=_auth("tech-token"),
        json={"client_id": "acme", "payload": {"device_id": "server:49324"}},
    )

    assert tools.status_code == 200
    assert "nsight-run-task-now" in {tool["id"] for tool in tools.json()}
    assert "nsight-antivirus-scans" in {tool["id"] for tool in tools.json()}
    assert "nsight-antivirus-products" in {tool["id"] for tool in tools.json()}
    assert "nsight-antivirus-definitions" in {tool["id"] for tool in tools.json()}
    assert "nsight-antivirus-update-history" in {tool["id"] for tool in tools.json()}
    assert "nsight-software-inventory" in {tool["id"] for tool in tools.json()}
    assert "nsight-hardware-inventory" in {tool["id"] for tool in tools.json()}
    assert "nsight-antivirus-scan-pause" in {tool["id"] for tool in tools.json()}
    assert "nsight-antivirus-scan-resume" in {tool["id"] for tool in tools.json()}
    assert detail.status_code == 200
    assert detail.json()["requires_approval"] is True
    assert detail.json()["access_mode"] == "write"
    assert check_config_detail.status_code == 200
    assert check_config_detail.json()["access_mode"] == "read"
    assert antivirus_scans_detail.status_code == 200
    assert antivirus_scans_detail.json()["access_mode"] == "read"
    assert antivirus_products_detail.status_code == 200
    assert antivirus_products_detail.json()["access_mode"] == "read"
    assert antivirus_definitions_detail.status_code == 200
    assert antivirus_definitions_detail.json()["access_mode"] == "read"
    assert antivirus_update_history_detail.status_code == 200
    assert antivirus_update_history_detail.json()["access_mode"] == "read"
    assert software_inventory_detail.status_code == 200
    assert software_inventory_detail.json()["access_mode"] == "read"
    assert hardware_inventory_detail.status_code == 200
    assert hardware_inventory_detail.json()["access_mode"] == "read"
    assert antivirus_scan_start_detail.status_code == 200
    assert antivirus_scan_start_detail.json()["requires_approval"] is True
    assert antivirus_scan_start_detail.json()["access_mode"] == "write"
    assert antivirus_scan_pause_detail.status_code == 200
    assert antivirus_scan_pause_detail.json()["requires_approval"] is True
    assert antivirus_scan_pause_detail.json()["access_mode"] == "write"
    assert antivirus_scan_resume_detail.status_code == 200
    assert antivirus_scan_resume_detail.json()["requires_approval"] is True
    assert antivirus_scan_resume_detail.json()["access_mode"] == "write"
    assert antivirus_scan_cancel_detail.status_code == 200
    assert antivirus_scan_cancel_detail.json()["requires_approval"] is True
    assert antivirus_scan_cancel_detail.json()["access_mode"] == "write"
    assert antivirus_quarantine_detail.status_code == 200
    assert antivirus_quarantine_detail.json()["requires_approval"] is False
    assert antivirus_quarantine_detail.json()["access_mode"] == "read"
    assert antivirus_quarantine_release_detail.status_code == 200
    assert antivirus_quarantine_release_detail.json()["requires_approval"] is True
    assert antivirus_quarantine_release_detail.json()["access_mode"] == "write"
    assert antivirus_quarantine_remove_detail.status_code == 200
    assert antivirus_quarantine_remove_detail.json()["requires_approval"] is True
    assert antivirus_quarantine_remove_detail.json()["access_mode"] == "write"
    assert preview.status_code == 200
    assert preview.json()["status"] == "pending_approval"
    assert preview.json()["output"]["check_id"] == 1304847
    assert scan_preview.status_code == 200
    assert scan_preview.json()["status"] == "pending_approval"
    assert cancel_preview.status_code == 200
    assert cancel_preview.json()["status"] == "pending_approval"
