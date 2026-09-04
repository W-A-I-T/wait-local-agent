from __future__ import annotations

import hashlib
import sqlite3
import zipfile
from dataclasses import replace
from typing import cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import wait_local_agent.api.routers.consultant as consultant_module
from tests.api_helpers import _auth, _provision_bound_principal
from wait_local_agent.api.app import create_app
from wait_local_agent.api.schemas import PowerPlatformRollbackRequest
from wait_local_agent.power_platform_deployment import PowerPlatformDeploymentError
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.store import Store


def test_consultant_blueprints_are_tenant_scoped_and_inspectable_only(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "",
            "viewer_token": "",
        }
    )
    store = Store(secure_settings.data_path)
    _provision_bound_principal(store, "acme-technician", "tech-token", "acme", "technician")
    _provision_bound_principal(store, "acme-viewer", "viewer-token", "acme", "viewer")
    payload = {
        "solution": {"name": "Employee Onboarding Agent"},
        "business_goal": {"reduce_manual_onboarding": True},
        "users": ["HR", "IT"],
        "knowledge": ["Employee Handbook"],
        "systems": ["Microsoft Entra"],
        "agents": [
            {"id": "onboarding", "name": "Onboarding", "purpose": "Design onboarding"}
        ],
        "workflows": [
            {"id": "create-user", "name": "Create user", "trigger": "HR", "steps": ["Validate"]}
        ],
        "approvals": {"create_user": "HR"},
        "deployment": ["Teams"],
        "risk": "medium",
    }
    app = create_app(secure_settings)
    client = TestClient(app)
    created = client.post(
        "/consultant/blueprints",
        headers=_auth("tech-token"),
        json={**payload, "client_id": "acme"},
    )
    foreign_create = client.post(
        "/consultant/blueprints",
        headers=_auth("tech-token"),
        json={**payload, "client_id": "beta"},
    )
    viewer_list = client.get("/consultant/blueprints", headers=_auth("viewer-token"))
    viewer_detail = client.get(
        f"/consultant/blueprints/{created.json()['id']}",
        headers=_auth("viewer-token"),
    )
    viewer_architecture = client.get(
        f"/consultant/blueprints/{created.json()['id']}/architecture",
        headers=_auth("viewer-token"),
    )
    connector_definition = {
        "swagger": "2.0",
        "info": {"title": "Example API", "version": "1"},
        "host": "api.example.test",
        "schemes": ["https"],
        "paths": {
            "/health": {
                "get": {
                    "operationId": "health-check",
                    "responses": {"200": {"description": "ok"}},
                }
            }
        },
    }
    connector_validation = client.post(
        "/consultant/connectors/openapi/validate",
        headers=_auth("tech-token"),
        json={"connector_id": "example", "definition": connector_definition},
    )
    connector_generation = client.post(
        "/consultant/connectors/openapi/generate",
        headers=_auth("tech-token"),
        json={"connector_id": "example", "definition": connector_definition},
    )
    connector_viewer = client.post(
        "/consultant/connectors/openapi/generate",
        headers=_auth("viewer-token"),
        json={"connector_id": "example", "definition": connector_definition},
    )
    evaluation = client.post(
        "/consultant/evaluations",
        headers=_auth("tech-token"),
        json={
            "test_set": [
                {
                    "id": "onboarding",
                    "expected_tool_ids": ["m365-user-create"],
                    "forbidden_tool_ids": [],
                    "expected_approval_tool_ids": ["m365-user-create"],
                }
            ],
            "observations": {
                "onboarding": {
                    "tool_ids": ["m365-user-create"],
                    "approval_tool_ids": ["m365-user-create"],
                    "tenant_isolated": True,
                    "prompt_injection_blocked": True,
                }
            },
        },
    )
    governance = client.post(
        "/consultant/governance/evaluate",
        headers=_auth("tech-token"),
        json={
            "architecture": {
                "client_id": "acme",
                "readiness": "ready",
                "components": [],
                "open_items": [],
            },
            "connector_artifacts": [],
        },
    )
    power_apps = client.post(
        "/consultant/power-apps/plan",
        headers=_auth("tech-token"),
        json={
            "client_id": "acme",
            "app_name": "Onboarding",
            "entities": [{"logical_name": "employee", "fields": []}],
            "screens": [{"id": "employee_browse", "entity": "employee"}],
            "actions": [{"id": "employee_lookup", "connector_id": "m365", "method": "GET"}],
        },
    )
    discovery = client.post(
        "/consultant/discovery",
        headers=_auth("tech-token"),
        json={
            "client_id": "acme",
            "answers": {
                "business_goal": "Reduce onboarding effort",
                "users": ["HR"],
                "knowledge": ["SharePoint policies"],
                "systems": ["Microsoft Entra"],
                "reads": ["Employee record"],
                "changes": ["Create user"],
                "approvals": ["Create user"],
                "failure_handling": "Pause for review",
                "data_location": ["Tenant SharePoint"],
                "data_leaves_tenant": False,
            },
        },
    )
    use_cases = client.get(
        "/consultant/use-cases",
        headers=_auth("viewer-token"),
        params={"category": "teams"},
    )
    power_automate = client.post(
        "/consultant/workflows/power-automate/plan",
        headers=_auth("tech-token"),
        json={
            "client_id": "acme",
            "workflow_id": "employee_onboarding",
            "workflow_name": "Employee onboarding",
            "trigger": "HR request",
            "steps": [
                {"id": "validate", "name": "Validate manager", "kind": "condition"},
                {"id": "create_user", "name": "Create user", "method": "POST", "approval_required": True},
            ],
        },
    )
    monitoring = client.get(
        "/consultant/monitoring/agents",
        headers=_auth("viewer-token"),
    )
    admin_create = client.post(
        "/consultant/blueprints",
        headers=_auth("admin-token"),
        json={**payload, "client_id": "beta"},
    )
    admin_beta = client.get(
        "/consultant/blueprints",
        headers=_auth("admin-token"),
        params={"client_id": "beta"},
    )
    foreign_detail = client.get(
        f"/consultant/blueprints/{admin_create.json()['id']}",
        headers=_auth("viewer-token"),
    )
    foreign_list = client.get(
        "/consultant/blueprints",
        headers=_auth("viewer-token"),
        params={"client_id": "beta"},
    )
    assert created.status_code == 201
    assert created.json()["client_id"] == "acme"
    assert created.json()["solution"] == {"name": "Employee Onboarding Agent"}
    assert created.json()["agents"][0]["tools"] == []
    assert foreign_create.status_code == 403
    assert [item["client_id"] for item in viewer_list.json()] == ["acme"]
    assert viewer_detail.status_code == 200
    assert viewer_architecture.status_code == 200
    assert viewer_architecture.json()["readiness"] == "needs_review"
    assert viewer_architecture.json()["execution_started"] is False
    assert viewer_architecture.json()["decision_engine"]["execution_started"] is False
    assert viewer_architecture.json()["decisions"]
    assert connector_validation.status_code == 200
    assert connector_validation.json()["valid"] is True
    assert connector_generation.json()["credentials_included"] is False
    assert connector_viewer.status_code == 403
    assert evaluation.status_code == 200
    assert evaluation.json()["production_readiness"] == "pass"
    assert governance.status_code == 200
    assert governance.json()["status"] == "pass"
    assert power_apps.status_code == 200
    assert power_apps.json()["format"] == "wait-local-agent.power-apps-plan"
    assert power_apps.json()["deployment_started"] is False
    assert discovery.status_code == 200
    assert discovery.json()["readiness"] == "ready_for_architecture"
    assert use_cases.status_code == 200
    assert use_cases.json()["use_cases"][0]["id"] == "teams-ticket-triage"
    assert power_automate.status_code == 200
    assert power_automate.json()["format"] == "wait-local-agent.power-automate-flow-plan"
    assert power_automate.json()["deployment_started"] is False
    assert monitoring.status_code == 200
    assert monitoring.json()["payloads_exposed"] is False
    assert admin_create.status_code == 201
    assert [item["client_id"] for item in admin_beta.json()] == ["beta"]
    assert foreign_detail.status_code == 404
    assert foreign_list.status_code == 403
    invalid = client.post(
        "/consultant/blueprints",
        headers=_auth("tech-token"),
        json={**payload, "client_id": "acme", "risk": "critical"},
    )
    assert invalid.status_code == 422
    assert len(client.get("/consultant/blueprints", headers=_auth("viewer-token")).json()) == 1


