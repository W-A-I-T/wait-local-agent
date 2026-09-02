from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from fastapi import HTTPException, Response
from fastapi.routing import APIRoute
from starlette.requests import Request

import wait_local_agent.api.app as app_module
from tests.support import ingest_local
from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import (
    CopilotStudioPlanRequest,
    DeliveryPlanRequest,
    DiscoveryBlueprintPromotionRequest,
    DiscoveryRequest,
    DiscoverySessionStartRequest,
    DiscoveryTurnRequest,
    EmployeeOnboardingDemoRequest,
    EnvironmentDiscoveryRequest,
    EvaluationExecutionRequest,
    EvaluationRequest,
    GovernanceRequest,
    OpenApiConnectorRequest,
    PowerAppsPlanRequest,
    PowerAutomatePlanRequest,
    PowerPlatformDeploymentRequest,
    PowerPlatformPackageMaterializationRequest,
    PowerPlatformPackageRequest,
    PowerPlatformPackageValidationRequest,
    SolutionBlueprintRequest,
    SupervisorRunRequest,
    TeamsMessageDraftRequest,
    create_app,
)
from wait_local_agent.consultant import generate_playbook_from_blueprint
from wait_local_agent.discovery import _QUESTION_DEFS
from wait_local_agent.models import BlueprintAgent, BlueprintWorkflow, SolutionBlueprint
from wait_local_agent.rbac import AuthContext, Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.workflows import list_workflow_templates


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
    return AuthContext(
        role=Role.TECHNICIAN,
        presented_token="tech-token",
        client_id=client_id,
        client_ids=frozenset({client_id}) if client_id else frozenset(),
    )


def _admin(client_id: str = "acme") -> AuthContext:
    return AuthContext(
        role=Role.ADMIN,
        presented_token="admin-token",
        client_id=client_id,
        is_msp_admin=True,
    )


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


def test_generate_playbook_compiler_lowers_only_resolved_primitives() -> None:
    blueprint = SolutionBlueprint(
        id="bp-generate",
        client_id="acme",
        created_by="tester",
        created_at="2026-08-18T00:00:00+00:00",
        updated_at="2026-08-18T00:00:00+00:00",
        solution_name="Blueprint Compiler Fixture",
        business_goal={"statement": "Reduce manual ticket handling."},
        users=("Technicians",),
        knowledge=(),
        systems=(),
        agents=(BlueprintAgent("agent-one", "Triage agent", "Triage tickets"),),
        workflows=(BlueprintWorkflow("ticket-triage", "Ticket triage", "manual", ("Classify",)),),
        approvals={},
        deployment=(),
        risk="high",
    )
    architecture = {
        "decisions": [
            {
                "id": "decision-workflow",
                "capability": "Ticket triage",
                "chosen_target": "wait_workflow",
                "dependencies": ["ticket-triage"],
                "why": "A real local workflow template matched.",
            },
            {
                "id": "decision-agent",
                "capability": "Triage agent",
                "chosen_target": "wait_agent",
                "dependencies": ["invented-tool-id"],
                "why": "The local agent runtime is the selected boundary.",
            },
            {
                "id": "decision-unsupported",
                "capability": "External system",
                "chosen_target": "unsupported",
                "dependencies": ["invented-workflow-id"],
                "why": "No local primitive was resolved.",
            },
            {
                "id": "decision-unresolved-workflow",
                "capability": "Design-only workflow",
                "chosen_target": "wait_workflow",
                "dependencies": ["invented-workflow-id"],
                "status": "needs_review",
                "why": "The workflow has no exact local template.",
            },
        ]
    }

    compiled = generate_playbook_from_blueprint(blueprint, architecture)
    repeated = generate_playbook_from_blueprint(blueprint, architecture)
    assert compiled == repeated
    assert compiled["id"] == "architect-bp-generate"
    assert compiled["name"] == blueprint.solution_name
    assert compiled["risk_level"] == "high"
    assert compiled["local_fixture"] is False
    steps = cast(list[dict[str, object]], compiled["steps"])
    assert [step["kind"] for step in steps] == ["agent", "review", "review", "workflow"]
    workflow = next(step for step in steps if step["kind"] == "workflow")
    assert workflow["workflow_template_id"] == "ticket-triage"
    assert all(
        step.get("workflow_template_id") in {"ticket-triage", None}
        for step in steps
    )
    assert all(
        "workflow_template_id" not in step
        for step in steps
        if step["kind"] in {"agent", "review"}
    )


def _compiler_blueprint(
    *,
    business_goal: dict[str, str | bool | int],
    blueprint_id: str = "bp-branches",
    solution_name: str = "Compiler branch fixture",
) -> SolutionBlueprint:
    return SolutionBlueprint(
        id=blueprint_id,
        client_id="acme",
        created_by="tester",
        created_at="2026-08-18T00:00:00+00:00",
        updated_at="2026-08-18T00:00:00+00:00",
        solution_name=solution_name,
        business_goal=business_goal,
        users=(),
        knowledge=(),
        systems=(),
        agents=(),
        workflows=(),
        approvals={},
        deployment=(),
        risk="low",
    )


def test_generate_playbook_uses_components_and_derives_targets() -> None:
    blueprint = _compiler_blueprint(business_goal={"statement": "Use components."})
    compiled = generate_playbook_from_blueprint(
        blueprint,
        {
            "components": [
                {"id": "agent-component", "kind": "agent", "name": "Agent"},
                {"id": "review-component", "kind": "unknown", "name": "Unknown"},
                {"id": "workflow-component", "kind": "workflow", "name": "Workflow"},
            ]
        },
    )

    steps = cast(list[dict[str, object]], compiled["steps"])
    assert [step["kind"] for step in steps] == ["agent", "review", "review"]
    assert steps[0]["id"] == "step-agent-component"
    assert steps[1]["description"] == "Manual review required: No deterministic primitive was resolved."


