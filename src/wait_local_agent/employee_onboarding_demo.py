"""Canonical local-fixture employee-onboarding consultant walkthrough.

This module composes existing discovery, environment, blueprint, architecture,
supervisor, evaluation, governance, and delivery primitives. It is deliberately
not a provider adapter or a second execution engine: every child uses the
existing ``AgentService`` with ``ticket-triage`` as a bounded local stand-in.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any, cast

from wait_local_agent.agents import AgentService
from wait_local_agent.config import Settings
from wait_local_agent.connectors import list_connector_statuses
from wait_local_agent.consultant import architect_solution_blueprint, parse_solution_blueprint
from wait_local_agent.copilot_studio import build_copilot_studio_plan
from wait_local_agent.delivery_plan import (
    build_consultant_artifact_review_package,
    build_consultant_delivery_plan,
)
from wait_local_agent.discovery import build_solution_discovery
from wait_local_agent.environment import discover_environment
from wait_local_agent.evaluation import AgentServiceEvaluationExecutor, execute_tool_contract
from wait_local_agent.governance import evaluate_solution_governance
from wait_local_agent.models import AgentDefinition, SolutionBlueprint
from wait_local_agent.power_apps import build_power_apps_artifact
from wait_local_agent.power_automate import build_power_automate_flow_plan
from wait_local_agent.rbac import Role
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.supervisor import execute_supervisor_delegation
from wait_local_agent.workflows import list_workflow_templates

CANONICAL_EMPLOYEE_ONBOARDING_REQUEST = (
    "Automate employee onboarding for a 500-person company using Microsoft 365, "
    "Entra, Intune, SharePoint, Teams, ConnectWise, NinjaOne, and Hudu. HR "
    "initiates onboarding. IT approves license assignment. Sensitive actions "
    "require approval. The manager must be notified. Everything must be auditable."
)

_FIXTURE_CHILDREN: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("identity-agent", "identity", ()),
    ("licensing-agent", "licensing", ("identity-agent",)),
    ("intune-agent", "intune", ("licensing-agent",)),
    ("psa-agent", "psa", ()),
    ("rmm-agent", "rmm", ("intune-agent",)),
    ("documentation-agent", "documentation", ()),
    ("communications-agent", "communications", ("documentation-agent",)),
)


class EmployeeOnboardingDemoError(ValueError):
    """Raised when the canonical fixture cannot be run safely."""


def run_employee_onboarding_demo(
    *,
    store: Store,
    settings: Settings,
    blueprint_payload: Mapping[str, object],
    client_id: str = "acme",
    entity_id: str = "TCK-1001",
    blueprint_id: str | None = None,
    persist_blueprint: bool = True,
) -> dict[str, Any]:
    """Run the bounded employee-onboarding scenario through existing services.

    The caller owns fixture seeding. This function refuses to invent a ticket or
    provider result, and returns explicit review/deployment boundaries when the
    local appliance has no external connector authorization.
    """

    if store.get_ticket(entity_id, client_id=client_id) is None:
        raise EmployeeOnboardingDemoError("employee-onboarding fixture requires a tenant-scoped ticket")
    if not isinstance(blueprint_payload, Mapping):
        raise EmployeeOnboardingDemoError("employee-onboarding blueprint must be an object")

    try:
        blueprint = parse_solution_blueprint(
            dict(blueprint_payload),
            client_id=client_id,
            created_by="employee-onboarding-demo",
            blueprint_id=blueprint_id,
        )
        environment = discover_environment(
            client_id=client_id,
            requested_systems=blueprint.systems,
            connector_statuses=list_connector_statuses(settings),
            configured_client_id=getattr(settings, "client_id", None),
        )
        discovery = build_solution_discovery(
            client_id=client_id,
            answers=blueprint.discovery,
            environment=environment,
        )
    except (TypeError, ValueError) as exc:
        raise EmployeeOnboardingDemoError(str(exc)) from exc

    discovered_blueprint = replace(
        blueprint,
        environment=tuple(cast(list[dict[str, object]], environment["systems"])),
        discovery=cast(dict[str, object], discovery["answered"]),
    )
    persisted_blueprint = (
        store.create_solution_blueprint(discovered_blueprint) if persist_blueprint else discovered_blueprint
    )

    smart_actions = SmartActionService(store, settings)
    agent_service = AgentService(store, settings, smart_actions)
    architecture = architect_solution_blueprint(
        persisted_blueprint,
        available_tool_ids=(tool.id for tool in agent_service.list_tools()),
        workflow_templates=list_workflow_templates(),
    )

    fixture_definitions = _create_fixture_definitions(agent_service, client_id)
    child_ids = [definition.id for definition in fixture_definitions]
    supervisor = execute_supervisor_delegation(
        client_id=client_id,
        entity_id=entity_id,
        task="Coordinate the bounded employee-onboarding review and stop for human approval.",
        child_agent_ids=child_ids,
        definitions=fixture_definitions,
        agent_service=agent_service,
        store=store,
        actor="employee-onboarding-demo",
        actor_role=Role.TECHNICIAN,
        input_payload={"ticket_id": entity_id},
    )

    evaluation_definition = fixture_definitions[0]
    evaluation = execute_tool_contract(
        [
            {
                "id": "local-onboarding-triage",
                "expected_tool_ids": ["ticket-triage"],
                "forbidden_tool_ids": ["m365-user-create", "communication-send"],
                "expected_approval_tool_ids": [],
            }
        ],
        AgentServiceEvaluationExecutor(
            agent_service,
            evaluation_definition,
            entity_id=entity_id,
            actor="employee-onboarding-evaluation",
            actor_role=Role.TECHNICIAN,
            input_payload={"ticket_id": entity_id},
            client_id=client_id,
        ),
    )
    governance = evaluate_solution_governance(architecture, [])
    review_artifacts = _build_review_artifacts(client_id)
    review_package, review_package_digest = build_consultant_artifact_review_package(
        client_id=client_id,
        artifacts=review_artifacts,
    )
    delivery = build_consultant_delivery_plan(
        client_id=client_id,
        architecture=architecture,
        evaluation=evaluation,
        governance=governance,
        deployment_targets=["Teams", "Power Automate", "Power Apps", "Dataverse"],
        review_artifacts=review_artifacts,
    )

    return {
        "format": "wait-local-agent.employee-onboarding-demo",
        "format_version": 1,
        "client_id": client_id,
        "entity_id": entity_id,
        "request": CANONICAL_EMPLOYEE_ONBOARDING_REQUEST,
        "mode": "local_fixture",
        "stages": {
            "discovery": discovery,
            "environment": environment,
            "blueprint": {
                "id": persisted_blueprint.id,
                "solution_name": persisted_blueprint.solution_name,
                "risk": persisted_blueprint.risk,
                "approval_policy": dict(persisted_blueprint.approvals),
            },
            "architecture": architecture,
            "supervisor": supervisor,
            "evaluation": evaluation,
            "governance": governance,
            "artifacts": {
                "status": "review_only",
                "items": review_artifacts,
                "package": review_package,
                "package_digest": review_package_digest,
                "deployment_package_generated": False,
                "deployment_started": False,
            },
            "delivery": delivery,
        },
        "fixture_child_agents": [
            {
                "id": definition.id,
                "role": role,
                "target_tools": _target_tools(persisted_blueprint, role),
                "local_fixture_tools": list(definition.enabled_tools),
                "depends_on": list(definition.depends_on_agent_ids),
            }
            for definition, (_, role, _) in zip(fixture_definitions, _FIXTURE_CHILDREN, strict=True)
        ],
        "boundaries": {
            "live_provider_execution": False,
            "artifact_generation": True,
            "artifact_generation_status": "review_only",
            "review_package_generated": True,
            "deployable_package_generated": False,
            "deployment_started": False,
            "production_deployment_requires_approval": True,
            "external_systems_require_environment_verification": True,
            "sensitive_operations_require_human_approval": True,
        },
        "audit": {
            "audit_event_count": len(store.list_audit_events(client_id)),
            "agent_run_count": len(store.list_agent_runs(client_id)),
        },
    }


def _create_fixture_definitions(agent_service: AgentService, client_id: str) -> list[AgentDefinition]:
    definitions: list[AgentDefinition] = []
    ids_by_role: dict[str, str] = {}
    for definition_name, role, dependency_roles in _FIXTURE_CHILDREN:
        dependencies = [ids_by_role[item] for item in dependency_roles]
        definition = agent_service.create(
            name=f"Employee onboarding {role} fixture",
            description=(
                f"Local fixture for the {role} onboarding specialist; target provider actions "
                "remain review-only."
            ),
            enabled=True,
            trigger="manual",
            entity_type="ticket",
            filters={},
            enabled_tools=["ticket-triage"],
            steps=[{"tool_id": "ticket-triage", "payload": {}}],
            max_steps=1,
            execution_timeout_seconds=30,
            client_id=client_id,
            depends_on_agent_ids=dependencies,
            context_sources=["ticket"],
        )
        definitions.append(definition)
        ids_by_role[definition_name] = definition.id
    return definitions


def _target_tools(blueprint: SolutionBlueprint, role: str) -> list[str]:
    return [
        tool
        for agent in blueprint.agents
        if role in agent.id or role in agent.name.casefold()
        for tool in agent.tools
    ]


def _build_review_artifacts(client_id: str) -> list[dict[str, Any]]:
    """Generate validated local manifests for the canonical Microsoft handoff."""

    return [
        build_power_apps_artifact(
            client_id=client_id,
            app_name="Employee onboarding workspace",
            entities=[
                {
                    "logical_name": "employee",
                    "display_name": "Employee",
                    "fields": [
                        {"name": "display_name", "type": "string", "required": True},
                        {"name": "start_date", "type": "date", "required": True},
                    ],
                }
            ],
            screens=[
                {"id": "employee_browse", "title": "Employees", "entity": "employee", "mode": "browse"},
                {"id": "employee_edit", "title": "Edit employee", "entity": "employee", "mode": "edit"},
            ],
            actions=[
                {"id": "employee_lookup", "connector_id": "m365", "method": "GET"},
                {
                    "id": "employee_create",
                    "connector_id": "m365",
                    "method": "POST",
                    "approval_required": True,
                },
            ],
        ),
        build_power_automate_flow_plan(
            client_id=client_id,
            workflow_id="employee_onboarding",
            workflow_name="Employee onboarding",
            trigger="HR onboarding request",
            steps=[
                {"id": "validate_manager", "name": "Validate manager", "kind": "condition"},
                {
                    "id": "prepare_identity",
                    "name": "Prepare Entra identity",
                    "tool_id": "m365_user_create",
                    "method": "POST",
                    "approval_required": True,
                },
                {
                    "id": "assign_license",
                    "name": "Assign Microsoft 365 license",
                    "tool_id": "m365_license_assign",
                    "method": "POST",
                    "approval_required": True,
                },
                {
                    "id": "notify_manager",
                    "name": "Notify manager in Teams",
                    "tool_id": "m365_teams_message",
                    "method": "POST",
                    "approval_required": True,
                },
            ],
        ),
        build_copilot_studio_plan(
            client_id=client_id,
            copilot_name="Employee onboarding copilot",
            business_goal="Guide HR through an auditable onboarding request.",
            topics=[
                {
                    "id": "onboarding_request",
                    "name": "Onboarding request",
                    "trigger_phrases": ["start onboarding", "new employee"],
                }
            ],
            knowledge_sources=["employee-handbook", "it-onboarding-runbook"],
            actions=[
                {"id": "lookup_employee", "connector_id": "m365", "method": "GET"},
                {
                    "id": "prepare_identity",
                    "connector_id": "m365",
                    "method": "POST",
                    "approval_required": True,
                },
            ],
        ),
    ]


__all__ = [
    "CANONICAL_EMPLOYEE_ONBOARDING_REQUEST",
    "EmployeeOnboardingDemoError",
    "run_employee_onboarding_demo",
]