def test_consultant_api_rejects_unscoped_and_malformed_review_inputs(settings) -> None:
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
    client = TestClient(create_app(secure_settings))

    invalid_calls = [
        ("/consultant/connectors/openapi/generate", {"connector_id": "bad", "definition": {}}),
        ("/consultant/evaluations", {"test_set": [], "observations": {}}),
        (
            "/consultant/evaluations",
            {
                "test_set": [
                    {
                        "id": "bounded-input",
                        "input": {str(index): index for index in range(17)},
                    }
                ],
                "observations": {
                    "bounded-input": {
                        "tool_ids": [],
                        "approval_tool_ids": [],
                        "tenant_isolated": True,
                        "prompt_injection_blocked": True,
                    }
                },
            },
        ),
        ("/consultant/governance/evaluate", {"architecture": {"client_id": "acme", "components": "bad"}}),
        (
            "/consultant/power-apps/plan",
            {
                "client_id": "acme",
                "app_name": "Onboarding",
                "entities": [{"logical_name": "employee", "fields": []}],
                "screens": [{"id": "browse", "entity": "employee"}],
                "actions": [{"id": "write", "connector_id": "m365", "method": "POST"}],
            },
        ),
        (
            "/consultant/discovery",
            {"client_id": "acme", "answers": {"unsupported": "value"}},
        ),
        (
            "/consultant/supervisor/plan",
            {"client_id": "acme", "task": "Review", "child_agent_ids": ["missing"]},
        ),
        (
            "/consultant/supervisor/run",
            {
                "client_id": "acme",
                "entity_id": "TCK-1",
                "task": "Review",
                "child_agent_ids": ["missing"],
            },
        ),
        (
            "/consultant/delivery-plan",
            {
                "client_id": "acme",
                "architecture": {"client_id": "beta"},
                "evaluation": {},
                "governance": {},
                "deployment_targets": ["Teams"],
            },
        ),
        (
            "/consultant/workflows/power-automate/plan",
            {
                "client_id": "acme",
                "workflow_id": "onboarding",
                "workflow_name": "Onboarding",
                "trigger": "HR",
                "steps": [{"id": "write", "name": "Write", "method": "POST"}],
            },
        ),
        (
            "/consultant/solutions/deployment-approvals",
            {
                "client_id": "acme",
                "solution_name": "onboarding",
                "publisher_name": "WAIT",
                "publisher_prefix": "wlp",
                "output_directory": "/tmp/wait-solution",
                "deployment_targets": [{"name": "dev", "environment_url": "http://unsafe"}],
            },
        ),
    ]
    for path, payload in invalid_calls:
        response = client.post(path, json=payload, headers=_auth("tech-token"))
        assert response.status_code == 422, (path, response.text)

    assert client.get("/consultant/blueprints/missing", headers=_auth("acme-viewer-token")).status_code == 404
    assert (
        client.get(
            "/consultant/blueprints",
            headers=_auth("acme-viewer-token"),
            params={"client_id": "beta"},
        ).status_code
        == 403
    )