def test_generate_playbook_resolves_workflows_from_each_supported_location() -> None:
    blueprint = _compiler_blueprint(business_goal={"description": "Resolve templates."})
    template_id = list_workflow_templates()[0].id
    compiled = generate_playbook_from_blueprint(
        blueprint,
        {
            "decisions": [
                {"id": "template", "chosen_target": "wait_workflow", "template": {"id": template_id}},
                {
                    "id": "dependency",
                    "chosen_target": "wait_workflow",
                    "dependencies": [template_id],
                },
                {
                    "id": "explicit",
                    "chosen_target": "wait_workflow",
                    "workflow_template_id": template_id,
                },
                {
                    "id": "missing",
                    "chosen_target": "wait_workflow",
                    "workflow_template_id": "not-a-real-template",
                    "why": "Catalog lookup failed.",
                },
                {"id": "agent", "chosen_target": "wait_agent"},
                {"id": "fallback", "chosen_target": "unsupported", "why": "Needs review."},
            ]
        },
    )

    steps = cast(list[dict[str, object]], compiled["steps"])
    by_id = {str(step["id"]): step for step in steps}
    assert by_id["step-agent"]["kind"] == "agent"
    assert by_id["step-fallback"]["kind"] == "review"
    assert by_id["step-missing"]["kind"] == "review"
    assert by_id["step-missing"]["description"] == "Manual review required: Catalog lookup failed."
    assert by_id["step-fallback"]["description"] == "Manual review required: Needs review."
    assert [by_id[f"step-{name}"]["workflow_template_id"] for name in ("dependency", "explicit", "template")] == [
        template_id,
        template_id,
        template_id,
    ]


@pytest.mark.parametrize(
    ("business_goal", "expected"),
    [
        ({"statement": "Statement goal."}, "Statement goal."),
        ({"description": "Description goal."}, "Description goal."),
        ({}, "Review the declared solution blueprint."),
    ],
)
def test_generate_playbook_goal_fallbacks(
    business_goal: dict[str, str | bool | int], expected: str
) -> None:
    compiled = generate_playbook_from_blueprint(
        _compiler_blueprint(business_goal=business_goal), {"decisions": []}
    )

    assert compiled["description"] == f"Generated from the blueprint goal: {expected}"


def test_generate_playbook_bounds_blueprint_derived_text() -> None:
    long_text = "A\x00B\n" + "x" * 700
    blueprint = _compiler_blueprint(
        business_goal={"statement": long_text},
        solution_name=long_text,
    )
    compiled = generate_playbook_from_blueprint(
        blueprint,
        {
            "decisions": [
                {
                    "id": "long-decision",
                    "capability": long_text,
                    "chosen_target": "unsupported",
                    "why": long_text,
                }
            ]
        },
    )

    steps = cast(list[dict[str, object]], compiled["steps"])
    name = cast(str, compiled["name"])
    description = cast(str, compiled["description"])
    step_name = cast(str, steps[0]["name"])
    step_description = cast(str, steps[0]["description"])
    assert len(name) <= 500
    assert len(description) <= 500
    assert "\x00" not in name
    assert "\n" not in name
    assert len(step_name) <= 500
    assert len(step_description) <= 500
    assert "\x00" not in step_description
    assert "\n" not in step_description


def test_generate_playbook_persists_bounded_blueprint_text(settings) -> None:
    long_name = "Z" * 240
    long_goal = "G" * 500
    blueprint = _compiler_blueprint(
        business_goal={"statement": long_goal},
        blueprint_id="bp-persisted-text",
        solution_name=long_name,
    )
    store = Store(settings.data_path)
    store.create_solution_blueprint(blueprint)

    endpoint = _endpoint(settings, "/consultant/blueprints/{blueprint_id}/generate-playbook")
    entry = endpoint(blueprint.id, _admin(), Response(), client_id="acme")
    persisted = store.get_msp_playbook_entry(entry["id"], "acme")

    assert persisted is not None
    definition = json.loads(persisted.definition_json)
    assert len(definition["name"]) <= 500
    assert len(definition["description"]) <= 500


def test_generate_playbook_marks_unresolved_status_as_review() -> None:
    compiled = generate_playbook_from_blueprint(
        _compiler_blueprint(business_goal={"statement": "Review unresolved agent."}),
        {
            "decisions": [
                {
                    "id": "unresolved-agent",
                    "capability": "Unresolved agent",
                    "chosen_target": "wait_agent",
                    "status": "needs_review",
                    "why": "The requested tool is not available.",
                }
            ]
        },
    )

    step = cast(list[dict[str, object]], compiled["steps"])[0]
    assert step["kind"] == "review"
    assert "workflow_template_id" not in step


