from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from starlette.requests import Request

from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import (
    DeliveryPlanRequest,
    DiscoveryBlueprintPromotionRequest,
    DiscoveryRequest,
    DiscoverySessionStartRequest,
    DiscoveryTurnRequest,
    EnvironmentDiscoveryRequest,
    EvaluationExecutionRequest,
    EvaluationRequest,
    GovernanceRequest,
    PowerAppsPlanRequest,
    PowerAutomatePlanRequest,
    PowerPlatformDeploymentRequest,
    SolutionBlueprintRequest,
    SupervisorRunRequest,
    TeamsMessageDraftRequest,
    create_app,
)
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store


def _endpoint(settings, path: str):
    app = create_app(settings)
    return next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and route.methods and "POST" in route.methods
    )


def _get_endpoint(settings, path: str):
    app = create_app(settings)
    return next(
        route.endpoint
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == path and route.methods and "GET" in route.methods
    )


def _technician(client_id: str = "acme") -> AuthContext:
    return AuthContext(role=Role.TECHNICIAN, presented_token="tech-token", client_id=client_id)


def _admin(client_id: str = "acme") -> AuthContext:
    return AuthContext(role=Role.ADMIN, presented_token="admin-token", client_id=client_id)


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/consultant/solutions/deployment-approvals",
            "headers": [],
            "query_string": b"",
            "scheme": "http",
            "client": ("test", 1234),
            "server": ("test", 80),
            "root_path": "",
        }
    )


def test_consultant_planning_routes_are_directly_callable_and_review_only(settings) -> None:
    discovery = _endpoint(settings, "/consultant/discovery")(
        DiscoveryRequest(
            client_id="acme",
            answers={
                "business_goal": "Reduce onboarding effort",
                "users": ["HR"],
                "knowledge": ["Handbook"],
                "systems": ["Entra"],
                "reads": ["Employee"],
                "changes": ["Create user"],
                "approvals": ["Create user"],
                "failure_handling": "Pause",
                "data_location": ["SharePoint"],
                "data_leaves_tenant": False,
            },
        ),
        _technician(),
    )
    power_apps = _endpoint(settings, "/consultant/power-apps/plan")(
        PowerAppsPlanRequest(
            client_id="acme",
            app_name="Onboarding",
            entities=[{"logical_name": "employee", "fields": []}],
            screens=[{"id": "browse", "entity": "employee"}],
            actions=[{"id": "lookup", "connector_id": "m365", "method": "GET"}],
        ),
        _technician(),
    )
    power_apps_artifact = _endpoint(settings, "/consultant/power-apps/build")(
        PowerAppsPlanRequest(
            client_id="acme",
            app_name="Onboarding",
            entities=[{"logical_name": "employee", "fields": []}],
            screens=[{"id": "browse", "entity": "employee"}],
            actions=[{"id": "lookup", "connector_id": "m365", "method": "GET"}],
        ),
        _technician(),
    )
    flow = _endpoint(settings, "/consultant/workflows/power-automate/plan")(
        PowerAutomatePlanRequest(
            client_id="acme",
            workflow_id="onboarding",
            workflow_name="Onboarding",
            trigger="HR request",
            steps=[{"id": "review", "name": "Review", "kind": "approval"}],
        ),
        _technician(),
    )
    delivery = _endpoint(settings, "/consultant/delivery-plan")(
        DeliveryPlanRequest(
            client_id="acme",
            architecture={"client_id": "acme", "readiness": "ready", "components": [], "approval_policy": {}},
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
        ),
        _technician(),
    )

    assert discovery["readiness"] == "ready_for_architecture"
    assert power_apps["dataverse_write_started"] is False
    assert power_apps_artifact["format"] == "wait-local-agent.power-apps-artifact"
    assert power_apps_artifact["deployment_started"] is False
    assert flow["export_status"] == "review_only"
    assert delivery["production_deployment_requires_approval"] is True