def test_consultant_api_builds_review_artifacts_and_gates_deployment(settings) -> None:
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
    client = TestClient(create_app(secure_settings))
    deployment = {
        "client_id": "acme",
        "solution_name": "onboarding",
        "publisher_name": "WAIT",
        "publisher_prefix": "wlp",
        "output_directory": "/tmp/wait-solution",
        "deployment_targets": [{"name": "dev", "environment_url": "https://dev.crm.dynamics.com"}],
        "stage": "build",
    }
    power_apps = {
        "client_id": "acme",
        "app_name": "Onboarding",
        "entities": [{"logical_name": "employee", "display_name": "Employee", "fields": []}],
        "screens": [{"id": "browse", "title": "Browse", "entity": "employee", "mode": "browse"}],
        "actions": [{"id": "lookup", "connector_id": "m365", "method": "GET"}],
    }

    built = client.post("/consultant/power-apps/build", json=power_apps, headers=_auth("tech-token"))
    requested = client.post(
        "/consultant/solutions/deployment-approvals",
        json=deployment,
        headers=_auth("tech-token"),
    )
    request_id = requested.json()["approval"]["id"]
    pending = client.post(
        f"/consultant/solutions/deployment-approvals/{request_id}/execute",
        headers=_auth("admin-token"),
    )
    missing = client.post(
        "/consultant/solutions/deployment-approvals/99999/execute",
        headers=_auth("admin-token"),
    )

    assert built.status_code == 200
    assert built.json()["deployment_started"] is False
    assert requested.status_code == 201
    assert requested.json()["plan"]["approval_required_for_every_stage"] is True
    assert pending.status_code == 409
    assert missing.status_code == 404