def test_generate_blueprint_playbook_endpoint_persists_one_disabled_revision(settings) -> None:
    blueprint = _endpoint(settings, "/consultant/blueprints")(
        SolutionBlueprintRequest(
            client_id="acme",
            solution={"name": "Generated ticket assistant"},
            business_goal={"statement": "Reduce manual ticket handling."},
            users=["Technicians"],
            knowledge=[],
            systems=[],
            agents=[{"id": "triage-agent", "name": "Triage agent", "purpose": "Triage tickets"}],
            workflows=[
                {
                    "id": "ticket-triage",
                    "name": "Ticket triage",
                    "trigger": "manual",
                    "steps": ["Classify"],
                }
            ],
            approvals={},
            deployment=[],
            risk="medium",
        ),
        _technician(),
    )
    endpoint = _endpoint(settings, "/consultant/blueprints/{blueprint_id}/generate-playbook")
    first_response = Response()
    first = endpoint(blueprint["id"], _admin(), first_response, client_id="acme")
    second = endpoint(blueprint["id"], _admin(), Response(), client_id="acme")

    assert first_response.status_code == 201
    assert first["id"] == f"architect-{blueprint['id']}"
    assert first["enabled"] is False
    assert first["source_playbook_id"] == f"architect:{blueprint['id']}"
    assert first["provenance"] == f"architect_blueprint:{blueprint['id']}"
    assert second["id"] == first["id"]
    assert second["version"] == 2
    assert second["enabled"] is False
    store = Store(settings.data_path)
    assert len(store.list_msp_playbook_entries("acme")) == 1
    assert len(store.list_msp_playbook_revisions(first["id"], "acme")) == 2


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
            review_artifacts=[
                {
                    "format": "wait-local-agent.power-automate-flow-plan",
                    "client_id": "acme",
                    "credentials_included": False,
                    "execution_started": False,
                    "deployment_started": False,
                }
            ],
        ),
        _technician(),
    )

    assert discovery["readiness"] == "ready_for_architecture"
    assert power_apps["dataverse_write_started"] is False
    assert power_apps_artifact["format"] == "wait-local-agent.power-apps-artifact"
    assert power_apps_artifact["deployment_started"] is False
    assert flow["export_status"] == "review_only"
    assert delivery["production_deployment_requires_approval"] is True
    assert delivery["summary"]["review_artifacts_prepared"] == 1
    assert delivery["review_package_generated"] is True
    assert delivery["delivery_bundle_generated"] is True
    assert delivery["delivery_bundle_status"] == "review_only"
    assert delivery["delivery_bundle"]["manifest"]["deployable"] is False
    assert delivery["deployment_package_generated"] is False

    copilot = _endpoint(settings, "/consultant/copilot-studio/plan")(
        CopilotStudioPlanRequest(
            client_id="acme",
            copilot_name="Employee onboarding copilot",
            business_goal="Guide HR through an auditable onboarding request.",
            topics=[
                {
                    "id": "onboarding_request",
                    "name": "Onboarding request",
                    "trigger_phrases": ["start onboarding"],
                }
            ],
            knowledge_sources=["employee-handbook"],
            actions=[
                {"id": "prepare_identity", "connector_id": "m365", "method": "POST", "approval_required": True}
            ],
        ),
        _technician(),
    )
    assert copilot["target"] == "microsoft_copilot_studio"
    assert copilot["generation_status"] == "review_only"
    assert copilot["deployment_started"] is False


def test_power_platform_package_routes_scope_roles_and_preserve_local_boundaries(settings) -> None:
    build = _endpoint(settings, "/consultant/power-platform/package")
    package = build(
        PowerPlatformPackageRequest(
            client_id="acme",
            solution_name="onboarding",
            publisher_name="WAITConsulting",
            publisher_prefix="wait",
            output_directory="/tmp/wait-onboarding-source",
        ),
        _technician(),
    )
    assert package["deployable"] is True
    assert package["execution_started"] is False
    assert package["deployment_started"] is False

    validate = _endpoint(settings, "/consultant/power-platform/package/validate")
    checked = validate(PowerPlatformPackageValidationRequest(package=package), _technician())
    assert checked["valid"] is True
    with pytest.raises(HTTPException) as cross_tenant:
        validate(PowerPlatformPackageValidationRequest(package=package, client_id="other"), _technician())
    assert cross_tenant.value.status_code == 403

    materialize = _endpoint(settings, "/consultant/power-platform/package/materialize")
    with pytest.raises(HTTPException) as technician:
        materialize(PowerPlatformPackageMaterializationRequest(package=package), _technician())
    assert technician.value.status_code == 403
    blocked = materialize(PowerPlatformPackageMaterializationRequest(package=package), _admin())
    assert blocked["status"] == "blocked"
    assert blocked["execution_started"] is False
    assert blocked["deployment_started"] is False

    delivery = _endpoint(settings, "/consultant/delivery-plan")(
        DeliveryPlanRequest(
            client_id="acme",
            architecture={"client_id": "acme", "readiness": "ready", "components": [], "approval_policy": {}},
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
            review_artifacts=[{"client_id": "acme", "credentials_included": False}],
            deployable_package=package,
        ),
        _technician(),
    )
    assert delivery["delivery_bundle"]["manifest"]["deployable"] is False
    assert delivery["deployable_source_package_digest"] == package["package_digest"]

    with pytest.raises(HTTPException) as malformed:
        build(
            PowerPlatformPackageRequest(
                client_id="acme",
                solution_name="onboarding",
                publisher_name="WAITConsulting",
                publisher_prefix="wait",
                output_directory="/tmp/wait-onboarding-source",
                artifacts=[{"client_id": []}],
            ),
            _technician(),
        )
    assert malformed.value.status_code == 422