def test_flagship_blueprint_promotes_discovery_and_environment_into_architecture(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())
    created = _endpoint(settings, "/consultant/blueprints")(
        SolutionBlueprintRequest(**{**payload, "client_id": "acme"}),
        _technician(),
    )
    view = created
    assert view["discovery"]["business_goal"].startswith("Automate auditable")
    assert len(view["environment"]) == 8

    result = _get_endpoint(settings, "/consultant/blueprints/{blueprint_id}/architecture")(
        view["id"],
        _technician(),
    )
    assert result["readiness"] == "needs_review"
    assert result["open_items"] == [
        {
            "kind": "deployment",
            "component_id": "Teams",
            "detail": "deployment target is recorded but not provisioned by this local runtime",
        },
        {
            "kind": "deployment",
            "component_id": "Power Automate",
            "detail": "deployment target is recorded but not provisioned by this local runtime",
        },
        {
            "kind": "deployment",
            "component_id": "Power Apps",
            "detail": "deployment target is recorded but not provisioned by this local runtime",
        },
        {
            "kind": "deployment",
            "component_id": "Dataverse",
            "detail": "deployment target is recorded but not provisioned by this local runtime",
        },
    ]
    assert result["execution_started"] is False
    assert result["deployment_started"] is False
    assert {item["chosen_target"] for item in result["decisions"]} >= {
        "microsoft_graph",
        "psa",
        "rmm",
        "mcp",
        "power_automate",
        "power_app",
        "dataverse",
    }


def test_flagship_employee_onboarding_runs_review_evaluation_and_approval_gates(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())
    blueprint = _endpoint(settings, "/consultant/blueprints")(
        SolutionBlueprintRequest(**{**payload, "client_id": "acme"}),
        _technician(),
    )
    architecture = _get_endpoint(settings, "/consultant/blueprints/{blueprint_id}/architecture")(
        blueprint["id"],
        _technician(),
    )

    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = AgentService(store, settings, SmartActionService(store, settings))
    agent = service.create(
        name="Employee onboarding supervisor fixture",
        description="Synthetic local fixture for the employee onboarding blueprint",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    evaluation = _endpoint(settings, "/consultant/evaluations")(
        EvaluationRequest(
            test_set=[
                {
                    "id": "employee-onboarding-triage",
                    "expected_tool_ids": ["ticket-triage"],
                    "forbidden_tool_ids": [],
                    "expected_approval_tool_ids": [],
                }
            ],
            execution=EvaluationExecutionRequest(
                agent_id=agent.id,
                entity_id="TCK-1001",
                client_id="acme",
            ),
        ),
        _technician(),
    )
    assert evaluation["execution_mode"] == "controlled"
    assert evaluation["production_readiness"] == "pass"
    assert evaluation["cases"][0]["execution"]["execution_status"] == "completed"

    governance = _endpoint(settings, "/consultant/governance/evaluate")(
        GovernanceRequest(architecture=architecture, connector_artifacts=[]),
        _technician(),
    )
    assert governance["status"] == "needs_review"
    assert governance["deployment_started"] is False

    delivery = _endpoint(settings, "/consultant/delivery-plan")(
        DeliveryPlanRequest(
            client_id="acme",
            architecture=architecture,
            evaluation=evaluation,
            governance=governance,
            deployment_targets=payload["deployment"],
        ),
        _technician(),
    )
    assert delivery["production_readiness"] == "needs_review"
    assert delivery["production_deployment_requires_approval"] is True
    assert delivery["execution_started"] is False
    assert delivery["deployment_started"] is False

    approval_result = _endpoint(settings, "/consultant/solutions/deployment-approvals")(
        PowerPlatformDeploymentRequest(
            client_id="acme",
            solution_name="employee_onboarding",
            publisher_name="WAITConsulting",
            publisher_prefix="wlp",
            output_directory="/tmp/wait-employee-onboarding-solution",
            deployment_targets=[
                {"name": "dev", "environment_url": "https://dev.crm.dynamics.com"},
                {"name": "test", "environment_url": "https://test.crm.dynamics.com"},
            ],
            stage="dev",
        ),
        _request(),
        _technician(),
    )
    assert approval_result["approval"]["status"] == "pending"
    assert approval_result["approval"]["can_execute"] is False
    assert approval_result["plan"]["deployment_started"] is False


def test_discovery_promotion_persists_blueprint_without_starting_execution(settings) -> None:
    result = _endpoint(settings, "/consultant/discovery/promote")(
        DiscoveryBlueprintPromotionRequest(
            client_id="acme",
            solution_name="Employee onboarding review",
            risk="high",
            answers={
                "solution_name": "Employee onboarding",
                "business_goal": "Reduce manual onboarding work",
                "users": ["HR", "IT"],
                "knowledge": ["SharePoint HR policies"],
                "systems": ["Microsoft Entra", "Teams"],
                "reads": ["Employee record", "HR policy"],
                "changes": ["Create user", "Assign license"],
                "approvals": ["Assign license"],
                "failure_handling": "Pause and create an approval review",
                "licenses": ["Microsoft 365 E3"],
                "data_location": ["Tenant SharePoint"],
                "data_leaves_tenant": False,
            },
        ),
        _technician(),
    )

    assert result["blueprint"]["client_id"] == "acme"
    assert result["blueprint"]["solution"] == {"name": "Employee onboarding review"}
    assert result["blueprint"]["risk"] == "high"
    assert result["blueprint"]["approvals"] == {"assign_license": "human_review_required"}
    assert result["discovery"]["blueprint_candidate"]["approvals"] == {
        "Assign license": "human_review_required"
    }
    assert result["execution_started"] is False
    assert result["deployment_started"] is False
    persisted = Store(settings.data_path).list_solution_blueprints(client_id="acme")
    assert any(item.solution_name == "Employee onboarding review" for item in persisted)


def test_discovery_promotion_requires_complete_answers_and_tenant_scope(settings) -> None:
    with pytest.raises(HTTPException) as incomplete:
        _endpoint(settings, "/consultant/discovery/promote")(
            DiscoveryBlueprintPromotionRequest(
                client_id="acme",
                solution_name="Onboarding",
                risk="medium",
                answers={"business_goal": "Review onboarding"},
            ),
            _technician(),
        )
    assert incomplete.value.status_code == 422

    with pytest.raises(HTTPException) as foreign:
        _endpoint(settings, "/consultant/discovery/promote")(
            DiscoveryBlueprintPromotionRequest(
                client_id="beta",
                solution_name="Onboarding",
                risk="medium",
                answers={},
            ),
            _technician("acme"),
        )
    assert foreign.value.status_code == 403


def test_guided_discovery_sessions_progress_and_preserve_scope(settings) -> None:
    start = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(
            client_id="acme",
            opening_message="Reduce manual onboarding effort",
        ),
        _technician(),
    )
    assert start["session_id"].startswith("CDS-")
    assert start["answered"]["business_goal"] == "Reduce manual onboarding effort"
    assert start["next_question"]["id"] == "users"
    assert start["execution_started"] is False

    turn = _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
        start["session_id"],
        DiscoveryTurnRequest(client_id="acme", field="users", answer=["HR operations"]),
        _technician(),
    )
    assert turn["answered"]["users"] == ["HR operations"]
    assert turn["transcript"][-2]["role"] == "user"
    assert turn["transcript"][-1]["role"] == "assistant"

    with pytest.raises(HTTPException) as foreign:
        _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
            start["session_id"],
            DiscoveryTurnRequest(client_id="beta", field="knowledge", answer=["Handbook"]),
            _technician("beta"),
        )
    assert foreign.value.status_code == 404