def test_consultant_api_rollbacks_are_approval_backed_and_audited(settings, tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "power-platform"
    workspace.mkdir()
    artifact = workspace / "previous.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    digest = f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}"
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "allow_write_actions": True,
            "allow_power_platform_deployment": True,
            "power_platform_workspace": workspace,
        }
    )
    client = TestClient(create_app(secure_settings))
    payload = {
        "client_id": "acme",
        "solution_name": "onboarding",
        "publisher_name": "WAIT",
        "publisher_prefix": "wlp",
        "output_directory": str(workspace / "solution"),
        "deployment_targets": [{"name": "dev", "environment_url": "https://dev.crm.dynamics.com"}],
        "stage": "dev",
        "rollback_artifact_path": str(artifact),
        "rollback_evidence": {
            "available": True,
            "strategy": "reimport_previous_package",
            "artifact_digest": digest,
        },
    }
    requested = client.post(
        "/consultant/solutions/rollback-approvals",
        headers=_auth("tech-token"),
        json=payload,
    )
    request_id = requested.json()["approval"]["id"]
    pending = client.post(
        f"/consultant/solutions/rollback-approvals/{request_id}/execute",
        headers=_auth("admin-token"),
    )
    approved = client.post(
        f"/approval-requests/{request_id}",
        headers=_auth("tech-token"),
        json={"status": "approved", "comment": "rollback reviewed"},
    )
    monkeypatch.setattr(
        consultant_module,
        "execute_power_platform_rollback",
        lambda *args, **kwargs: {
            "format": "wait-local-agent.power-platform.rollback-result",
            "format_version": 1,
            "stage_id": "dev",
            "status": "succeeded",
            "message": "Power Platform rollback for dev completed.",
            "strategy": "reimport_previous_package",
            "artifact_digest": digest,
            "commands": [],
            "execution_started": True,
            "rollback_started": True,
            "deployment_started": True,
        },
    )
    executed = client.post(
        f"/consultant/solutions/rollback-approvals/{request_id}/execute",
        headers=_auth("admin-token"),
    )
    audit = client.get("/audit", headers=_auth("admin-token"))

    assert requested.status_code == 201
    assert requested.json()["approval"]["action_type"] == "power_platform.solution_rollback"
    assert pending.status_code == 409
    assert approved.status_code == 200
    assert executed.status_code == 200
    assert executed.json()["execution_status"] == "succeeded"
    assert any(event["event_type"] == "power_platform.solution_rollback" for event in audit.json())