def test_copilot_studio_plan_route_scopes_tenant_and_maps_validation(settings) -> None:
    endpoint = _endpoint(settings, "/consultant/copilot-studio/plan")
    request = CopilotStudioPlanRequest(
        client_id="acme",
        copilot_name="Employee onboarding copilot",
        business_goal="Guide HR through an auditable onboarding request.",
        actions=[{"id": "write", "connector_id": "m365", "method": "POST", "approval_required": False}],
    )

    with pytest.raises(HTTPException) as forbidden:
        endpoint(request, _technician(client_id="other"))
    assert forbidden.value.status_code == 403

    with pytest.raises(HTTPException) as invalid:
        endpoint(request, _technician())
    assert invalid.value.status_code == 422


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
    assert result["supervisor"]["mode"] == "supervisor"
    assert len(result["supervisor"]["children"]) == len(payload["agents"])
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
    child_map = json.loads(Path("examples/consultant/employee-onboarding-child-agent-map.json").read_text())
    blueprint_agents = {agent["id"]: agent for agent in payload["agents"]}
    assert set(blueprint_agents) == {child["id"] for child in child_map["child_agents"]}
    assert child_map["mode"] == "local_fixture"
    assert child_map["live_provider_execution"] is False
    assert child_map["deployment_started"] is False
    for child in child_map["child_agents"]:
        assert child["target_tools"] == blueprint_agents[child["id"]]["tools"]
        assert child["local_fixture_tools"] == ["ticket-triage"]
    blueprint = _endpoint(settings, "/consultant/blueprints")(
        SolutionBlueprintRequest(**{**payload, "client_id": "acme"}),
        _technician(),
    )
    architecture = _get_endpoint(settings, "/consultant/blueprints/{blueprint_id}/architecture")(
        blueprint["id"],
        _technician(),
    )

    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update tickets set client_id = 'acme'")
    service = AgentService(store, settings, SmartActionService(store, settings))

    runtime_ids: dict[str, str] = {}
    for child in child_map["child_agents"]:
        dependencies = [runtime_ids[dependency_id] for dependency_id in child["depends_on"]]
        definition = service.create(
            name=f"{child['role'].title()} onboarding fixture",
            description="Local fixture child for bounded employee-onboarding orchestration.",
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=child["local_fixture_tools"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id="acme",
            depends_on_agent_ids=dependencies,
        )
        runtime_ids[child["id"]] = definition.id

    supervisor_result = _endpoint(settings, "/consultant/supervisor/run")(
        SupervisorRunRequest(
            client_id="acme",
            entity_id="TCK-1001",
            task=payload["business_goal"]["statement"],
            child_agent_ids=[runtime_ids[child["id"]] for child in child_map["child_agents"]],
            input={"ticket_id": "TCK-1001", "fixture_mode": child_map["mode"]},
        ),
        _technician(),
    )
    assert supervisor_result["status"] == "completed"
    assert supervisor_result["execution_started"] is True
    assert supervisor_result["cross_tenant_context"] is False
    assert len(supervisor_result["children"]) == len(child_map["child_agents"])
    assert all(child["status"] == "completed" for child in supervisor_result["children"])
    assert len(store.list_agent_runs(client_id="acme")) == len(child_map["child_agents"])

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
                    "required_security_dimensions": ["rbac", "unexpected_writes"],
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
    assert evaluation["dimensions"]["rbac"] == 100.0
    assert evaluation["dimensions"]["unexpected_writes"] == 100.0
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


def test_guided_discovery_sessions_can_be_listed_and_resumed_with_scope(settings) -> None:
    start = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(
            client_id="acme",
            opening_message="Review onboarding",
        ),
        _technician(),
    )

    listed = _get_endpoint(settings, "/consultant/discovery/sessions")(_technician())
    assert [item["session_id"] for item in listed] == [start["session_id"]]
    assert listed[0]["transcript"][-1]["role"] == "assistant"
    assert listed[0]["blueprint_id"] is None
    assert isinstance(listed[0]["updated_at"], str)

    resumed = _get_endpoint(settings, "/consultant/discovery/sessions/{session_id}")(start["session_id"], _technician())
    assert resumed["session_id"] == start["session_id"]
    assert resumed["answered"]["business_goal"] == "Review onboarding"
    assert resumed["transcript"] == listed[0]["transcript"]

    with pytest.raises(HTTPException) as foreign:
        _get_endpoint(settings, "/consultant/discovery/sessions/{session_id}")(start["session_id"], _technician("beta"))
    assert foreign.value.status_code == 404


def test_guided_discovery_session_turns_to_completion_promotes_blueprint_and_enforces_cap(settings) -> None:
    question_defs = {cast(str, question["id"]): question for question in _QUESTION_DEFS}
    result = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(
            client_id="acme",
            opening_message="Reduce manual employee onboarding effort",
            answers={"solution_name": "Employee onboarding"},
        ),
        _technician(),
    )

    turn_limit = (len(_QUESTION_DEFS) * 2) + 5
    for _ in range(turn_limit):
        if result["status"] == "complete":
            break
        next_question = result["next_question"]
        assert isinstance(next_question, dict), f"active session did not return next_question: {result}"
        field = cast(str, next_question["id"])
        question = question_defs.get(field)
        assert question is not None, f"API returned unknown discovery question: {field}"
        if question["kind"] == "boolean":
            answer: object = False
        elif question["kind"] == "list":
            answer = ["Evidence"]
        else:
            answer = "Evidence"
        result = _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
            result["session_id"],
            DiscoveryTurnRequest(client_id="acme", field=field, answer=answer),
            _technician(),
        )
    else:
        pytest.fail(f"guided discovery did not complete within {turn_limit} turns: {result}")

    assert result["status"] == "complete"
    assert result["session_status"] == "completed"
    assert isinstance(result["blueprint_id"], str)
    session_id = cast(str, result["session_id"])
    store = Store(settings.data_path)
    session = store.get_consultant_discovery_session(
        session_id,
        client_id="acme",
        principal_id=_technician().approver_id or "api",
    )
    assert session is not None
    assert session.status == "completed"
    read_back = _get_endpoint(settings, "/consultant/discovery/sessions/{session_id}")(
        session_id,
        _technician(),
    )
    assert read_back["status"] == "complete"
    assert read_back["session_status"] == "completed"
    listed = _get_endpoint(settings, "/consultant/discovery/sessions")(_technician())
    listed_session = next(item for item in listed if item["session_id"] == session_id)
    assert listed_session["status"] == "complete"
    assert listed_session["session_status"] == "completed"
    blueprint = store.get_solution_blueprint(result["blueprint_id"], client_id="acme")
    assert blueprint is not None
    assert blueprint.solution_name == "Employee onboarding"

    capped = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(client_id="acme", opening_message="Check turn cap"),
        _technician(),
    )
    for _ in range(31):
        _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
            capped["session_id"],
            DiscoveryTurnRequest(client_id="acme", field="users", answer=["HR"]),
            _technician(),
        )
    with pytest.raises(HTTPException, match="turn limit"):
        _endpoint(settings, "/consultant/discovery/sessions/{session_id}/turn")(
            capped["session_id"],
            DiscoveryTurnRequest(client_id="acme", field="users", answer=["HR"]),
            _technician(),
        )