def test_guided_discovery_session_turn_is_bounded(settings) -> None:
    start = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(client_id="acme", answers={"business_goal": "Review onboarding"}),
        _technician(),
    )
    session_id = start["session_id"]
    transcript = cast(
        list[dict[str, object]],
        [{"role": "assistant", "field": "users", "content": "Who uses this?"}] * 64,
    )
    Store(settings.data_path).update_consultant_discovery_session(
        session_id,
        client_id="acme",
        principal_id=_technician().approver_id or "api",
        status="active",
        answers={"business_goal": "Review onboarding"},
        transcript=transcript,
    )

    with pytest.raises(HTTPException) as bounded:
        _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
            session_id,
            DiscoveryTurnRequest(client_id="acme", field="users", answer=["HR"]),
            _technician(),
        )
    assert bounded.value.status_code == 422


def test_guided_discovery_session_rejects_impact_side_channel(settings) -> None:
    start = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(client_id="acme"),
        _technician(),
    )

    with pytest.raises(HTTPException) as rejected:
        _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
            start["session_id"],
            DiscoveryTurnRequest(client_id="acme", field="impact", answer={"monthly_runs": 1}),
            _technician(),
        )
    assert rejected.value.status_code == 422


def test_guided_discovery_admin_can_continue_explicit_tenant_without_bound_context(settings) -> None:
    start = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(
            client_id="acme",
            opening_message="Review onboarding",
        ),
        _admin(client_id=""),
    )

    turn = _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
        start["session_id"],
        DiscoveryTurnRequest(client_id="acme", field="users", answer=["HR"]),
        _admin(client_id=""),
    )

    assert turn["answered"]["users"] == ["HR"]