def test_consultant_api_rollbacks_fail_closed_on_scope_digest_and_execution_errors(
    settings, tmp_path, monkeypatch
) -> None:
    workspace = tmp_path / "power-platform"
    workspace.mkdir()
    artifact = workspace / "previous.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    digest = f"sha256:{hashlib.sha256(artifact.read_bytes()).hexdigest()}"
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "allow_write_actions": True,
            "allow_power_platform_deployment": True,
            "power_platform_workspace": workspace,
        }
    )
    client = TestClient(create_app(secure_settings))
    payload = {
        "client_id": "acme",
        "solution_name": "onboarding",
        "publisher_name": "WAIT",
        "publisher_prefix": "wlp",
        "output_directory": str(workspace / "solution"),
        "deployment_targets": [{"name": "dev", "environment_url": "https://dev.crm.dynamics.com"}],
        "stage": "dev",
        "rollback_artifact_path": str(artifact),
        "rollback_evidence": {
            "available": True,
            "strategy": "reimport_previous_package",
            "artifact_digest": digest,
        },
    }
    rollback_evidence = cast(dict[str, object], payload["rollback_evidence"])
    mismatch: dict[str, object] = dict(payload)
    mismatch["rollback_evidence"] = {
        **rollback_evidence,
        "artifact_digest": "sha256:" + "0" * 64,
    }
    assert (
        client.post(
            "/consultant/solutions/rollback-approvals",
            headers=_auth("tech-token"),
            json=mismatch,
        ).status_code
        == 422
    )

    unscoped_settings = secure_settings.__class__(**{**secure_settings.__dict__, "client_id": ""})
    unscoped_app = create_app(unscoped_settings)
    rollback_endpoint = next(
        route.endpoint
        for route in unscoped_app.routes
        if isinstance(route, APIRoute) and route.path == "/consultant/solutions/rollback-approvals"
    )
    with pytest.raises(HTTPException, match="has no tenant"):
        rollback_endpoint(
            PowerPlatformRollbackRequest.model_validate(payload),
            None,
            AuthContext(role=Role.TECHNICIAN, presented_token="tenantless"),
        )
    assert (
        client.post(
            "/consultant/solutions/rollback-approvals/99999/execute",
            headers=_auth("admin-token"),
        ).status_code
        == 404
    )

    requested = client.post("/consultant/solutions/rollback-approvals", headers=_auth("tech-token"), json=payload)
    request_id = requested.json()["approval"]["id"]
    Store(secure_settings.data_path).update_approval_request(request_id, "approved")
    monkeypatch.setattr(
        consultant_module,
        "execute_power_platform_rollback",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PowerPlatformDeploymentError("provider boundary")
        ),
    )
    assert (
        client.post(
            f"/consultant/solutions/rollback-approvals/{request_id}/execute",
            headers=_auth("admin-token"),
        ).status_code
        == 422
    )
    store = Store(secure_settings.data_path)
    stored_payload = requested.json()["approval"]["payload"]
    malformed_stage = dict(stored_payload)
    malformed_stage["stage"] = 1
    stage_request = store.create_approval_request(
        "acme:onboarding:rollback:invalid-stage",
        "power_platform.solution_rollback",
        malformed_stage,
        client_id="acme",
    )
    store.update_approval_request(stage_request.id or 0, "approved")
    assert (
        client.post(
            f"/consultant/solutions/rollback-approvals/{stage_request.id}/execute",
            headers=_auth("admin-token"),
        ).status_code
        == 422
    )
    malformed_artifact = dict(stored_payload)
    malformed_artifact["rollback_artifact_path"] = 1
    artifact_request = store.create_approval_request(
        "acme:onboarding:rollback:invalid-artifact",
        "power_platform.solution_rollback",
        malformed_artifact,
        client_id="acme",
    )
    store.update_approval_request(artifact_request.id or 0, "approved")
    assert (
        client.post(
            f"/consultant/solutions/rollback-approvals/{artifact_request.id}/execute",
            headers=_auth("admin-token"),
        ).status_code
        == 422
    )
    runtime_request = store.create_approval_request(
        "acme:onboarding:rollback:runtime-error",
        "power_platform.solution_rollback",
        stored_payload,
        client_id="acme",
    )
    store.update_approval_request(runtime_request.id or 0, "approved")
    monkeypatch.setattr(
        consultant_module,
        "execute_power_platform_rollback",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider runtime unavailable")),
    )
    assert (
        client.post(
            f"/consultant/solutions/rollback-approvals/{runtime_request.id}/execute",
            headers=_auth("admin-token"),
        ).status_code
        == 409
    )