def test_guided_discovery_store_rejects_unscoped_and_invalid_updates(settings) -> None:
    store = Store(settings.data_path)
    with pytest.raises(ValueError, match="client scope"):
        store.create_consultant_discovery_session(
            client_id="",
            principal_id="technician",
            answers={},
            transcript=[],
        )
    with pytest.raises(ValueError, match="principal identity"):
        store.create_consultant_discovery_session(
            client_id="acme",
            principal_id="",
            answers={},
            transcript=[],
        )
    assert store.list_consultant_discovery_sessions(client_id="", principal_id="technician") == []
    assert (
        store.update_consultant_discovery_session(
            "missing",
            client_id="",
            principal_id="technician",
            status="active",
            answers={},
            transcript=[],
        )
        is None
    )
    session = store.create_consultant_discovery_session(
        client_id="acme",
        principal_id="technician",
        answers={"business_goal": "Review onboarding"},
        transcript=[],
    )
    with pytest.raises(ValueError, match="status is invalid"):
        store.update_consultant_discovery_session(
            session.id,
            client_id="acme",
            principal_id="technician",
            status="invalid",
            answers={},
            transcript=[],
        )


def test_guided_discovery_store_persists_completed_status_without_raising(settings) -> None:
    store = Store(settings.data_path)
    session = store.create_consultant_discovery_session(
        client_id="acme",
        principal_id="technician",
        answers={"business_goal": "Review onboarding"},
        transcript=[],
    )

    updated = store.update_consultant_discovery_session(
        session.id,
        client_id="acme",
        principal_id="technician",
        status="completed",
        answers={"business_goal": "Review onboarding", "users": ["HR"]},
        transcript=[{"role": "user", "field": "users", "content": ["HR"]}],
    )

    assert updated is not None
    assert updated.status == "completed"
    reloaded = store.get_consultant_discovery_session(
        session.id,
        client_id="acme",
        principal_id="technician",
    )
    assert reloaded is not None
    assert reloaded.status == "completed"


def test_completed_guided_discovery_promotes_a_tenant_scoped_blueprint(settings) -> None:
    result = _endpoint(settings, "/consultant/discovery/sessions")(
        DiscoverySessionStartRequest(
            client_id="acme",
            answers={
                "solution_name": "Employee onboarding",
                "business_goal": "Automate employee onboarding",
                "users": ["HR", "IT"],
                "knowledge": ["Employee handbook"],
                "systems": ["Microsoft 365", "Entra"],
                "reads": ["Employee record"],
                "changes": ["Prepare identity"],
                "approvals": ["Identity creation"],
                "failure_handling": "Pause for human review",
                "data_location": ["Customer tenant"],
                "data_leaves_tenant": False,
                "licenses": ["Microsoft 365 E3"],
                "current_process": "HR submits a request and IT provisions access.",
                "owners": ["HR operations"],
                "approvers": ["IT manager"],
                "sensitive_operations": ["Identity creation"],
                "compliance": ["Least privilege"],
                "data_residency": ["Customer tenant"],
                "existing_apis": ["Microsoft Graph"],
                "existing_automation": ["HR request process"],
                "channels": ["Teams"],
                "expected_volume": "40 per month",
                "business_value": "Reduce provisioning time",
                "success_metrics": ["Time to provision"],
                "rollback_expectations": "Pause before irreversible changes.",
            },
        ),
        _technician(),
    )

    assert result["status"] == "complete"
    assert isinstance(result["blueprint_id"], str)
    blueprint = Store(settings.data_path).get_solution_blueprint(result["blueprint_id"], client_id="acme")
    assert blueprint is not None
    assert blueprint.solution_name == "Employee onboarding"
    assert blueprint.discovery["business_goal"] == "Automate employee onboarding"


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


def test_power_platform_deployment_route_records_approved_execution(settings, monkeypatch) -> None:
    request_approval = _endpoint(settings, "/consultant/solutions/deployment-approvals")(
        PowerPlatformDeploymentRequest(
            client_id="acme",
            solution_name="onboarding_execution",
            publisher_name="WAITConsulting",
            publisher_prefix="wlp",
            output_directory="/tmp/wait-consultant-solution",
            deployment_targets=[{"name": "dev", "environment_url": "https://dev.crm.dynamics.com"}],
            stage="build",
        ),
        _request(),
        _technician(),
    )
    approval_id = request_approval["approval"]["id"]
    Store(settings.data_path).update_approval_request(approval_id, "approved", approver_id="admin")

    def fake_execute(*args, **kwargs):
        assert kwargs["approved"] is True
        return {
            "status": "succeeded",
            "message": "bounded PAC fixture succeeded",
            "stage": "build",
            "artifact_digest": "sha256:" + "a" * 64,
        }

    monkeypatch.setattr("wait_local_agent.api.app.execute_power_platform_stage", fake_execute)
    result = _endpoint(settings, "/consultant/solutions/deployment-approvals/{request_id}/execute")(
        approval_id,
        _request(),
        _admin(),
    )

    assert result["status"] == "approved"
    assert result["execution_status"] == "succeeded"
    assert result["output"]["status"] == "succeeded"
    persisted = Store(settings.data_path).get_approval_request(approval_id)
    assert persisted is not None
    assert persisted.status == "approved"
    assert persisted.execution_status == "succeeded"


