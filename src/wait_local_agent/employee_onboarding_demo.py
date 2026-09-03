"""Canonical local-fixture employee-onboarding consultant walkthrough.

This module composes existing discovery, environment, blueprint, architecture,
supervisor, evaluation, governance, and delivery primitives. It is deliberately
not a provider adapter or a second execution engine: every child uses the
existing ``AgentService`` with ``ticket-triage`` as a bounded local stand-in.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
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
from wait_local_agent.power_platform_package import build_power_platform_package
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

_SYSTEM_CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "identity",
        ("entra", "active directory", "identity", "directory", "okta", "auth", "sso", "m365", "microsoft 365"),
    ),
    ("licensing", ("license", "licensing", "subscription")),
    ("endpoint", ("intune", "ninjaone", "jamf", "endpoint", "device", "workstation")),
    ("psa", ("connectwise", "halopsa", "halo psa", "syncro", "servicenow", "autotask", "psa", "ticket")),
    (
        "documentation",
        ("hudu", "it glue", "sharepoint", "confluence", "notion", "documentation", "knowledge", "wiki"),
    ),
    ("communications", ("teams", "slack", "email", "communication", "messaging", "notification")),
    ("data", ("dataverse", "database", "postgres", "mysql", "sql", "data warehouse")),
)


@dataclass(frozen=True)
class _FixtureChildSpec:
    key: str
    role: str
    category: str
    systems: tuple[str, ...]
    dependencies: tuple[str, ...]


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
    output_directory: str | None = None,
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

    fixture_definitions, fixture_specs = _create_fixture_definitions(
        agent_service,
        client_id,
        persisted_blueprint,
    )
    child_ids = [definition.id for definition in fixture_definitions]
    supervisor = execute_supervisor_delegation(
        client_id=client_id,
        entity_id=entity_id,
        task=(f"Coordinate the bounded {persisted_blueprint.solution_name} review and stop for human approval."),
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
    design_handoffs = _build_design_handoffs(client_id)
    review_package, review_package_digest = build_consultant_artifact_review_package(
        client_id=client_id,
        artifacts=review_artifacts,
    )
    deployable_package = build_power_platform_package(
        client_id=client_id,
        solution_name="employee_onboarding",
        publisher_name="WAITConsulting",
        publisher_prefix="wait",
        output_directory=output_directory or str(settings.power_platform_workspace / "employee-onboarding-source"),
        artifacts=review_artifacts,
    )
    delivery = build_consultant_delivery_plan(
        client_id=client_id,
        architecture=architecture,
        evaluation=evaluation,
        governance=governance,
        deployment_targets=["Teams", "Power Automate", "Power Apps", "Dataverse"],
        review_artifacts=review_artifacts,
        deployable_package=deployable_package,
    )

    return {
        "format": "wait-local-agent.employee-onboarding-demo",
        "format_version": 1,
        "client_id": client_id,
        "entity_id": entity_id,
        "request": _blueprint_request(persisted_blueprint),
        "mode": "local_fixture",
        "design_handoffs": design_handoffs,
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
                "delivery_bundle": delivery["delivery_bundle"],
                "delivery_bundle_digest": delivery["delivery_bundle_digest"],
                "delivery_bundle_status": delivery["delivery_bundle_status"],
                "deployable_source_package": deployable_package,
                "deployable_source_package_digest": deployable_package["package_digest"],
                "deployable_source_package_deployable": deployable_package["deployable"],
                "deployable_source_package_status": deployable_package["package_status"],
                "deployment_package_generated": False,
                "deployment_started": False,
            },
            "delivery": delivery,
        },
        "fixture_child_agents": [
            {
                "id": definition.id,
                "role": spec.role,
                "target_tools": _target_tools(persisted_blueprint, spec.role, spec.systems),
                "local_fixture_tools": list(definition.enabled_tools),
                "depends_on": list(definition.depends_on_agent_ids),
            }
            for definition, spec in zip(fixture_definitions, fixture_specs, strict=True)
        ],
        "boundaries": {
            "live_provider_execution": False,
            "artifact_generation": True,
            "artifact_generation_status": "review_only",
            "review_package_generated": True,
            "delivery_bundle_generated": delivery["delivery_bundle_generated"],
            "delivery_bundle_status": delivery["delivery_bundle_status"],
            "deployable_package_generated": deployable_package is not None,
            "deployable_package_deployable": deployable_package["deployable"],
            "deployable_package_status": deployable_package["package_status"],
            "deployable_package_digest": deployable_package["package_digest"],
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


def _create_fixture_definitions(
    agent_service: AgentService,
    client_id: str,
    blueprint: SolutionBlueprint,
) -> tuple[list[AgentDefinition], tuple[_FixtureChildSpec, ...]]:
    definitions: list[AgentDefinition] = []
    ids_by_key: dict[str, str] = {}
    specs = _derive_fixture_children(blueprint)
    for spec in specs:
        dependencies = [ids_by_key[item] for item in spec.dependencies]
        systems = ", ".join(spec.systems)
        definition = agent_service.create(
            name=f"Blueprint {spec.role} fixture",
            description=(
                f"Local fixture for the {spec.role} specialist covering {systems}; "
                "target provider actions remain review-only."
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
        ids_by_key[spec.key] = definition.id
    return definitions, specs


def _derive_fixture_children(blueprint: SolutionBlueprint) -> tuple[_FixtureChildSpec, ...]:
    """Build bounded child roles from the selected blueprint's declared services.

    Systems are grouped by capability so all declared systems remain represented
    without exceeding the supervisor's eight-child limit. If a blueprint omits
    systems, declared agent names are used as service labels before falling back
    to the solution name; valid blueprints always have at least one of these.
    """

    grouped: dict[str, list[str]] = {}
    source_systems = list(blueprint.systems)
    if not source_systems:
        source_systems = [agent.name for agent in blueprint.agents]
    if not source_systems:
        source_systems = [blueprint.solution_name]
    for system in source_systems:
        category = _system_category(system)
        grouped.setdefault(category, []).append(system)

    specs: list[_FixtureChildSpec] = []
    keys_by_category: dict[str, str] = {}
    for category, systems in grouped.items():
        key = f"{category}-{len(specs) + 1}"
        role = f"{category}-{_service_slug(systems)}"
        dependencies = _fixture_dependencies(category, specs, keys_by_category)
        specs.append(
            _FixtureChildSpec(
                key=key,
                role=role,
                category=category,
                systems=tuple(systems),
                dependencies=dependencies,
            )
        )
        keys_by_category[category] = key
    return tuple(specs)


def _system_category(system: str) -> str:
    normalized = system.casefold()
    for category, markers in _SYSTEM_CATEGORY_RULES:
        if any(marker in normalized for marker in markers):
            return category
    return "service"


def _service_slug(systems: list[str]) -> str:
    source = "-".join(_slugify(system) for system in systems)
    if len(source) <= 54:
        return source or "service"
    digest = hashlib.sha256("|".join(systems).encode("utf-8")).hexdigest()[:8]
    return f"{source[:45].rstrip('-')}-{digest}"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:32] or "service"


def _fixture_dependencies(
    category: str,
    specs: list[_FixtureChildSpec],
    keys_by_category: dict[str, str],
) -> tuple[str, ...]:
    if category == "licensing":
        return (keys_by_category["identity"],) if "identity" in keys_by_category else ()
    if category in {"endpoint", "rmm"}:
        for prerequisite in ("rmm", "endpoint", "licensing", "identity"):
            if prerequisite in keys_by_category:
                return (keys_by_category[prerequisite],)
        return ()
    if category == "communications" and "documentation" in keys_by_category:
        return (keys_by_category["documentation"],)
    if category == "service" and specs:
        return (specs[-1].key,)
    return ()


def _blueprint_request(blueprint: SolutionBlueprint) -> str:
    """Compose a bounded request from blueprint evidence.

    The canonical onboarding request is retained only for the impossible case
    where parsing yields no usable blueprint content, and is intentionally
    explicit here so a future schema change cannot silently restore hardcoding.
    """

    sections: list[str] = []
    if blueprint.solution_name.strip():
        sections.append(f"Solution: {blueprint.solution_name.strip()}")
    goal = _format_mapping(blueprint.business_goal)
    if goal:
        sections.append(f"Business goal: {goal}")
    if blueprint.systems:
        sections.append(f"Systems/services: {', '.join(blueprint.systems)}")
    if blueprint.users:
        sections.append(f"Users: {', '.join(blueprint.users)}")
    discovery = _format_mapping(blueprint.discovery)
    if discovery:
        sections.append(f"Discovery evidence: {discovery}")
    if not sections:
        return CANONICAL_EMPLOYEE_ONBOARDING_REQUEST
    request = "Review and design the selected blueprint. " + ". ".join(sections) + "."
    return request[:2_000]


def _format_mapping(values: Mapping[str, object]) -> str:
    return "; ".join(
        f"{key.replace('_', ' ')}={_format_value(values[key])}" for key in sorted(values) if _format_value(values[key])
    )


def _format_value(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, Mapping):
        return "; ".join(f"{key}={value[key]}" for key in sorted(value))
    return str(value)


def _target_tools(blueprint: SolutionBlueprint, role: str, systems: tuple[str, ...]) -> list[str]:
    category = role.split("-", 1)[0]
    tokens = {token for system in systems for token in re.findall(r"[a-z0-9]+", system.casefold()) if len(token) >= 3}
    return [
        tool
        for agent in blueprint.agents
        if category in agent.id
        or category in agent.name.casefold()
        or tokens.intersection(set(re.findall(r"[a-z0-9]+", f"{agent.id} {agent.name} {agent.purpose}".casefold())))
        for tool in agent.tools
    ]


def _build_review_artifacts(client_id: str) -> list[dict[str, Any]]:
    """Generate package-eligible local manifests for the Microsoft handoff."""

    return [
        build_power_apps_artifact(
            client_id=client_id,
            app_name="Employee onboarding workspace",
            entities=[
                {
                    "logical_name": "wait_employee",
                    "display_name": "Employee",
                    "primary_name_column": "wait_display_name",
                    "fields": [
                        {"name": "wait_display_name", "type": "string", "required": True},
                        {"name": "wait_start_date", "type": "date", "required": True},
                    ],
                }
            ],
            screens=[
                {"id": "employee_browse", "title": "Employees", "entity": "wait_employee", "mode": "browse"},
                {"id": "employee_edit", "title": "Edit employee", "entity": "wait_employee", "mode": "edit"},
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
    ]


def _build_design_handoffs(client_id: str) -> list[dict[str, Any]]:
    """Generate design deliverables that makers complete outside the packager."""

    return [
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