def test_power_platform_deployment_route_creates_approval_and_stays_gated(settings) -> None:
    request_approval = _endpoint(settings, "/consultant/solutions/deployment-approvals")(
        PowerPlatformDeploymentRequest(
            client_id="acme",
            solution_name="onboarding_review",
            publisher_name="WAITConsulting",
            publisher_prefix="wlp",
            output_directory="/tmp/wait-consultant-solution",
            deployment_targets=[
                {"name": "dev", "environment_url": "https://dev.crm.dynamics.com"},
                {"name": "test", "environment_url": "https://test.crm.dynamics.com"},
            ],
            stage="dev",
        ),
        _request(),
        _technician(),
    )

    assert request_approval["plan"]["deployment_started"] is False
    approval = request_approval["approval"]
    assert approval["action_type"] == "power_platform.solution_stage"
    assert approval["status"] == "pending"
    assert approval["can_execute"] is False
    assert approval["payload"]["credentials_included"] is False


def test_power_platform_deployment_route_rejects_foreign_tenant(settings) -> None:
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        _endpoint(settings, "/consultant/solutions/deployment-approvals")(
            PowerPlatformDeploymentRequest(
                client_id="beta",
                solution_name="onboarding_review",
                publisher_name="WAITConsulting",
                publisher_prefix="wlp",
                output_directory="/tmp/wait-consultant-solution",
                deployment_targets=[
                    {"name": "dev", "environment_url": "https://dev.crm.dynamics.com"},
                ],
            ),
            _request(),
            _technician("acme"),
        )


def test_power_platform_promotion_route_requires_evidence_for_test_and_prod(settings) -> None:
    endpoint = _endpoint(settings, "/consultant/solutions/deployment-approvals")
    base = {
        "client_id": "acme",
        "solution_name": "onboarding_review",
        "publisher_name": "WAITConsulting",
        "publisher_prefix": "wlp",
        "output_directory": "/tmp/wait-consultant-solution",
        "deployment_targets": [
            {"name": "dev", "environment_url": "https://dev.crm.dynamics.com"},
            {"name": "test", "environment_url": "https://test.crm.dynamics.com"},
            {"name": "prod", "environment_url": "https://prod.crm.dynamics.com"},
        ],
    }
    with pytest.raises(HTTPException, match="requires promotion_evidence") as missing:
        endpoint(
            PowerPlatformDeploymentRequest.model_validate({**base, "stage": "test"}),
            _request(),
            _technician(),
        )
    assert missing.value.status_code == 422

    promotion_evidence = {
        "source_stage": "dev",
        "source_status": "succeeded",
        "source_approval_request_id": 0,
        "artifact_digest": "sha256:" + "a" * 64,
        "evaluation": {"production_readiness": "pass", "case_count": 1},
        "governance": {"status": "pass"},
        "rollback": {
            "available": True,
            "strategy": "reimport_previous_package",
            "artifact_digest": "sha256:" + "b" * 64,
        },
    }
    source = endpoint(
        PowerPlatformDeploymentRequest.model_validate({**base, "stage": "dev"}),
        _request(),
        _technician(),
    )
    source_id = source["approval"]["id"]
    store = Store(settings.data_path)
    store.update_approval_request(source_id, "approved", approver_id="admin")
    store.record_approval_execution(
        source_id,
        status="succeeded",
        message="verified fixture stage",
        result={"status": "succeeded", "artifact_digest": promotion_evidence["artifact_digest"]},
        audit_event_type="power_platform.solution_stage",
    )
    promotion_evidence["source_approval_request_id"] = source_id
    approved_for_review = endpoint(
        PowerPlatformDeploymentRequest.model_validate(
            {**base, "stage": "test", "promotion_evidence": promotion_evidence}
        ),
        _request(),
        _technician(),
    )
    approval = approved_for_review["approval"]
    assert approval["status"] == "pending"
    assert approval["payload"]["promotion_evidence"]["source_stage"] == "dev"
    assert approved_for_review["plan"]["deployment_started"] is False