def test_power_platform_stage_execution_rejects_already_executed_approval(settings, monkeypatch) -> None:
    execute = _endpoint(settings, "/consultant/solutions/deployment-approvals/{request_id}/execute")
    store = Store(settings.data_path)
    calls: list[object] = []

    def unexpected_execute(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("PAC execution must not run for a terminal approval")

    monkeypatch.setattr("wait_local_agent.api.app.execute_power_platform_stage", unexpected_execute)

    for terminal_status in ("succeeded", "verified", "unverified", "submitted"):
        approval = store.create_approval_request(
            f"acme:onboarding:stage:{terminal_status}",
            "power_platform.solution_stage",
            {
                "format": "wait-local-agent.power-platform.deployment-approval",
                "format_version": 1,
                "client_id": "acme",
                "solution_name": "onboarding",
                "publisher_name": "WAITConsulting",
                "publisher_prefix": "wlp",
                "output_directory": "/tmp/wait-consultant-solution",
                "deployment_targets": [{"name": "dev", "environment_url": "https://dev.crm.dynamics.com"}],
                "stage": "build",
                "promotion_evidence": {},
                "credentials_included": False,
            },
            client_id="acme",
        )
        approval_id = approval.id or 0
        store.update_approval_request(approval_id, "approved", approver_id="admin")
        store.record_approval_execution(
            approval_id,
            status=terminal_status,
            message="terminal execution fixture",
            result={"status": terminal_status, "evidence": "preserve"},
            audit_event_type="power_platform.solution_stage",
        )
        before = store.get_approval_request(approval_id)
        assert before is not None

        with pytest.raises(HTTPException) as exc_info:
            execute(approval_id, _request(), _admin())

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "deployment approval request has already executed"
        assert calls == []
        after = store.get_approval_request(approval_id)
        assert after == before


def test_power_platform_rollback_execution_rejects_already_executed_approval(settings, monkeypatch) -> None:
    execute = _endpoint(settings, "/consultant/solutions/rollback-approvals/{request_id}/execute")
    store = Store(settings.data_path)
    calls: list[object] = []

    def unexpected_execute(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("PAC execution must not run for a terminal approval")

    monkeypatch.setattr("wait_local_agent.api.app.execute_power_platform_rollback", unexpected_execute)

    for terminal_status in ("succeeded", "verified", "unverified", "submitted"):
        approval = store.create_approval_request(
            f"acme:onboarding:rollback:{terminal_status}",
            "power_platform.solution_rollback",
            {"stage": "dev"},
            client_id="acme",
        )
        approval_id = approval.id or 0
        store.update_approval_request(approval_id, "approved", approver_id="admin")
        store.record_approval_execution(
            approval_id,
            status=terminal_status,
            message="terminal execution fixture",
            result={"status": terminal_status, "evidence": "preserve"},
            audit_event_type="power_platform.solution_rollback",
        )
        before = store.get_approval_request(approval_id)
        assert before is not None

        with pytest.raises(HTTPException) as exc_info:
            execute(approval_id, _request(), _admin())

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == "rollback approval request has already executed"
        assert calls == []
        after = store.get_approval_request(approval_id)
        assert after == before


def test_power_platform_stage_execution_still_runs_for_a_fresh_approval(settings, monkeypatch) -> None:
    request_approval = _endpoint(settings, "/consultant/solutions/deployment-approvals")(
        PowerPlatformDeploymentRequest(
            client_id="acme",
            solution_name="onboarding_fresh_execution",
            publisher_name="WAITConsulting",
            publisher_prefix="wlp",
            output_directory="/tmp/wait-consultant-solution",
            deployment_targets=[{"name": "dev", "environment_url": "https://dev.crm.dynamics.com"}],
            stage="build",
        ),
        _request(),
        _technician(),
    )
    approval_id = request_approval["approval"]["id"]
    store = Store(settings.data_path)
    store.update_approval_request(approval_id, "approved", approver_id="admin")
    calls: list[object] = []

    def fake_execute(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "succeeded",
            "message": "fresh approval fixture succeeded",
            "stage": "build",
            "artifact_digest": "sha256:" + "a" * 64,
        }

    monkeypatch.setattr("wait_local_agent.api.app.execute_power_platform_stage", fake_execute)
    result = _endpoint(settings, "/consultant/solutions/deployment-approvals/{request_id}/execute")(
        approval_id,
        _request(),
        _admin(),
    )

    assert result["execution_status"] == "succeeded"
    assert calls


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
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
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
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
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
                    "required_security_dimensions": ["tool_injection", "secret_leakage"],
                    "secret_input_keys": ["temporary_password"],
                }
            ],
            execution=EvaluationExecutionRequest(
                agent_id=agent.id,
                entity_id="TCK-1001",
                client_id="acme",
                input={"temporary_password": "fixture-secret"},
            ),
        ),
        _technician(),
    )

    assert result["execution_started"] is True
    assert result["execution_mode"] == "controlled"
    assert result["production_readiness"] == "pass"
    assert result["cases"][0]["execution"]["execution_status"] == "completed"
    assert result["cases"][0]["checks"]["tool_injection"] is True
    assert result["cases"][0]["checks"]["secret_leakage"] is True
    assert "fixture-secret" not in str(result)


def test_controlled_evaluation_rejects_non_demo_or_write_enabled_settings(settings) -> None:
    request = EvaluationRequest(
        test_set=[{"id": "triage"}],
        execution=EvaluationExecutionRequest(
            agent_id="fixture",
            entity_id="TCK-1",
            client_id="acme",
        ),
    )
    rejected_settings = settings.__class__(
        **{**settings.__dict__, "demo_mode": False, "api_token": "api-token"}
    )

    with pytest.raises(HTTPException, match="local demo mode"):
        _endpoint(rejected_settings, "/consultant/evaluations")(request, _technician())