def test_guided_discovery_api_persists_turns_with_tenant_scope(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "acme",
            "admin_token": "admin-token",
            "tech_token": "tech-token",
        }
    )
    client = TestClient(create_app(secure_settings))
    start = client.post(
        "/consultant/discovery/sessions",
        headers=_auth("tech-token"),
        json={"client_id": "acme", "opening_message": "Reduce onboarding effort"},
    )
    assert start.status_code == 200
    session_id = start.json()["session_id"]
    assert start.json()["next_question"]["id"] == "users"

    turn = client.post(
        f"/consultant/discovery/sessions/{session_id}/turn",
        headers=_auth("tech-token"),
        json={"client_id": "acme", "field": "users", "answer": ["HR"]},
    )
    assert turn.status_code == 200
    assert turn.json()["answered"]["users"] == ["HR"]

    beta_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "client_id": "beta",
            "admin_token": "admin-token",
            "tech_token": "beta-token",
        }
    )
    foreign = TestClient(create_app(beta_settings)).post(
        f"/consultant/discovery/sessions/{session_id}/turn",
        headers=_auth("beta-token"),
        json={"client_id": "beta", "field": "knowledge", "answer": ["Handbook"]},
    )
    assert foreign.status_code == 404


def test_consultant_blueprint_requires_tenant_and_role(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    app = create_app(secure_settings)
    client = TestClient(app)
    minimal = {
        "solution": {"name": "Design"},
        "business_goal": {},
        "users": [],
        "knowledge": [],
        "systems": [],
        "agents": [],
        "workflows": [],
        "approvals": {},
        "deployment": [],
        "risk": "low",
    }
    viewer = client.post("/consultant/blueprints", headers=_auth("viewer-token"), json=minimal)
    no_tenant = client.post("/consultant/blueprints", headers=_auth("tech-token"), json=minimal)
    admin = client.post(
        "/consultant/blueprints",
        headers=_auth("admin-token"),
        json={**minimal, "client_id": "acme"},
    )
    detail_endpoint = next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/consultant/blueprints/{blueprint_id}"
    )
    with pytest.raises(HTTPException) as unbound_detail_error:
        detail_endpoint(admin.json()["id"], AuthContext(role=Role.VIEWER, presented_token="tenantless"))
    assert viewer.status_code == 403
    assert no_tenant.status_code == 403
    assert admin.status_code == 201
    assert unbound_detail_error.value.status_code == 404



