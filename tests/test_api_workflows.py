from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

import pytest
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
import wait_local_agent.api.routers.workflows as workflows_module
from tests.api_helpers import _auth, _provision_bound_principal
from tests.support import ingest_local
from wait_local_agent.api.app import create_app
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


def test_workflow_run_detail_hides_foreign_approval_payload(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    foreign_approval = store.create_approval_request(
        "TCK-GLOBEX",
        "ticket.assign",
        {"ticket_id": "TCK-GLOBEX", "payload": "foreign"},
        client_id="globex",
    )
    local_approval = store.create_approval_request(
        "TCK-ACME",
        "ticket.assign",
        {"ticket_id": "TCK-ACME", "payload": "local"},
        client_id="acme",
    )
    foreign_run = store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-GLOBEX",
        "pending_approval",
        "foreign approval link",
        foreign_approval.id,
        client_id="acme",
    )
    local_run = store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-ACME",
        "pending_approval",
        "local approval link",
        local_approval.id,
        client_id="acme",
    )
    client = TestClient(create_app(secure_settings))

    foreign_response = client.get(f"/workflow-runs/{foreign_run.id}", headers=_auth("tech-token"))
    local_response = client.get(f"/workflow-runs/{local_run.id}", headers=_auth("tech-token"))

    assert foreign_response.status_code == 200
    foreign_payload = foreign_response.json()
    assert foreign_payload["approval_request"] is None
    assert foreign_payload["id"] == foreign_run.id
    assert foreign_payload["template_id"] == foreign_run.template_id
    assert foreign_payload["ticket_id"] == foreign_run.ticket_id
    assert foreign_payload["status"] == foreign_run.status
    assert foreign_payload["message"] == foreign_run.message
    assert foreign_payload["approval_request_id"] == foreign_approval.id
    assert foreign_payload["client_id"] == foreign_run.client_id
    assert foreign_payload["created_at"] == foreign_run.created_at
    assert foreign_payload["updated_at"] == foreign_run.updated_at
    assert foreign_payload["template"]["id"] == foreign_run.template_id
    assert isinstance(foreign_payload["events"], list)

    assert local_response.status_code == 200
    local_payload = local_response.json()
    assert local_payload["approval_request"]["id"] == local_approval.id
    assert local_payload["approval_request"]["client_id"] == "acme"
    assert local_payload["approval_request"]["payload"] == {
        "ticket_id": "TCK-ACME",
        "payload": "local",
    }
    assert local_payload["approval_request"]["workflow_run_id"] == local_run.id


def test_workflow_run_comparison_is_tenant_scoped_and_redacted(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
        }
    )
    store = Store(secure_settings.data_path)
    _provision_bound_principal(store, "acme-technician", "acme-technician-token", "acme", "technician")
    left = store.create_workflow_run(
        "ticket-triage",
        "TCK-ACME",
        "failed",
        "provider api_key=left-secret",
        client_id="acme",
        template_version=1,
    )
    right = store.create_workflow_run(
        "ticket-triage",
        "TCK-ACME",
        "completed",
        "provider api_key=right-secret",
        client_id="acme",
        template_version=2,
    )
    foreign = store.create_workflow_run(
        "ticket-triage",
        "TCK-BETA",
        "completed",
        "foreign",
        client_id="beta",
        template_version=3,
    )
    client = TestClient(create_app(secure_settings))

    compared = client.get(
        f"/workflow-runs/{left.id}/compare/{right.id}", headers=_auth("acme-technician-token")
    )
    foreign_response = client.get(
        f"/workflow-runs/{left.id}/compare/{foreign.id}", headers=_auth("acme-technician-token")
    )
    missing_response = client.get(
        f"/workflow-runs/{left.id}/compare/99999", headers=_auth("acme-technician-token")
    )
    no_tenant_settings = secure_settings.__class__(
        **{**secure_settings.__dict__, "client_id": "", "tech_token": "", "viewer_token": "viewer-token"}
    )
    compare_endpoint = next(
        route.endpoint
        for route in create_app(no_tenant_settings).routes
        if isinstance(route, APIRoute)
        and route.path == "/workflow-runs/{run_id}/compare/{other_run_id}"
    )
    with pytest.raises(HTTPException) as no_tenant_error:
        compare_endpoint(
            left.id,
            right.id,
            AuthContext(role=Role.VIEWER, presented_token="tenantless"),
        )

    assert compared.status_code == 200
    assert compared.json()["changed"] is True
    assert {change["field"] for change in compared.json()["changes"]} >= {
        "status",
        "template_version",
    }
    assert "left-secret" not in compared.text
    assert "right-secret" not in compared.text
    assert foreign_response.status_code == 404
    assert missing_response.status_code == 404
    assert no_tenant_error.value.status_code == 404