def test_employee_onboarding_demo_endpoint_composes_existing_local_fixture(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute("update tickets set client_id = 'acme'")

    result = _endpoint(settings, "/consultant/demos/employee-onboarding")(
        EmployeeOnboardingDemoRequest(
            client_id="acme",
            entity_id="TCK-1001",
            blueprint=payload,
        ),
        _technician(),
    )

    assert result["format"] == "wait-local-agent.employee-onboarding-demo"
    assert result["mode"] == "local_fixture"
    assert result["stages"]["supervisor"]["status"] == "completed"
    assert result["stages"]["evaluation"]["production_readiness"] == "pass"
    assert result["stages"]["artifacts"]["status"] == "review_only"
    assert result["stages"]["artifacts"]["deployment_package_generated"] is False
    assert result["boundaries"]["live_provider_execution"] is False
    assert result["boundaries"]["artifact_generation_status"] == "review_only"
    assert result["boundaries"]["deployable_package_generated"] is True
    assert result["boundaries"]["deployable_package_status"] == "deployable_source"
    assert result["boundaries"]["deployable_package_digest"].startswith("sha256:")
    assert result["boundaries"]["deployment_started"] is False


def test_employee_onboarding_demo_endpoint_resolves_persisted_blueprint_in_scope(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())
    blueprint = _endpoint(settings, "/consultant/blueprints")(
        SolutionBlueprintRequest(**{**payload, "client_id": "acme"}),
        _technician(),
    )
    store = Store(settings.data_path)
    ingest_local(store, Path("examples/sample_tickets/tickets.json"))
    with store._connect() as connection:  # noqa: SLF001 - bind the isolated fixture tenant.
        connection.execute("update tickets set client_id = 'acme'")

    result = _endpoint(settings, "/consultant/demos/employee-onboarding")(
        EmployeeOnboardingDemoRequest(
            client_id="acme",
            blueprint_id=blueprint["id"],
            entity_id="TCK-1001",
        ),
        _technician(),
    )

    assert result["client_id"] == "acme"
    assert result["stages"]["blueprint"]["id"] == blueprint["id"]
    assert len(Store(settings.data_path).list_solution_blueprints(client_id="acme")) == 1


def test_employee_onboarding_demo_endpoint_enforces_local_mode_and_tenant_scope(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())
    request = EmployeeOnboardingDemoRequest(client_id="acme", blueprint=payload)

    with pytest.raises(HTTPException, match="tenant scope") as missing_scope:
        _endpoint(settings, "/consultant/demos/employee-onboarding")(request, _technician(client_id=""))
    assert missing_scope.value.status_code == 403

    with pytest.raises(HTTPException, match="outside authenticated scope"):
        _endpoint(settings, "/consultant/demos/employee-onboarding")(request, _technician(client_id="beta"))

    secured_settings = settings.__class__(
        **{**settings.__dict__, "demo_mode": False, "api_token": "api-token"}
    )
    with pytest.raises(HTTPException, match="local demo mode"):
        _endpoint(secured_settings, "/consultant/demos/employee-onboarding")(request, _technician())

    with pytest.raises(HTTPException, match="exactly one"):
        _endpoint(settings, "/consultant/demos/employee-onboarding")(
            EmployeeOnboardingDemoRequest(client_id="acme", blueprint_id="bp_missing", blueprint=payload),
            _technician(),
        )

    with pytest.raises(HTTPException, match="solution blueprint not found"):
        _endpoint(settings, "/consultant/demos/employee-onboarding")(
            EmployeeOnboardingDemoRequest(client_id="acme", blueprint_id="bp_missing"),
            _technician(),
        )


def test_employee_onboarding_demo_endpoint_does_not_invent_fixture_ticket(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())

    with pytest.raises(HTTPException, match="tenant-scoped ticket") as missing_ticket:
        _endpoint(settings, "/consultant/demos/employee-onboarding")(
            EmployeeOnboardingDemoRequest(client_id="acme", blueprint=payload),
            _technician(),
        )
    assert missing_ticket.value.status_code == 422


def test_consultant_blueprint_reads_preserve_tenant_scope(settings) -> None:
    payload = json.loads(Path("examples/consultant/employee-onboarding-blueprint.json").read_text())
    blueprint = _endpoint(settings, "/consultant/blueprints")(
        SolutionBlueprintRequest(**{**payload, "client_id": "acme"}),
        _technician(),
    )

    with pytest.raises(HTTPException, match="no tenant") as missing_scope:
        _get_endpoint(settings, "/consultant/blueprints")(_technician(client_id=""), "acme")
    assert missing_scope.value.status_code == 403

    with pytest.raises(HTTPException, match="no tenant") as architecture_scope:
        _get_endpoint(settings, "/consultant/blueprints/{blueprint_id}/architecture")(
            blueprint["id"],
            _technician(client_id=""),
        )
    assert architecture_scope.value.status_code == 403

    with pytest.raises(HTTPException, match="not found") as missing_blueprint:
        _get_endpoint(settings, "/consultant/blueprints/{blueprint_id}/architecture")(
            "bp-missing",
            _technician(),
        )
    assert missing_blueprint.value.status_code == 404


def test_consultant_routes_reject_missing_tenant_and_invalid_connector_definitions(settings) -> None:
    power_apps_request = PowerAppsPlanRequest(
        client_id="acme",
        app_name="Onboarding",
        entities=[],
        screens=[],
        actions=[],
    )
    with pytest.raises(HTTPException, match="no tenant"):
        _endpoint(settings, "/consultant/power-apps/plan")(power_apps_request, _technician(client_id=""))
    with pytest.raises(HTTPException, match="no tenant"):
        _endpoint(settings, "/consultant/power-apps/build")(power_apps_request, _technician(client_id=""))

    connector_request = OpenApiConnectorRequest(connector_id="employee-api", definition={})
    with pytest.raises(HTTPException, match="OpenAPI") as validation_error:
        _endpoint(settings, "/consultant/connectors/openapi/validate")(connector_request, _technician())
    assert validation_error.value.status_code == 422
    with pytest.raises(HTTPException, match="OpenAPI") as generation_error:
        _endpoint(settings, "/consultant/connectors/openapi/generate")(connector_request, _technician())
    assert generation_error.value.status_code == 422

    with pytest.raises(HTTPException, match="no tenant") as discovery_error:
        _endpoint(settings, "/consultant/discovery")(
            DiscoveryRequest(client_id="acme", answers={}),
            _technician(client_id=""),
        )
    assert discovery_error.value.status_code == 403
    with pytest.raises(HTTPException, match="no tenant") as promotion_error:
        _endpoint(settings, "/consultant/discovery/promote")(
            DiscoveryBlueprintPromotionRequest(client_id="acme", solution_name="Onboarding", risk="medium", answers={}),
            _technician(client_id=""),
        )
    assert promotion_error.value.status_code == 403


def test_environment_discovery_route_returns_explicit_local_evidence(settings) -> None:
    result = _endpoint(settings, "/consultant/environment-discovery")(
        EnvironmentDiscoveryRequest(client_id="acme", systems=["Microsoft 365", "Custom API"]),
        _technician(),
    )

    assert result["probe_performed"] is False
    systems = {item["name"]: item for item in result["systems"]}
    assert systems["Microsoft 365"]["status"] == "not_configured"
    assert systems["Custom API"]["status"] == "detected"


def test_power_platform_cli_status_route_surfaces_server_owned_prerequisites(monkeypatch, settings) -> None:
    monkeypatch.setattr(
        app_module,
        "power_platform_cli_status",
        lambda active_settings: {
            "available": True,
            "path": "/usr/bin/pac",
            "version": "2.4.1",
            "commands_executed": True,
        },
    )

    result = _get_endpoint(settings, "/consultant/power-platform/cli-status")(_technician())

    assert result == {
        "available": True,
        "path": "/usr/bin/pac",
        "version": "2.4.1",
        "commands_executed": True,
        "minimum_version": "2.4.1",
        "version_compatible": True,
        "allow_write_actions": False,
        "allow_power_platform_deployment": False,
        "workspace_exists": False,
    }


def test_environment_discovery_route_records_probe_request_without_claiming_success(settings) -> None:
    result = _endpoint(settings, "/consultant/environment-discovery")(
        EnvironmentDiscoveryRequest(client_id="acme", systems=["Microsoft 365"], probe=True),
        _technician(),
    )

    assert result["probe_requested"] is True
    assert result["probe_performed"] is False
    assert result["systems"][0]["status"] == "not_configured"


def test_environment_discovery_does_not_construct_probe_clients_when_http_probing_is_disabled(
    monkeypatch, settings
) -> None:
    active = settings.__class__(
        **{
            **settings.__dict__,
            "m365_graph_base_url": "https://graph.example",
            "m365_access_token": "fixture-token",
            "allow_http_probing": False,
        }
    )
    calls: list[object] = []

    def unexpected_probe(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("probe clients must not be constructed when HTTP probing is disabled")

    monkeypatch.setattr(app_module, "probe_connector_health", unexpected_probe)
    result = _endpoint(active, "/consultant/environment-discovery")(
        EnvironmentDiscoveryRequest(client_id="acme", systems=["Microsoft 365"], probe=True),
        _technician(),
    )

    assert result["probe_performed"] is False
    assert calls == []


def test_environment_discovery_route_projects_positive_health_evidence_and_audits(monkeypatch, settings) -> None:
    active = settings.__class__(
        **{
            **settings.__dict__,
            "allow_http_probing": True,
            "client_id": "acme",
            "m365_graph_base_url": "https://graph.example",
            "m365_access_token": "fixture-token",
        }
    )
    monkeypatch.setattr(
        app_module,
        "probe_connector_health",
        lambda connector_ids, active_settings, **clients: {
            connector_id: {"passed": True, "layer": "connector", "message": "health succeeded"}
            for connector_id in connector_ids
        },
    )

    result = _endpoint(active, "/consultant/environment-discovery")(
        EnvironmentDiscoveryRequest(client_id="acme", systems=["Microsoft 365"], probe=True),
        _technician(),
    )

    assert result["probe_performed"] is True
    assert result["systems"][0]["status"] == "authorized"
    assert result["systems"][0]["evidence"][-1] == "provider_health_response"
    audit_events = Store(active.data_path).list_audit_events(client_id="acme")
    assert any(event.event_type == "consultant.environment_discovery" for event in audit_events)


def test_environment_discovery_does_not_probe_foreign_tenant_configuration(monkeypatch, settings) -> None:
    active = settings.__class__(
        **{
            **settings.__dict__,
            "allow_http_probing": True,
            "client_id": "beta",
            "m365_graph_base_url": "https://graph.example",
            "m365_access_token": "fixture-token",
        }
    )
    calls: list[str] = []

    def probe(connector_ids, active_settings, **clients):
        calls.extend(connector_ids)
        return {}

    monkeypatch.setattr(app_module, "probe_connector_health", probe)
    result = _endpoint(active, "/consultant/environment-discovery")(
        EnvironmentDiscoveryRequest(client_id="acme", systems=["Microsoft 365"], probe=True),
        _technician(),
    )

    assert calls == []
    assert result["systems"][0]["status"] == "permission-limited"


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