def test_generate_blueprint_playbook_is_admin_scoped_disabled_and_versioned(settings) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
    )
    client = TestClient(create_app(secure_settings))
    blueprint_payload = {
        "solution": {"name": "Generated ticket assistant"},
        "business_goal": {"statement": "Reduce manual ticket handling."},
        "users": ["Technicians"],
        "knowledge": [],
        "systems": [],
        "agents": [{"id": "triage-agent", "name": "Triage agent", "purpose": "Triage tickets"}],
        "workflows": [
            {
                "id": "ticket-triage",
                "name": "Ticket triage",
                "trigger": "manual",
                "steps": ["Classify"],
            }
        ],
        "approvals": {},
        "deployment": [],
        "risk": "medium",
    }
    created = client.post(
        "/consultant/blueprints",
        headers=_auth("tech-token"),
        json={**blueprint_payload, "client_id": "acme"},
    )
    assert created.status_code == 201
    blueprint_id = created.json()["id"]

    lower_role = client.post(
        f"/consultant/blueprints/{blueprint_id}/generate-playbook",
        headers=_auth("tech-token"),
    )
    assert lower_role.status_code == 403

    generated = client.post(
        f"/consultant/blueprints/{blueprint_id}/generate-playbook",
        headers=_auth("admin-token"),
        params={"client_id": "acme"},
    )
    assert generated.status_code == 201
    first = generated.json()
    assert first["id"] == f"architect-{blueprint_id}"
    assert first["source_playbook_id"] == f"architect:{blueprint_id}"
    assert first["provenance"] == f"architect_blueprint:{blueprint_id}"
    assert first["enabled"] is False
    assert first["client_id"] == "acme"
    assert any(step["kind"] == "agent" for step in first["definition"]["steps"])
    workflow_steps = [step for step in first["definition"]["steps"] if step["kind"] == "workflow"]
    assert [step["workflow_template_id"] for step in workflow_steps] == ["ticket-triage"]

    regenerated = client.post(
        f"/consultant/blueprints/{blueprint_id}/generate-playbook",
        headers=_auth("admin-token"),
        params={"client_id": "acme"},
    )
    assert regenerated.status_code == 200
    second = regenerated.json()
    assert second["id"] == first["id"]
    assert second["version"] == first["version"] + 1
    assert second["enabled"] is False
    entries = client.get("/msp/playbook-entries", headers=_auth("admin-token"), params={"client_id": "acme"})
    assert entries.status_code == 200
    assert len([entry for entry in entries.json() if entry["source_playbook_id"] == first["source_playbook_id"]]) == 1

    foreign = client.post(
        "/consultant/blueprints",
        headers=_auth("admin-token"),
        json={**blueprint_payload, "client_id": "beta"},
    )
    assert foreign.status_code == 201
    assert (
        client.post(
            f"/consultant/blueprints/{foreign.json()['id']}/generate-playbook",
            headers=_auth("admin-token"),
            params={"client_id": "acme"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/consultant/blueprints/missing/generate-playbook",
            headers=_auth("admin-token"),
            params={"client_id": "acme"},
        ).status_code
        == 404
    )


def test_generate_blueprint_playbook_updates_after_concurrent_create(settings, monkeypatch) -> None:
    secure_settings = replace(
        settings,
        demo_mode=False,
        client_id="acme",
        admin_token="admin-token",
        tech_token="tech-token",
    )
    app = create_app(secure_settings)
    client = TestClient(app)
    blueprint_payload = {
        "solution": {"name": "Concurrent generated assistant"},
        "business_goal": {"statement": "Reduce manual ticket handling."},
        "users": ["Technicians"],
        "knowledge": [],
        "systems": [],
        "agents": [{"id": "triage-agent", "name": "Triage agent", "purpose": "Triage tickets"}],
        "workflows": [],
        "approvals": {},
        "deployment": [],
        "risk": "medium",
    }
    created = client.post(
        "/consultant/blueprints",
        headers=_auth("tech-token"),
        json={**blueprint_payload, "client_id": "acme"},
    )
    assert created.status_code == 201
    blueprint_id = created.json()["id"]
    store = app.state.store
    original_create = store.create_msp_playbook_entry
    create_calls = 0

    def create_then_raise(*args, **kwargs):
        nonlocal create_calls
        create_calls += 1
        created_entry = original_create(*args, **kwargs)
        if create_calls == 1:
            raise sqlite3.IntegrityError("simulated concurrent create")
        return created_entry

    monkeypatch.setattr(store, "create_msp_playbook_entry", create_then_raise)

    generated = client.post(
        f"/consultant/blueprints/{blueprint_id}/generate-playbook",
        headers=_auth("admin-token"),
        params={"client_id": "acme"},
    )

    assert generated.status_code == 200
    assert create_calls == 1
    assert generated.json()["id"] == f"architect-{blueprint_id}"
    persisted = store.get_msp_playbook_entry(f"architect-{blueprint_id}", "acme")
    assert persisted is not None
    assert persisted.enabled is False