def test_tool_backed_workflow_runs_existing_action_and_preserves_tenant_scope(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    client = TestClient(create_app(settings))

    run = client.post(
        "/workflows/templates/ticket-quality-review/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    actions = client.get("/smart-actions/runs", params={"client_id": "acme"})

    assert run.status_code == 200
    assert run.json()["status"] == "completed"
    assert "ticket quality review" in run.json()["message"].lower()
    assert actions.status_code == 200
    assert actions.json()[0]["action_id"] == "ticket-quality"
    assert actions.json()[0]["client_id"] == "acme"


def test_threshold_workflow_api_accepts_bounded_payload_and_rejects_missing_fields(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    client = TestClient(create_app(settings))

    missing = client.post(
        "/workflows/templates/ticket-sla-risk-review/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme", "payload": {}},
    )
    completed = client.post(
        "/workflows/templates/ticket-sla-risk-review/runs",
        json={
            "ticket_id": "TCK-1001",
            "client_id": "acme",
            "payload": {"thresholds_minutes": {"high": 1}},
        },
    )

    assert missing.status_code == 422
    assert "thresholds_minutes" in missing.json()["detail"]
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_workflow_run_inherits_ticket_client_id_when_request_omits_it(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute(
            "update tickets set client_id = ? where id = ?",
            ("acme", "TCK-1002"),
        )
    client = TestClient(create_app(settings))

    run = client.post(
        "/workflows/templates/documentation-assisted-response/runs",
        json={"ticket_id": "TCK-1002"},
    )
    approvals = client.get("/approval-requests", params={"client_id": "acme"})
    runs = client.get("/workflow-runs", params={"client_id": "acme"})

    assert run.status_code == 200
    assert run.json()["client_id"] == "acme"
    assert [request["action_type"] for request in approvals.json()] == [
        "smart_action:documentation-assisted-response"
    ]
    assert approvals.json()[0]["client_id"] == "acme"
    assert [item["ticket_id"] for item in runs.json()] == ["TCK-1002"]


def test_manual_workflow_run_emits_completion_event(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    agent = client.post(
        "/agents",
        json={
            "name": "Workflow completion triage",
            "trigger": "event",
            "filters": {
                "event_type": "workflow.completed",
                "workflow_template_id": "ticket-triage",
            },
            "enabled_tools": ["ticket-triage"],
            "steps": [{"tool_id": "ticket-triage", "payload": {}}],
            "max_steps": 1,
        },
    )
    assert agent.status_code == 200
    assert agent.json()["id"]

    run = client.post(
        "/workflows/templates/ticket-triage/runs",
        json={"ticket_id": "TCK-1001"},
    )
    assert run.status_code == 200
    assert run.json()["status"] == "completed"

    deliveries = client.get("/automation/event-deliveries")
    assert deliveries.status_code == 200
    completion = [
        delivery for delivery in deliveries.json() if delivery["event_type"] == "workflow.completed"
    ]
    assert len(completion) == 1
    assert completion[0]["status"] == "completed"
    assert completion[0]["run_ids"]

    pending = client.post(
        "/workflows/templates/assign-technician/runs",
        json={"ticket_id": "TCK-1001"},
    )
    assert pending.status_code == 200
    assert pending.json()["status"] == "pending_approval"
    assert len(
        [delivery for delivery in client.get("/automation/event-deliveries").json()
         if delivery["event_type"] == "workflow.completed"]
    ) == 1


def test_manual_workflow_completion_dispatch_failure_is_audited(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))

    def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("api-key=secret-value")

    monkeypatch.setattr(app_module.EventDispatcher, "dispatch", fail_dispatch)
    client = TestClient(create_app(settings))

    response = client.post(
        "/workflows/templates/ticket-triage/runs",
        json={"ticket_id": "TCK-1001"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    failures = [
        event for event in store.list_audit_events()
        if event.event_type == "workflow.completion_dispatch_failed"
    ]
    assert len(failures) == 1
    assert "secret-value" not in failures[0].detail


def test_manual_workflow_run_requires_tenant_for_authenticated_technician(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(secure_settings))

    response = client.post(
        "/workflows/templates/ticket-triage/runs",
        headers=_auth("tech-token"),
        json={"ticket_id": "TCK-1001"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_manual_workflow_run_reports_missing_template_after_ticket_scope_check(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    response = client.post(
        "/workflows/templates/missing/runs",
        json={"ticket_id": "TCK-1001"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "workflow template not found"


def test_manual_workflow_run_maps_runtime_ticket_lookup_failure(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))

    def fail_workflow(*_args, **_kwargs):
        raise LookupError("ticket disappeared")

    monkeypatch.setattr(workflows_module, "run_workflow_template", fail_workflow)
    client = TestClient(create_app(settings))

    response = client.post(
        "/workflows/templates/ticket-triage/runs",
        json={"ticket_id": "TCK-1001"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "ticket not found"


def test_template_gallery_is_provenance_bearing_and_runs_only_in_scope(settings) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ?", ("acme",))
    client = TestClient(create_app(settings))

    created = client.post(
        "/workflow-templates/gallery",
        json={
            "source_template_id": "ticket-triage",
            "display_name": "Acme triage starter",
            "provenance": "Reviewed by the local operator",
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    assert created.json()["source_template_id"] == "ticket-triage"
    assert created.json()["provenance"] == "Reviewed by the local operator"
    entry_id = created.json()["id"]

    listed = client.get("/workflow-templates/gallery")
    detail = client.get(f"/workflow-templates/gallery/{entry_id}")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == entry_id
    assert detail.status_code == 200
    assert detail.json()["id"] == entry_id

    run = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert run.status_code == 200
    assert run.json()["template_id"] == "ticket-triage"
    assert run.json()["status"] == "completed"

    unknown_source = client.post(
        "/workflow-templates/gallery",
        json={"source_template_id": "not-a-template", "provenance": "review"},
    )
    foreign_run = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "beta"},
    )
    missing_entry = client.get("/workflow-templates/gallery/not-a-gallery-entry")
    missing_ticket = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "NO-SUCH-TICKET", "client_id": "acme"},
    )
    assert unknown_source.status_code == 404
    assert foreign_run.status_code == 404
    assert missing_entry.status_code == 404
    assert missing_ticket.status_code == 404

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    _provision_bound_principal(store, "globex-viewer", "globex-viewer-token", "globex", "viewer")
    _provision_bound_principal(store, "globex-technician", "globex-technician-token", "globex", "technician")
    secure_client = TestClient(create_app(secure))
    assert secure_client.get(
        "/workflow-templates/gallery",
        headers=_auth("globex-viewer-token"),
    ).json() == []
    assert secure_client.get(
        "/workflow-templates/gallery/anything",
        headers=_auth("globex-viewer-token"),
    ).status_code == 404
    assert secure_client.post(
        "/workflow-templates/gallery",
        headers=_auth("globex-technician-token"),
        json={"source_template_id": "ticket-triage", "provenance": "review", "client_id": "acme"},
    ).status_code == 403
    assert secure_client.post(
        "/workflow-templates/gallery/anything/runs",
        headers=_auth("globex-technician-token"),
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    ).status_code == 403


def test_template_gallery_instances_are_editable_versioned_and_disableable(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:
        connection.execute("update tickets set client_id = ? where id = ?", ("acme", "TCK-1001"))
    client = TestClient(create_app(settings))

    created = client.post(
        "/workflow-templates/gallery",
        json={
            "source_template_id": "ticket-triage",
            "provenance": "operator review",
            "display_name": "Acme triage v1",
            "instructions": "Use the local triage policy.",
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    entry_id = created.json()["id"]
    assert created.json()["version"] == 1
    assert created.json()["enabled"] is True

    updated = client.patch(
        f"/workflow-templates/gallery/{entry_id}",
        json={
            "name": "Acme triage disabled",
            "description": "A locally maintained triage definition.",
            "instructions": "Do not post externally.",
            "enabled": False,
            "client_id": "acme",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["enabled"] is False
    assert updated.json()["instructions"] == "Do not post externally."

    disabled_run = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    revisions = client.get(
        f"/workflow-templates/gallery/{entry_id}/revisions",
        params={"client_id": "acme"},
    )
    assert disabled_run.status_code == 409
    assert revisions.status_code == 200
    assert [revision["version"] for revision in revisions.json()] == [2, 1]
    assert revisions.json()[0]["definition"]["enabled"] is False
    diff = client.get(
        f"/workflow-templates/gallery/{entry_id}/revisions/1/diff/2",
        params={"client_id": "acme"},
    )
    assert diff.status_code == 200
    assert diff.json()["changed"] is True
    assert {change["field"] for change in diff.json()["changes"]} == {
        "description",
        "enabled",
        "instructions",
        "name",
    }
    foreign_diff = client.get(
        f"/workflow-templates/gallery/{entry_id}/revisions/1/diff/2",
        params={"client_id": "beta"},
    )
    assert foreign_diff.status_code == 404
    with store._connect() as connection:
        connection.execute(
            "update template_gallery_revisions set definition_json = ? where gallery_id = ? and version = 1",
            (
                '{"name":"Acme triage v1","description":"Review tickets.",'
                '"instructions":"Use the local triage policy.","enabled":true,'
                '"token":"do-not-echo"}',
                entry_id,
            ),
        )
    redacted_diff = client.get(
        f"/workflow-templates/gallery/{entry_id}/revisions/1/diff/2",
        params={"client_id": "acme"},
    )
    assert redacted_diff.status_code == 200
    assert "do-not-echo" not in redacted_diff.text

    restored = client.post(
        f"/workflow-templates/gallery/{entry_id}/revisions/1/restore",
        json={"client_id": "acme"},
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["name"] == "Acme triage v1"
    assert restored.json()["enabled"] is True

    run = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert run.status_code == 200
    assert run.json()["template_version"] == 3
    assert "local triage policy" in run.json()["message"]

    foreign_update = client.patch(
        f"/workflow-templates/gallery/{entry_id}",
        json={"name": "cross-tenant", "client_id": "beta"},
    )
    assert foreign_update.status_code == 404

    missing_revisions = client.get("/workflow-templates/gallery/missing/revisions")
    missing_diff = client.get("/workflow-templates/gallery/missing/revisions/1/diff/2")
    missing_update = client.patch(
        "/workflow-templates/gallery/missing",
        json={"name": "Missing"},
    )
    invalid_update = client.patch(
        f"/workflow-templates/gallery/{entry_id}",
        json={"name": "   ", "client_id": "acme"},
    )
    missing_restore = client.post(
        f"/workflow-templates/gallery/{entry_id}/revisions/999/restore",
        json={"client_id": "acme"},
    )
    assert missing_revisions.status_code == 200
    assert missing_revisions.json() == []
    assert missing_diff.status_code == 404
    assert missing_update.status_code == 404
    assert invalid_update.status_code == 422
    assert missing_restore.status_code == 404

    missing_restore_entry = client.post(
        "/workflow-templates/gallery/missing/revisions/1/restore",
        json={},
    )
    missing_revision_diff = client.get(
        f"/workflow-templates/gallery/{entry_id}/revisions/1/diff/999",
        params={"client_id": "acme"},
    )
    assert missing_restore_entry.status_code == 404
    assert missing_revision_diff.status_code == 404

    with store._connect() as connection:
        connection.execute(
            "update template_gallery_revisions set definition_json = ? where gallery_id = ? and version = 1",
            ('{"name":""}', entry_id),
        )
    invalid_restore = client.post(
        f"/workflow-templates/gallery/{entry_id}/revisions/1/restore",
        json={"client_id": "acme"},
    )
    assert invalid_restore.status_code == 409

    monkeypatch.setattr(workflows_module, "get_workflow_template", lambda _template_id: None)
    unavailable_source = client.post(
        f"/workflow-templates/gallery/{entry_id}/runs",
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )
    assert unavailable_source.status_code == 409


def test_template_gallery_editing_preserves_secure_tenant_boundary(settings) -> None:
    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure.data_path)
    _provision_bound_principal(store, "globex-viewer", "globex-viewer-token", "globex", "viewer")
    _provision_bound_principal(store, "globex-technician", "globex-technician-token", "globex", "technician")
    template = workflows_module.get_workflow_template("ticket-triage")
    assert template is not None
    entry = store.create_template_gallery_entry(template, provenance="operator review", client_id="acme")
    client = TestClient(create_app(secure))

    patch = client.patch(
        f"/workflow-templates/gallery/{entry.id}",
        headers=_auth("globex-technician-token"),
        json={"name": "No tenant", "client_id": "acme"},
    )
    revisions = client.get(
        f"/workflow-templates/gallery/{entry.id}/revisions",
        headers=_auth("globex-viewer-token"),
    )
    diff = client.get(
        f"/workflow-templates/gallery/{entry.id}/revisions/1/diff/1",
        headers=_auth("globex-viewer-token"),
    )
    restore = client.post(
        f"/workflow-templates/gallery/{entry.id}/revisions/1/restore",
        headers=_auth("globex-technician-token"),
        json={"client_id": "acme"},
    )
    run = client.post(
        f"/workflow-templates/gallery/{entry.id}/runs",
        headers=_auth("globex-technician-token"),
        json={"ticket_id": "TCK-1001", "client_id": "acme"},
    )

    assert patch.status_code == 403
    assert revisions.status_code == 200 and revisions.json() == []
    assert diff.status_code == 404
    assert restore.status_code == 404
    assert run.status_code == 403


def test_template_gallery_workflow_design_round_trips_and_restores(settings) -> None:
    client = TestClient(create_app(settings))
    design = {
        "format": "wait-local-agent.workflow-design",
        "version": 1,
        "nodes": [
            {"id": "trigger", "type": "trigger", "label": "Ticket", "config": {}},
            {"id": "action", "type": "action", "label": "Review", "config": {}},
            {"id": "end", "type": "end", "label": "Done", "config": {}},
        ],
        "edges": [
            {"from": "trigger", "to": "action"},
            {"from": "action", "to": "end"},
        ],
    }
    created = client.post(
        "/workflow-templates/gallery",
        json={
            "source_template_id": "ticket-triage",
            "provenance": "designer review",
            "client_id": "acme",
            "definition": design,
        },
    )
    assert created.status_code == 200
    created_definition = created.json()["definition"]
    assert created_definition["format"] == design["format"]
    assert created_definition["edges"] == design["edges"]
    assert created_definition["nodes"][1]["label"] == "Review"

    design_nodes = cast(list[dict[str, object]], design["nodes"])
    updated_design = {
        **design,
        "nodes": [
            *design_nodes[:-1],
            {"id": "end", "type": "end", "label": "Complete", "config": {}},
        ],
    }
    updated = client.patch(
        f"/workflow-templates/gallery/{created.json()['id']}",
        json={"definition": updated_design, "client_id": "acme"},
    )
    assert updated.status_code == 200
    assert updated.json()["definition"]["nodes"][-1]["label"] == "Complete"

    revisions = client.get(
        f"/workflow-templates/gallery/{created.json()['id']}/revisions",
        params={"client_id": "acme"},
    )
    assert revisions.status_code == 200
    revision_definition = revisions.json()[0]["definition"]["definition"]
    assert revision_definition["format"] == updated_design["format"]
    assert revision_definition["nodes"][-1]["label"] == "Complete"

    restored = client.post(
        f"/workflow-templates/gallery/{created.json()['id']}/revisions/1/restore",
        json={"client_id": "acme"},
    )
    assert restored.status_code == 200
    assert restored.json()["definition"]["nodes"][1]["label"] == "Review"

    invalid = client.patch(
        f"/workflow-templates/gallery/{created.json()['id']}",
        json={
            "definition": {
                **design,
                "edges": [{"from": "trigger", "to": "action"}],
            },
            "client_id": "acme",
        },
    )
    assert invalid.status_code == 422


def _seed_execution_tickets(store: Store) -> None:
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))


def test_executions_api_lists_and_details_runs(settings) -> None:
    store = Store(settings.data_path)
    _seed_execution_tickets(store)
    client = TestClient(create_app(settings))

    run = client.post(
        "/workflows/templates/ticket-triage/runs", json={"ticket_id": "TCK-1001"}
    )
    assert run.status_code == 200

    listed = client.get("/executions")
    assert listed.status_code == 200
    executions = listed.json()
    assert len(executions) == 1
    assert executions[0]["run_kind"] == "workflow"
    assert executions[0]["status"] == "completed"
    execution_id = executions[0]["id"]

    filtered = client.get("/executions", params={"kind": "smart_action"})
    assert filtered.status_code == 200
    assert filtered.json() == []
    by_status = client.get("/executions", params={"status": "completed"})
    assert len(by_status.json()) == 1
    ranged = client.get("/executions", params={"from": "2000-01-01", "to": "2000-01-02"})
    assert ranged.json() == []

    detail = client.get(f"/executions/{execution_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["id"] == execution_id
    assert [step["ordinal"] for step in payload["steps"]] == [0]
    assert payload["steps"][0]["kind"] == "workflow.template"
    assert payload["steps"][0]["input"]["ticket_id"] == "TCK-1001"
    assert payload["artifacts"] == []

    missing = client.get("/executions/9999")
    assert missing.status_code == 404


def test_executions_api_serves_smart_action_artifact(settings) -> None:
    store = Store(settings.data_path)
    _seed_execution_tickets(store)
    client = TestClient(create_app(settings))

    invoke = client.post(
        "/smart-actions/ticket-triage/invoke", json={"payload": {"ticket_id": "TCK-1001"}}
    )
    assert invoke.status_code == 200

    detail = client.get("/executions", params={"kind": "smart_action"}).json()[0]
    execution = client.get(f"/executions/{detail['id']}").json()
    assert execution["artifacts"]
    artifact = execution["artifacts"][0]
    assert "storage_path" not in artifact

    download = client.get(f"/executions/{detail['id']}/artifacts/{artifact['id']}")
    assert download.status_code == 200
    assert hashlib.sha256(download.content).hexdigest() == artifact["sha256"]

    wrong_run = client.get(f"/executions/{detail['id'] + 1}/artifacts/{artifact['id']}")
    assert wrong_run.status_code == 404
    missing_artifact = client.get(f"/executions/{detail['id']}/artifacts/9999")
    assert missing_artifact.status_code == 404


def test_executions_api_enforces_tenant_scope(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    _provision_bound_principal(store, "acme-viewer", "acme-viewer-token", "acme", "viewer")
    _provision_bound_principal(store, "acme-technician", "acme-technician-token", "acme", "technician")
    _seed_execution_tickets(store)
    acme_run = store.create_execution_run(
        "workflow", 1, "a", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="acme",
    )
    beta_run = store.create_execution_run(
        "workflow", 2, "b", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="beta",
    )
    assert acme_run.id is not None and beta_run.id is not None
    store.add_execution_step(
        acme_run.id, 0, "workflow.template", "t", "completed",
        "2026-08-01T09:00:00+00:00", "2026-08-01T09:01:00+00:00",
        "d", "d", "{}", "{}", "",
    )
    store.add_execution_artifact(
        acme_run.id, 0, "a.bin", "application/octet-stream", 1, "f" * 64, "/tmp/nope"
    )
    client = TestClient(create_app(secure_settings))

    viewer_list = client.get("/executions", headers=_auth("acme-viewer-token"))
    assert viewer_list.status_code == 200
    assert [run["id"] for run in viewer_list.json()] == [acme_run.id]

    foreign_detail = client.get(f"/executions/{beta_run.id}", headers=_auth("acme-viewer-token"))
    assert foreign_detail.status_code == 404
    foreign_artifact = client.get(
        f"/executions/{beta_run.id}/artifacts/1", headers=_auth("acme-technician-token")
    )
    assert foreign_artifact.status_code == 404

    admin_list = client.get("/executions", headers=_auth("admin-token"))
    assert {run["id"] for run in admin_list.json()} == {acme_run.id, beta_run.id}
    admin_filtered = client.get(
        "/executions", params={"client_id": "beta"}, headers=_auth("admin-token")
    )
    assert [run["id"] for run in admin_filtered.json()] == [beta_run.id]
    admin_detail = client.get(f"/executions/{beta_run.id}", headers=_auth("admin-token"))
    assert admin_detail.status_code == 200

    # The artifact file name must equal its content digest; a tampered path 404s.
    artifacts = store.list_execution_artifacts(acme_run.id)
    tampered = client.get(
        f"/executions/{acme_run.id}/artifacts/{artifacts[0].id}", headers=_auth("acme-technician-token")
    )
    assert tampered.status_code == 404


def test_executions_api_hides_all_runs_from_tenantless_principal(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure_settings.data_path)
    store.create_execution_run(
        "workflow", 1, "a", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="acme",
    )
    app = create_app(secure_settings)
    tenantless = AuthContext(role=Role.VIEWER, presented_token="viewer-token", client_id=None)
    executions_endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/executions"
    )
    analytics_endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/analytics/summary"
    )

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/executions",
            "headers": [],
            "query_string": b"",
        }
    )

    with pytest.raises(HTTPException, match="has no tenant"):
        executions_endpoint(request=request, context=tenantless)
    with pytest.raises(HTTPException, match="has no tenant"):
        analytics_endpoint(tenantless)


def test_analytics_summary_api_returns_metric_groups(settings) -> None:
    store = Store(settings.data_path)
    _seed_execution_tickets(store)
    client = TestClient(create_app(settings))

    invoke = client.post(
        "/smart-actions/ticket-triage/invoke", json={"payload": {"ticket_id": "TCK-1001"}}
    )
    assert invoke.status_code == 200
    failed = client.post(
        "/smart-actions/ticket-triage/invoke", json={"payload": {"ticket_id": "NOPE"}}
    )
    assert failed.status_code == 200

    response = client.get("/analytics/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["success_rate"]["total"] == 2
    assert summary["success_rate"]["succeeded"] == 1
    assert summary["failures_by_status"] == [{"status": "failed", "count": 1}]
    assert len(summary["executions_over_time"]) == 1
    assert summary["activity_breakdown"]
    assert summary["ticket_metrics"]["touched"] == 1
    assert summary["ticket_metrics"]["resolved"] == 0
    assert summary["activity_by_workflow"] == [
        {
            "run_kind": "smart_action",
            "workflow_id": "ticket-triage",
            "total": 2,
            "succeeded": 1,
            "status_counts": [
                {"status": "failed", "count": 1},
                {"status": "success", "count": 1},
            ],
        }
    ]
    time_saved = summary["estimated_minutes_saved"]
    assert time_saved["estimate"] is True
    assert time_saved["minutes"] == 4
    assert "estimate" in time_saved["derivation"]


def test_execution_steps_are_redacted_at_serialization(settings) -> None:
    store = Store(settings.data_path)
    run = store.create_execution_run(
        "smart_action", 1, "tech", "success", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test",
    )
    assert run.id is not None
    with store._connect() as connection:
        connection.execute(
            """
            insert into execution_steps
              (execution_run_id, ordinal, kind, name, status, started_at, finished_at,
               input_digest, output_digest, input_json, output_json, error_detail)
            values (?, 0, 'smart_action.invoke', 'legacy', 'success', ?, ?, 'd', 'd', ?, '{}', '')
            """,
            (
                run.id,
                "2026-08-01T09:00:00+00:00",
                "2026-08-01T09:01:00+00:00",
                '{"note":"password=legacy-secret"}',
            ),
        )
    client = TestClient(create_app(settings))

    detail = client.get(f"/executions/{run.id}")

    assert detail.status_code == 200
    assert "legacy-secret" not in detail.text


def test_template_gallery_artifacts_are_portable_validated_and_tenant_scoped(settings) -> None:
    client = TestClient(create_app(settings))
    created = client.post(
        "/workflow-templates/gallery",
        json={
            "source_template_id": "ticket-triage",
            "display_name": "Portable triage",
            "provenance": "operator review",
            "instructions": "Keep token=should-not-leak local.",
            "client_id": "acme",
        },
    )
    assert created.status_code == 200
    entry_id = created.json()["id"]

    exported = client.get(f"/workflow-templates/gallery/{entry_id}/export")
    assert exported.status_code == 200
    artifact = exported.json()
    assert artifact["format"] == "wait-local-agent.workflow-template"
    assert artifact["format_version"] == 1
    assert "client_id" not in artifact
    assert "should-not-leak" not in exported.text

    imported = client.post(
        "/workflow-templates/gallery/import",
        json={**artifact, "client_id": "beta"},
    )
    assert imported.status_code == 200
    assert imported.json()["client_id"] == "beta"
    assert imported.json()["enabled"] is False
    assert imported.json()["name"] == "Portable triage"

    invalid_source = client.post(
        "/workflow-templates/gallery/import",
        json={**artifact, "source_template_id": "not-a-template"},
    )
    invalid_format = client.post(
        "/workflow-templates/gallery/import",
        json={**artifact, "format_version": 2},
    )
    assert invalid_source.status_code == 404
    assert invalid_format.status_code == 422
    invalid_create = client.post(
        "/workflow-templates/gallery",
        json={"source_template_id": "ticket-triage", "provenance": "   ", "client_id": "acme"},
    )
    assert invalid_create.status_code == 422

    secure = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    store = Store(secure.data_path)
    _provision_bound_principal(store, "globex-viewer", "globex-viewer-token", "globex", "viewer")
    _provision_bound_principal(store, "globex-technician", "globex-technician-token", "globex", "technician")
    secure_client = TestClient(create_app(secure))
    assert secure_client.get(
        f"/workflow-templates/gallery/{entry_id}/export",
        headers=_auth("globex-viewer-token"),
    ).status_code == 404
    assert secure_client.post(
        "/workflow-templates/gallery/import",
        headers=_auth("globex-technician-token"),
        json={**artifact, "client_id": "acme"},
    ).status_code == 403