def test_teams_message_draft_is_native_graph_approval_gated(settings) -> None:
    draft = _endpoint(settings, "/connectors/m365/teams/message-drafts")(
        TeamsMessageDraftRequest(
            team_id="team-1",
            channel_id="channel-1",
            body="Welcome to the team",
            client_id="acme",
        ),
        _request(),
        _admin(),
    )

    assert draft["action_type"] == "teams.message.send"
    assert draft["status"] == "pending"
    assert draft["payload"]["connector"] == "m365-teams"
    assert draft["can_execute"] is False


def test_supervisor_run_orders_persisted_children_and_returns_child_runs(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = AgentService(store, settings, SmartActionService(store, settings))
    identity = service.create(
        name="Identity child",
        description="Identity review",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )
    security = service.create(
        name="Security child",
        description="Security review",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
        depends_on_agent_ids=[identity.id],
    )

    result = _endpoint(settings, "/consultant/supervisor/run")(
        SupervisorRunRequest(
            client_id="acme",
            entity_id="TCK-1001",
            task="Review onboarding",
            child_agent_ids=[security.id, identity.id],
            input={"ticket_id": "TCK-1001"},
        ),
        _technician(),
    )

    assert result["status"] == "completed"
    assert result["supervisor"]["ordered_child_agent_ids"] == [identity.id, security.id]
    assert [child["status"] for child in result["children"]] == ["completed", "completed"]


def test_controlled_evaluation_runs_existing_agent_in_local_fixture_mode(settings) -> None:
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = AgentService(store, settings, SmartActionService(store, settings))
    agent = service.create(
        name="Triage fixture",
        description="Local evaluation fixture",
        enabled=True,
        trigger="manual",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id="acme",
    )

    result = _endpoint(settings, "/consultant/evaluations")(
        EvaluationRequest(
            test_set=[
                {
                    "id": "triage",
                    "expected_tool_ids": ["ticket-triage"],
                    "forbidden_tool_ids": [],
                    "expected_approval_tool_ids": [],
                }
            ],
            execution=EvaluationExecutionRequest(
                agent_id=agent.id,
                entity_id="TCK-1001",
                client_id="acme",
            ),
        ),
        _technician(),
    )

    assert result["execution_started"] is True
    assert result["execution_mode"] == "controlled"
    assert result["production_readiness"] == "pass"
    assert result["cases"][0]["execution"]["execution_status"] == "completed"


def test_controlled_evaluation_rejects_non_demo_or_write_enabled_settings(settings) -> None:
    production_settings = settings.__class__(**{**settings.__dict__, "demo_mode": False})
    endpoint = _endpoint(production_settings, "/consultant/evaluations")

    with pytest.raises(HTTPException, match="local demo mode"):
        endpoint(
            EvaluationRequest(
                test_set=[{"id": "triage"}],
                execution=EvaluationExecutionRequest(
                    agent_id="fixture",
                    entity_id="TCK-1",
                    client_id="acme",
                ),
            ),
            _technician(),
        )


def test_environment_discovery_route_returns_explicit_local_evidence(settings) -> None:
    result = _endpoint(settings, "/consultant/environment-discovery")(
        EnvironmentDiscoveryRequest(client_id="acme", systems=["Microsoft 365", "Custom API"]),
        _technician(),
    )

    assert result["probe_performed"] is False
    systems = {item["name"]: item for item in result["systems"]}
    assert systems["Microsoft 365"]["status"] == "not_configured"
    assert systems["Custom API"]["status"] == "detected"


def test_consultant_planning_routes_reject_foreign_tenant(settings) -> None:
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        _endpoint(settings, "/consultant/discovery")(
            DiscoveryRequest(client_id="beta", answers={}),
            _technician("acme"),
        )
    with pytest.raises(HTTPException, match="outside authenticated scope"):
        _endpoint(settings, "/consultant/power-apps/build")(
            PowerAppsPlanRequest(
                client_id="beta",
                app_name="Onboarding",
                entities=[],
                screens=[],
                actions=[],
            ),
            _technician("acme"),
        )
