from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from wait_local_agent.models import (
    BlueprintAgent,
    BlueprintWorkflow,
    SolutionBlueprint,
    WorkflowTemplate,
)

BlueprintRisk = Literal["low", "medium", "high"]

MAX_BLUEPRINT_ITEMS = 32
MAX_BLUEPRINT_TEXT = 240
MAX_BLUEPRINT_GOAL_VALUE = 500
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_FORBIDDEN_KEY_TOKENS = frozenset(
    {
        "key",
        "token",
        "secret",
        "password",
        "passwd",
        "credential",
        "authorization",
        "bearer",
        "private",
    }
)
_TOP_LEVEL_FIELDS = {
    "solution",
    "business_goal",
    "users",
    "knowledge",
    "systems",
    "agents",
    "workflows",
    "approvals",
    "deployment",
    "risk",
    "instructions",
    "intents",
    "skills",
    "model",
    "orchestration",
    "environment",
    "discovery",
}
_REQUIRED_TOP_LEVEL_FIELDS = _TOP_LEVEL_FIELDS - {
    "instructions",
    "intents",
    "skills",
    "model",
    "orchestration",
    "environment",
    "discovery",
}
_ORCHESTRATION_MODES = {"single_agent", "supervisor", "event_driven", "hybrid"}
_VERIFIED_ENVIRONMENT_STATUSES = {"reachable", "authenticated", "authorized"}
_LOCAL_DEPLOYMENT_TARGETS = {"local", "api", "cli", "agents", "mcp"}
_DECISION_EVIDENCE_FIELDS = (
    "business_goal",
    "reads",
    "changes",
    "approvals",
    "licenses",
    "data_location",
    "data_residency",
    "data_leaves_tenant",
    "failure_handling",
    "compliance",
    "existing_apis",
    "channels",
    "success_metrics",
    "rollback_expectations",
)


class BlueprintValidationError(ValueError):
    """Raised when an offline solution blueprint is not structurally safe."""


def architect_solution_blueprint(
    blueprint: SolutionBlueprint,
    *,
    available_tool_ids: Iterable[str],
    workflow_templates: Iterable[WorkflowTemplate],
) -> dict[str, Any]:
    """Resolve a blueprint against existing local catalogs without side effects.

    This is deliberately an inspectable architecture view, not a deployment or
    execution operation. Anything that cannot be resolved from the local tool
    and workflow catalogs remains an explicit review item.
    """

    tool_ids = set(_ordered_unique(item.strip() for item in available_tool_ids if item.strip()))
    templates = {template.id: template for template in workflow_templates}
    open_items: list[dict[str, str]] = []
    components: list[dict[str, object]] = []

    for agent in blueprint.agents:
        requested = list(_ordered_unique(agent.tools))
        resolved = [tool_id for tool_id in requested if tool_id in tool_ids]
        unresolved = [tool_id for tool_id in requested if tool_id not in tool_ids]
        for tool_id in unresolved:
            open_items.append(
                {
                    "kind": "tool",
                    "component_id": agent.id,
                    "detail": f"tool '{tool_id}' is not in the local smart-action catalog",
                }
            )
        components.append(
            {
                "id": agent.id,
                "kind": "agent",
                "name": agent.name,
                "purpose": agent.purpose,
                "implementation": "existing_agent_runtime",
                "requested_tool_ids": requested,
                "resolved_tool_ids": resolved,
                "unresolved_tool_ids": unresolved,
                "knowledge_references": list(agent.knowledge),
                "status": "ready" if not unresolved else "needs_review",
            }
        )

    for workflow in blueprint.workflows:
        template = templates.get(workflow.id)
        if template is None:
            open_items.append(
                {
                    "kind": "workflow_template",
                    "component_id": workflow.id,
                    "detail": "workflow id has no exact match in the local template catalog",
                }
            )
        template_view = (
            {
                "id": template.id,
                "name": template.name,
                "trigger": template.trigger,
                "approval_required": template.approval_required,
                "risk_level": template.risk_level,
                "tool_id": template.tool_id,
            }
            if template is not None
            else None
        )
        components.append(
            {
                "id": workflow.id,
                "kind": "workflow",
                "name": workflow.name,
                "trigger": workflow.trigger,
                "steps": list(workflow.steps),
                "implementation": "existing_workflow_template" if template else "design_only",
                "template": template_view,
                "status": "ready" if template else "needs_review",
            }
        )

    for name in blueprint.knowledge:
        open_items.append(
            {
                "kind": "knowledge_source",
                "component_id": name,
                "detail": "source binding is not inferred from a display name",
            }
        )
        components.append(
            {
                "id": name,
                "kind": "knowledge_source",
                "name": name,
                "implementation": "local_knowledge_or_external_source",
                "status": "needs_review",
            }
        )

    for name in blueprint.systems:
        environment = _matching_environment(name, blueprint.environment)
        verified = bool(environment and environment.get("status") in _VERIFIED_ENVIRONMENT_STATUSES)
        if not verified:
            open_items.append(
                {
                    "kind": "system_connector",
                    "component_id": name,
                    "detail": (
                        str(environment.get("limitation"))
                        if environment and environment.get("limitation")
                        else "connector selection and configuration are not inferred"
                    ),
                }
            )
        components.append(
            {
                "id": name,
                "kind": "system_connector",
                "name": name,
                "implementation": "existing_connector_boundary" if verified else "existing_connector_or_mcp_boundary",
                "connector_id": environment.get("connector_id") if environment else None,
                "observed_status": environment.get("status") if environment else None,
                "status": "ready" if verified else "needs_review",
            }
        )

    for environment in blueprint.environment:
        status = str(environment["status"])
        connector_id = str(environment.get("connector_id") or "")
        if status not in {"authorized", "authenticated", "reachable"}:
            open_items.append(
                {
                    "kind": "environment",
                    "component_id": str(environment["id"]),
                    "detail": str(
                        environment.get("limitation")
                        or f"environment status is {status}; provider verification is incomplete"
                    ),
                }
            )
        components.append(
            {
                "id": environment["id"],
                "kind": "environment",
                "name": environment["name"],
                "connector_id": connector_id or None,
                "observed_status": status,
                "evidence": list(cast(list[str], environment.get("evidence", []))),
                "implementation": "existing_connector_boundary" if connector_id else "customer_declared_system",
                "status": "ready" if status in {"authorized", "authenticated", "reachable"} else "needs_review",
            }
        )

    supported_surfaces = {"api", "cli", "agents", "mcp", "local"}
    for target in blueprint.deployment:
        normalized_target = target.casefold()
        supported = normalized_target in supported_surfaces
        if not supported:
            open_items.append(
                {
                    "kind": "deployment",
                    "component_id": target,
                    "detail": "deployment target is recorded but not provisioned by this local runtime",
                }
            )
        components.append(
            {
                "id": target,
                "kind": "deployment",
                "name": target,
                "implementation": "existing_local_surface" if supported else "requested_only",
                "status": "ready" if supported else "needs_review",
            }
        )

    decisions = _architecture_decisions(blueprint, components, templates)
    unresolved_decisions = [item for item in decisions if item["status"] != "ready"]
    discovery_evidence = _decision_discovery_evidence(blueprint)
    return {
        "blueprint_id": blueprint.id,
        "client_id": blueprint.client_id,
        "solution": {"name": blueprint.solution_name},
        "risk": blueprint.risk,
        "approval_policy": dict(blueprint.approvals),
        "components": components,
        "decisions": decisions,
        "decision_engine": {
            "format": "wait-local-agent.architecture-decisions",
            "format_version": 1,
            "authority": "deterministic_local_catalogs_and_explicit_blueprint_evidence",
            "inference_started": False,
            "execution_started": False,
            "deployment_started": False,
            "decision_count": len(decisions),
            "unresolved_decision_count": len(unresolved_decisions),
            "evidence_summary": discovery_evidence,
        },
        "supervisor": _supervisor_plan(blueprint),
        "open_items": open_items,
        "readiness": "ready" if not open_items and not unresolved_decisions else "needs_review",
        "execution_started": False,
        "deployment_started": False,
    }


def _architecture_decisions(
    blueprint: SolutionBlueprint,
    components: list[dict[str, object]],
    templates: Mapping[str, WorkflowTemplate],
) -> list[dict[str, object]]:
    return [_decision_for_component(blueprint, component, templates) for component in components]


def _decision_for_component(
    blueprint: SolutionBlueprint,
    component: Mapping[str, object],
    templates: Mapping[str, WorkflowTemplate],
) -> dict[str, object]:
    kind = str(component.get("kind", "unknown"))
    component_id = str(component.get("id", "unknown"))
    name = str(component.get("name", component_id))
    status = str(
        component.get("observed_status", component.get("status", "needs_review"))
        if kind == "environment"
        else component.get("status", "needs_review")
    )
    common: dict[str, object] = {
        "id": f"decision-{_safe_decision_id(kind)}-{_safe_decision_id(component_id)}",
        "capability": name,
        "component_id": component_id,
        "chosen_target": "unsupported",
        "why": "No deterministic local target rule matched this component.",
        "alternatives_considered": ["human_process"],
        "systems_involved": list(blueprint.systems),
        "dependencies": [],
        "required_permissions": _permission_requirements(blueprint, component),
        "licenses": _license_requirements(blueprint),
        "read_write_behavior": _read_write_requirements(blueprint),
        "approval_requirements": _approval_requirements(blueprint),
        "risk": blueprint.risk,
        "data_movement": _data_movement(blueprint),
        "execution_boundary": "unknown",
        "estimated_complexity": "unknown",
        "reversibility": _reversibility(blueprint),
        "testing_requirements": [
            "functional behavior",
            "tenant isolation",
            "approval and forbidden-tool checks",
        ],
        "deployment_requirements": [
            "review generated artifacts",
            "obtain explicit human approval before deployment",
        ],
        "evidence": [],
        "evidence_quality": "explicit_blueprint_and_local_catalog_evidence",
        "open_questions": [],
        "status": "needs_review",
    }

    if kind == "agent":
        unresolved = cast(list[object], component.get("unresolved_tool_ids", []))
        common.update(
            {
                "chosen_target": "wait_agent",
                "why": "The existing WAIT AgentService is the local runtime boundary for the declared agent.",
                "alternatives_considered": [
                    "microsoft_copilot_studio",
                    "custom_service",
                    "human_process",
                ],
                "dependencies": list(cast(list[str], component.get("requested_tool_ids", [])))
                + list(cast(list[str], component.get("knowledge_references", []))),
                "execution_boundary": "local",
                "estimated_complexity": "medium" if component.get("requested_tool_ids") else "low",
                "reversibility": (
                    _reversibility(blueprint)
                    if _reversibility(blueprint) != "unknown"
                    else "reversible_design_only"
                ),
                "evidence": ["existing_agent_runtime", "blueprint_agent_declaration"],
                "status": "needs_review" if unresolved else "ready",
            }
        )
        if unresolved:
            common["open_questions"] = ["resolve every requested tool against the local smart-action catalog"]
        return common

    if kind == "workflow":
        template = templates.get(component_id)
        template_approval = template.approval_required if template else False
        dependencies: list[str] = []
        if template:
            dependencies.append(template.id)
            if template.tool_id:
                dependencies.append(template.tool_id)
        common.update(
            {
                "chosen_target": "wait_workflow",
                "why": (
                    "The matching local workflow template supplies a bounded runtime path."
                    if template
                    else "WAIT can retain the workflow design, but no exact local template is available."
                ),
                "alternatives_considered": ["power_automate", "human_process"],
                "dependencies": dependencies,
                "read_write_behavior": {
                    "read": "template_defined" if template else "not_declared",
                    "write": "approval_gated" if template_approval else "not_declared",
                    "evidence": "workflow template metadata" if template else "no matching workflow template",
                },
                "approval_requirements": _approval_requirements(blueprint, template_approval),
                "execution_boundary": "local",
                "estimated_complexity": "medium",
                "reversibility": "reversible_design_only",
                "evidence": ["existing_workflow_template"] if template else ["blueprint_workflow_declaration"],
                "status": "ready" if template else "needs_review",
            }
        )
        if not template:
            common["open_questions"] = ["select or implement a bounded workflow template"]
        return common

    if kind == "knowledge_source":
        common.update(
            {
                "chosen_target": "wait_agent",
                "why": "Knowledge is consumed through the existing tenant-scoped WAIT knowledge boundary.",
                "alternatives_considered": ["mcp", "direct_api", "human_process"],
                "dependencies": [name],
                "execution_boundary": "local",
                "estimated_complexity": "medium",
                "reversibility": "reversible_design_only",
                "evidence": ["blueprint_knowledge_declaration"],
                "open_questions": ["bind the named source to an authorized tenant-scoped provider or local corpus"],
            }
        )
        return common

    if kind == "system_connector":
        if status == "ready":
            chosen_target = _connector_target(component)
            supported = chosen_target != "unsupported"
            common.update(
                {
                    "chosen_target": chosen_target,
                    "why": "Environment evidence resolved the declared system to an existing connector boundary.",
                    "alternatives_considered": ["mcp", "direct_api", "human_process"],
                    "dependencies": [str(component.get("connector_id"))],
                    "data_movement": "tenant_scoped_external",
                    "execution_boundary": "hybrid",
                    "estimated_complexity": "medium",
                    "reversibility": "reversible_with_provider_rollback",
                    "evidence": ["verified_environment_status", "existing_connector_boundary"],
                    "status": "ready" if supported else "needs_review",
                }
            )
            if not supported:
                common["open_questions"] = ["map the verified system to a supported connector target"]
        else:
            common.update(
                {
                    "why": "The declared system has no verified connector binding in the available evidence.",
                    "alternatives_considered": ["mcp", "direct_api", "human_process"],
                    "open_questions": ["identify and authorize the connector boundary before implementation"],
                }
            )
        return common

    if kind == "environment":
        chosen_target = _connector_target(component)
        verified = status in _VERIFIED_ENVIRONMENT_STATUSES
        supported = chosen_target != "unsupported"
        common.update(
            {
                "chosen_target": chosen_target,
                "why": (
                    "The existing connector boundary matches the environment kind."
                    if component.get("connector_id")
                    else "The customer declaration has no existing connector boundary."
                ),
                "alternatives_considered": ["wait_agent", "mcp", "direct_api", "human_process"],
                "dependencies": [component.get("connector_id")] if component.get("connector_id") else [],
                "read_write_behavior": {
                    "read": "provider_status_required",
                    "write": "approval_required_before_any_mutation",
                    "evidence": "environment discovery does not probe providers",
                },
                "approval_requirements": ["human approval before any write action"],
                "data_movement": "tenant_scoped_external" if component.get("connector_id") else "unknown",
                "execution_boundary": "hybrid" if component.get("connector_id") else "unknown",
                "estimated_complexity": "medium",
                "reversibility": "reversible_with_provider_rollback" if verified else "unknown",
                "evidence": list(cast(list[str], component.get("evidence", []))),
                "status": "ready" if verified and supported else "needs_review",
            }
        )
        if not verified or not supported:
            common["open_questions"] = [
                (
                    "obtain provider reachability, authentication, and authorization evidence"
                    if not verified
                    else "map the verified system to a supported connector target"
                )
            ]
        return common

    if kind == "deployment":
        target = _deployment_target(name)
        supported = target != "unsupported"
        common.update(
            {
                "chosen_target": target,
                "why": (
                    "The deployment target maps to an existing WAIT surface."
                    if supported
                    else "The requested deployment target is not provisioned by the local runtime."
                ),
                "alternatives_considered": ["wait_agent", "human_process"],
                "execution_boundary": "local" if name.casefold() in _LOCAL_DEPLOYMENT_TARGETS else "cloud",
                "estimated_complexity": "medium" if supported else "unknown",
                "reversibility": "reversible_with_rollback" if supported else "unknown",
                "evidence": ["supported_local_surface"] if supported else [],
                "status": "ready" if supported else "needs_review",
            }
        )
        if not supported:
            common["open_questions"] = ["confirm supported packaging and deployment path"]
        return common

    return common


def _unknown_requirement(evidence: str) -> list[dict[str, object]]:
    return [{"name": "provider_requirement", "status": "unknown", "evidence": [evidence]}]


def _decision_discovery_evidence(blueprint: SolutionBlueprint) -> dict[str, object]:
    """Summarize only explicit discovery facts used by architecture decisions.

    Discovery answers are customer evidence, not provider verification. Keeping
    the source and missing fields in the architecture response prevents a
    decision from looking more certain merely because a blueprint exists.
    """

    explicit_fields = [field for field in _DECISION_EVIDENCE_FIELDS if field in blueprint.discovery]
    missing_fields = [field for field in _DECISION_EVIDENCE_FIELDS if field not in blueprint.discovery]
    return {
        "source": "blueprint.discovery",
        "explicit_fields": explicit_fields,
        "missing_fields": missing_fields,
        "evidence_only": True,
        "provider_verification_source": "environment evidence is evaluated separately",
    }


def _discovery_list(blueprint: SolutionBlueprint, field: str) -> list[str]:
    value = blueprint.discovery.get(field)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _permission_requirements(
    blueprint: SolutionBlueprint,
    component: Mapping[str, object],
) -> list[dict[str, object]]:
    requirements: list[dict[str, object]] = [
        {
            "name": "tenant_scope",
            "status": "verified",
            "evidence": ["blueprint_client_scope"],
        }
    ]
    approvals = _discovery_list(blueprint, "approvals")
    if approvals:
        requirements.append(
            {
                "name": "human_approval",
                "status": "declared",
                "evidence": ["discovery.approvals"],
                "actions": approvals,
            }
        )
    if component.get("kind") in {"system_connector", "environment"}:
        status = str(component.get("observed_status", ""))
        if status == "authorized":
            requirements.append(
                {
                    "name": "provider_authorization",
                    "status": "verified",
                    "evidence": list(cast(list[str], component.get("evidence", []))),
                }
            )
        else:
            requirements.append(
                {
                    "name": "provider_authorization",
                    "status": "unknown",
                    "evidence": ["provider authorization is not verified for this component"],
                }
            )
    else:
        requirements.append(
            {
                "name": "provider_permissions",
                "status": "unknown",
                "evidence": ["provider permissions are not declared by the local catalog"],
            }
        )
    return requirements


def _license_requirements(blueprint: SolutionBlueprint) -> list[dict[str, object]]:
    licenses = _discovery_list(blueprint, "licenses")
    if not licenses:
        return _unknown_requirement("licensing evidence is not present in the blueprint")
    return [
        {
            "name": license_name,
            "status": "declared",
            "evidence": ["discovery.licenses"],
            "verification": "not_verified",
        }
        for license_name in licenses
    ]


def _read_write_requirements(blueprint: SolutionBlueprint) -> dict[str, object]:
    reads = _discovery_list(blueprint, "reads")
    writes = _discovery_list(blueprint, "changes")
    return {
        "read": {
            "status": "declared" if reads else "unknown",
            "items": reads,
            "source": "discovery.reads" if reads else "missing discovery.reads",
        },
        "write": {
            "status": "declared" if writes else "unknown",
            "items": writes,
            "source": "discovery.changes" if writes else "missing discovery.changes",
        },
        "evidence": "customer discovery declaration; action-level provider behavior remains unverified",
    }


def _data_movement(blueprint: SolutionBlueprint) -> str:
    value = blueprint.discovery.get("data_leaves_tenant")
    if value is True:
        return "cross_boundary_declared"
    if value is False:
        return "within_declared_tenant_and_local_boundary"
    return "unknown"


def _reversibility(blueprint: SolutionBlueprint) -> str:
    expectation = blueprint.discovery.get("rollback_expectations")
    if isinstance(expectation, str) and expectation.strip():
        return "operator_declared"
    return "unknown"


def _approval_requirements(blueprint: SolutionBlueprint, template_approval: bool = False) -> list[str]:
    requirements = [f"{action}: approval by {owner}" for action, owner in sorted(blueprint.approvals.items())]
    if template_approval and "workflow_template" not in requirements:
        requirements.append("workflow_template: approval required by local template")
    return requirements


def _connector_target(component: Mapping[str, object]) -> str:
    kind = str(component.get("kind", "")).casefold()
    connector_kind = str(component.get("connector_id", "")).casefold()
    value = f"{kind} {connector_kind} {str(component.get('name', '')).casefold()}"
    if "m365" in value or "entra" in value or "microsoft 365" in value:
        return "microsoft_graph"
    if "psa" in value or any(item in value for item in ("halopsa", "connectwise", "autotask", "servicenow", "syncro")):
        return "psa"
    if "rmm" in value or any(
        item in value for item in ("ninjaone", "n-central", "n-sight", "datto", "kaseya", "screenconnect")
    ):
        return "rmm"
    if any(item in value for item in ("documentation", "hudu", "it glue", "confluence", "notion", "sharepoint")):
        return "mcp"
    return "unsupported"


def _deployment_target(name: str) -> str:
    normalized = name.casefold()
    if normalized in _LOCAL_DEPLOYMENT_TARGETS:
        return "wait_agent"
    if "copilot" in normalized or normalized == "teams":
        return "microsoft_copilot_studio"
    if "power automate" in normalized:
        return "power_automate"
    if "power app" in normalized:
        return "power_app"
    if "dataverse" in normalized:
        return "dataverse"
    return "unsupported"


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().replace("/", " ").split())


def _matching_environment(
    system_name: str,
    environments: Iterable[dict[str, object]],
) -> dict[str, object] | None:
    requested = _normalize_name(system_name)
    for environment in environments:
        candidates = [environment.get("name"), environment.get("connector_id")]
        for candidate in candidates:
            if not isinstance(candidate, str):
                continue
            normalized = _normalize_name(candidate)
            if requested == normalized or requested in normalized or normalized in requested:
                return environment
    return None


def _safe_decision_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9-]+", "-", _normalize_name(value).replace(" ", "-")).strip("-")
    return normalized[:64] or "unknown"


def _supervisor_plan(blueprint: SolutionBlueprint) -> dict[str, object]:
    """Describe bounded child-agent delegation without creating agent records."""

    children = [
        {
            "id": agent.id,
            "kind": "child_agent" if len(blueprint.agents) > 1 else "agent",
            "purpose": agent.purpose,
            "tool_ids": list(agent.tools),
            "knowledge_references": list(agent.knowledge),
            "context_policy": "tenant_scoped_structured_result_only",
        }
        for agent in blueprint.agents
    ]
    return {
        "mode": "supervisor" if len(children) > 1 else "single_agent",
        "children": children,
        "context_policy": "pass only bounded structured results within the blueprint tenant",
        "execution_started": False,
    }


def parse_solution_blueprint(
    payload: dict[str, object],
    *,
    client_id: str,
    created_by: str,
    blueprint_id: str | None = None,
    now: str | None = None,
) -> SolutionBlueprint:
    if not isinstance(payload, dict):
        raise BlueprintValidationError("blueprint must be a JSON object")
    unknown = sorted(set(payload) - _TOP_LEVEL_FIELDS)
    if unknown:
        raise BlueprintValidationError(f"unsupported blueprint fields: {', '.join(unknown)}")
    missing = sorted(_REQUIRED_TOP_LEVEL_FIELDS - set(payload))
    if missing:
        raise BlueprintValidationError(f"missing blueprint fields: {', '.join(missing)}")

    client = _text(client_id, "client_id", max_length=128)
    actor = _text(created_by, "created_by", max_length=128)
    identifier = _identifier(blueprint_id or f"bp_{uuid4().hex}", "id", allow_prefix=True)
    timestamp = now or datetime.now(UTC).isoformat()

    solution = _object(payload["solution"], "solution")
    _reject_unknown(solution, {"name"}, "solution")
    solution_name = _text(solution.get("name"), "solution.name")
    business_goal = _business_goal(payload["business_goal"])
    users = _text_list(payload["users"], "users")
    knowledge = _text_list(payload["knowledge"], "knowledge")
    systems = _text_list(payload["systems"], "systems")
    agents = _agents(payload["agents"])
    workflows = _workflows(payload["workflows"])
    approvals = _approvals(payload["approvals"])
    deployment = _text_list(payload["deployment"], "deployment")
    risk = _risk(payload["risk"])
    instructions = _optional_text(payload.get("instructions"), "instructions", max_length=4000)
    intents = _text_list(payload.get("intents", []), "intents")
    skills = _text_list(payload.get("skills", []), "skills")
    model = _optional_text(payload.get("model"), "model")
    orchestration = payload.get("orchestration", "")
    if orchestration is None:
        orchestration = ""
    if not isinstance(orchestration, str) or (orchestration and orchestration not in _ORCHESTRATION_MODES):
        raise BlueprintValidationError(f"orchestration must be one of: {', '.join(sorted(_ORCHESTRATION_MODES))}")

    return SolutionBlueprint(
        id=identifier,
        client_id=client,
        created_by=actor,
        created_at=timestamp,
        updated_at=timestamp,
        solution_name=solution_name,
        business_goal=business_goal,
        users=users,
        knowledge=knowledge,
        systems=systems,
        agents=agents,
        workflows=workflows,
        approvals=approvals,
        deployment=deployment,
        risk=risk,
        instructions=instructions,
        intents=intents,
        skills=skills,
        model=model,
        orchestration=cast(str, orchestration),
        environment=_environment(payload.get("environment", []), client_id=client),
        discovery=_discovery(payload.get("discovery", {})),
    )


def promote_discovery_candidate(
    candidate: Mapping[str, object],
    *,
    client_id: str,
    solution_name: str,
    risk: str,
    created_by: str,
) -> SolutionBlueprint:
    """Persist a blueprint-shaped discovery candidate after explicit review.

    Discovery labels are evidence, not identifiers. Approval labels such as
    ``Assign license`` are converted to bounded blueprint identifiers while
    the original label remains in the stored discovery evidence. The caller
    must provide the solution name and risk; neither is inferred here.
    """

    payload = dict(candidate)
    payload["solution"] = {"name": solution_name}
    payload["risk"] = risk
    raw_approvals = payload.get("approvals")
    if not isinstance(raw_approvals, Mapping):
        raise BlueprintValidationError("discovery candidate approvals must be an object")
    approvals: dict[str, object] = {}
    for raw_action, approver in raw_approvals.items():
        if not isinstance(raw_action, str):
            raise BlueprintValidationError("approval action must be text")
        raw_action_text = _text(raw_action, "approval action")
        if _has_forbidden_key(raw_action_text):
            raise BlueprintValidationError("approval action contains secret material")
        normalized_action = re.sub(r"[^a-z0-9_.:-]+", "_", raw_action_text.casefold()).strip("_")
        if not normalized_action or not re.match(r"^[a-z0-9]", normalized_action):
            raise BlueprintValidationError("approval action must contain a usable identifier")
        if normalized_action in approvals:
            raise BlueprintValidationError(f"approval action identifiers collide: {normalized_action}")
        approvals[normalized_action] = approver
    payload["approvals"] = approvals
    raw_environment = payload.get("environment")
    if isinstance(raw_environment, list):
        environment: list[object] = []
        seen_environment_ids: set[str] = set()
        for index, raw_system in enumerate(raw_environment, start=1):
            if not isinstance(raw_system, Mapping):
                environment.append(raw_system)
                continue
            system = dict(raw_system)
            raw_id = system.get("id")
            if isinstance(raw_id, str) and raw_id.strip():
                identifier = raw_id.strip()
                if identifier in seen_environment_ids:
                    name = system.get("name")
                    base_identifier = _safe_decision_id(str(name)) if name is not None else f"system-{index}"
                    identifier = base_identifier
                    suffix = 2
                    while identifier in seen_environment_ids:
                        identifier = f"{base_identifier}-{suffix}"[:64]
                        suffix += 1
                    system["id"] = identifier
                seen_environment_ids.add(identifier)
            environment.append(system)
        payload["environment"] = environment
    return parse_solution_blueprint(
        payload,
        client_id=client_id,
        created_by=created_by,
    )


def blueprint_payload(blueprint: SolutionBlueprint) -> dict[str, Any]:
    payload: dict[str, object] = {
        "solution": {"name": blueprint.solution_name},
        "business_goal": dict(blueprint.business_goal),
        "users": list(blueprint.users),
        "knowledge": list(blueprint.knowledge),
        "systems": list(blueprint.systems),
        "agents": [
            {
                "id": agent.id,
                "name": agent.name,
                "purpose": agent.purpose,
                "tools": list(agent.tools),
                "knowledge": list(agent.knowledge),
            }
            for agent in blueprint.agents
        ],
        "workflows": [
            {
                "id": workflow.id,
                "name": workflow.name,
                "trigger": workflow.trigger,
                "steps": list(workflow.steps),
            }
            for workflow in blueprint.workflows
        ],
        "approvals": dict(blueprint.approvals),
        "deployment": list(blueprint.deployment),
        "risk": blueprint.risk,
    }
    if blueprint.instructions:
        payload["instructions"] = blueprint.instructions
    if blueprint.intents:
        payload["intents"] = list(blueprint.intents)
    if blueprint.skills:
        payload["skills"] = list(blueprint.skills)
    if blueprint.model:
        payload["model"] = blueprint.model
    if blueprint.orchestration:
        payload["orchestration"] = blueprint.orchestration
    if blueprint.environment:
        payload["environment"] = [dict(item) for item in blueprint.environment]
    if blueprint.discovery:
        payload["discovery"] = dict(blueprint.discovery)
    return payload


def blueprint_view(blueprint: SolutionBlueprint) -> dict[str, Any]:
    return {
        "id": blueprint.id,
        "client_id": blueprint.client_id,
        "created_by": blueprint.created_by,
        "created_at": blueprint.created_at,
        "updated_at": blueprint.updated_at,
        **blueprint_payload(blueprint),
    }


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _object(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BlueprintValidationError(f"{field} must be an object")
    return cast(dict[str, object], value)


def _reject_unknown(value: dict[str, object], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise BlueprintValidationError(f"unsupported {field} fields: {', '.join(unknown)}")


def _text(value: object, field: str, *, max_length: int = MAX_BLUEPRINT_TEXT) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BlueprintValidationError(f"{field} must be non-empty text")
    normalized = value.strip()
    if len(normalized) > max_length:
        raise BlueprintValidationError(f"{field} exceeds {max_length} characters")
    if any(ord(character) < 32 and character not in "\t\n" for character in normalized):
        raise BlueprintValidationError(f"{field} contains unsupported control characters")
    return normalized


def _optional_text(value: object, field: str, *, max_length: int = MAX_BLUEPRINT_TEXT) -> str:
    if value is None or value == "":
        return ""
    return _text(value, field, max_length=max_length)


def _identifier(value: object, field: str, *, allow_prefix: bool = False) -> str:
    normalized = _text(value, field, max_length=64)
    if _has_forbidden_key(normalized):
        raise BlueprintValidationError(f"{field} cannot contain secret material")
    if not _IDENTIFIER.fullmatch(normalized) or (not allow_prefix and normalized.startswith("bp_")):
        raise BlueprintValidationError(f"{field} must be a lowercase identifier")
    return normalized


def _text_list(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BlueprintValidationError(f"{field} must be an array")
    if len(value) > MAX_BLUEPRINT_ITEMS:
        raise BlueprintValidationError(f"{field} may contain at most {MAX_BLUEPRINT_ITEMS} items")
    return tuple(_text(item, f"{field}[{index}]") for index, item in enumerate(value))


def _environment(value: object, *, client_id: str) -> tuple[dict[str, object], ...]:
    if not isinstance(value, list):
        raise BlueprintValidationError("environment must be an array")
    if len(value) > MAX_BLUEPRINT_ITEMS:
        raise BlueprintValidationError(f"environment may contain at most {MAX_BLUEPRINT_ITEMS} items")
    allowed = {
        "id",
        "name",
        "kind",
        "connector_id",
        "status",
        "evidence",
        "limitation",
        "tenant_scope",
        "provider_status",
        "http_probing_enabled",
        "write_actions_enabled",
        "probe",
    }
    statuses = {
        "configured",
        "detected",
        "reachable",
        "authenticated",
        "authorized",
        "permission-limited",
        "unavailable",
        "not_configured",
        "unknown",
    }
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw in enumerate(value):
        item = _object(raw, f"environment[{index}]")
        _reject_unknown(item, allowed, f"environment[{index}]")
        identifier = _identifier(item.get("id"), f"environment[{index}].id", allow_prefix=True)
        if identifier in seen:
            raise BlueprintValidationError(f"environment contains duplicate id: {identifier}")
        seen.add(identifier)
        status = _text(item.get("status"), f"environment[{index}].status", max_length=32)
        if status not in statuses:
            raise BlueprintValidationError(f"environment[{index}].status is unsupported")
        evidence = _text_list(item.get("evidence", []), f"environment[{index}].evidence")
        normalized: dict[str, object] = {
            "id": identifier,
            "name": _text(item.get("name"), f"environment[{index}].name"),
            "kind": _text(item.get("kind"), f"environment[{index}].kind", max_length=64),
            "connector_id": _optional_text(
                item.get("connector_id"),
                f"environment[{index}].connector_id",
                max_length=64,
            ),
            "status": status,
            "evidence": list(evidence),
            "limitation": _optional_text(item.get("limitation"), f"environment[{index}].limitation", max_length=500),
        }
        for boolean_field in ("http_probing_enabled", "write_actions_enabled"):
            if boolean_field in item:
                boolean_value = item[boolean_field]
                if not isinstance(boolean_value, bool):
                    raise BlueprintValidationError(f"environment[{index}].{boolean_field} must be boolean")
                normalized[boolean_field] = boolean_value
        for text_field in ("tenant_scope", "provider_status"):
            if text_field in item:
                text_value = _text(item[text_field], f"environment[{index}].{text_field}", max_length=128)
                if text_field == "tenant_scope" and text_value != client_id:
                    raise BlueprintValidationError(f"environment[{index}].tenant_scope is outside the blueprint tenant")
                normalized[text_field] = text_value
        if "probe" in item:
            probe = _object(item["probe"], f"environment[{index}].probe")
            _reject_unknown(
                probe,
                {"status", "layer", "message"},
                f"environment[{index}].probe",
            )
            probe_status = _text(
                probe.get("status"),
                f"environment[{index}].probe.status",
                max_length=16,
            )
            if probe_status not in {"passed", "failed", "not_run"}:
                raise BlueprintValidationError(f"environment[{index}].probe.status is unsupported")
            probe_layer = _text(
                probe.get("layer"),
                f"environment[{index}].probe.layer",
                max_length=32,
            )
            probe_message = _optional_text(
                probe.get("message"),
                f"environment[{index}].probe.message",
                max_length=240,
            )
            normalized["probe"] = {
                "status": probe_status,
                "layer": probe_layer,
                "message": probe_message or "",
            }
        result.append(normalized)
    return tuple(result)


def _discovery(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BlueprintValidationError("discovery must be an object")
    allowed = {
        "solution_name",
        "business_goal",
        "users",
        "knowledge",
        "systems",
        "reads",
        "changes",
        "approvals",
        "failure_handling",
        "licenses",
        "data_location",
        "data_leaves_tenant",
        "current_process",
        "owners",
        "approvers",
        "sensitive_operations",
        "compliance",
        "data_residency",
        "existing_apis",
        "existing_automation",
        "channels",
        "expected_volume",
        "business_value",
        "success_metrics",
        "rollback_expectations",
    }
    _reject_unknown(value, allowed, "discovery")
    list_fields = {
        "users",
        "knowledge",
        "systems",
        "reads",
        "changes",
        "approvals",
        "licenses",
        "data_location",
        "owners",
        "approvers",
        "sensitive_operations",
        "compliance",
        "data_residency",
        "existing_apis",
        "existing_automation",
        "channels",
        "success_metrics",
    }
    text_fields = {
        "solution_name",
        "business_goal",
        "failure_handling",
        "current_process",
        "expected_volume",
        "business_value",
        "rollback_expectations",
    }
    result: dict[str, object] = {}
    for key, raw in value.items():
        if key in list_fields:
            normalized_list = list(_text_list(raw, f"discovery.{key}"))
            if any(_has_forbidden_key(item) for item in normalized_list):
                raise BlueprintValidationError("discovery evidence cannot contain secret material")
            result[key] = normalized_list
        elif key in text_fields:
            normalized_text = _text(raw, f"discovery.{key}")
            if _has_forbidden_key(normalized_text):
                raise BlueprintValidationError("discovery evidence cannot contain secret material")
            result[key] = normalized_text
        elif key == "data_leaves_tenant":
            if not isinstance(raw, bool):
                raise BlueprintValidationError("discovery.data_leaves_tenant must be boolean")
            result[key] = raw
    return result


def _business_goal(value: object) -> dict[str, str | bool | int]:
    goal = _object(value, "business_goal")
    if len(goal) > MAX_BLUEPRINT_ITEMS:
        raise BlueprintValidationError(f"business_goal may contain at most {MAX_BLUEPRINT_ITEMS} items")
    result: dict[str, str | bool | int] = {}
    for key, item in goal.items():
        identifier = _identifier(key, "business_goal key")
        if isinstance(item, bool):
            result[identifier] = item
        elif isinstance(item, int) and not isinstance(item, bool):
            result[identifier] = item
        elif isinstance(item, str):
            result[identifier] = _text(item, f"business_goal.{identifier}", max_length=MAX_BLUEPRINT_GOAL_VALUE)
        else:
            raise BlueprintValidationError(f"business_goal.{identifier} must be text, integer, or boolean")
    return result


def _agents(value: object) -> tuple[BlueprintAgent, ...]:
    if not isinstance(value, list):
        raise BlueprintValidationError("agents must be an array")
    if len(value) > MAX_BLUEPRINT_ITEMS:
        raise BlueprintValidationError(f"agents may contain at most {MAX_BLUEPRINT_ITEMS} items")
    result: list[BlueprintAgent] = []
    for index, raw in enumerate(value):
        item = _object(raw, f"agents[{index}]")
        _reject_unknown(item, {"id", "name", "purpose", "tools", "knowledge"}, f"agents[{index}]")
        identifier = _identifier(item.get("id"), f"agents[{index}].id")
        result.append(
            BlueprintAgent(
                id=identifier,
                name=_text(item.get("name"), f"agents[{index}].name"),
                purpose=_text(item.get("purpose"), f"agents[{index}].purpose"),
                tools=_text_list(item.get("tools", []), f"agents[{index}].tools"),
                knowledge=_text_list(item.get("knowledge", []), f"agents[{index}].knowledge"),
            )
        )
    _unique_ids([agent.id for agent in result], "agents")
    return tuple(result)


def _workflows(value: object) -> tuple[BlueprintWorkflow, ...]:
    if not isinstance(value, list):
        raise BlueprintValidationError("workflows must be an array")
    if len(value) > MAX_BLUEPRINT_ITEMS:
        raise BlueprintValidationError(f"workflows may contain at most {MAX_BLUEPRINT_ITEMS} items")
    result: list[BlueprintWorkflow] = []
    for index, raw in enumerate(value):
        item = _object(raw, f"workflows[{index}]")
        _reject_unknown(item, {"id", "name", "trigger", "steps"}, f"workflows[{index}]")
        result.append(
            BlueprintWorkflow(
                id=_identifier(item.get("id"), f"workflows[{index}].id"),
                name=_text(item.get("name"), f"workflows[{index}].name"),
                trigger=_text(item.get("trigger"), f"workflows[{index}].trigger"),
                steps=_text_list(item.get("steps"), f"workflows[{index}].steps"),
            )
        )
    _unique_ids([workflow.id for workflow in result], "workflows")
    return tuple(result)


def _approvals(value: object) -> dict[str, str]:
    approvals = _object(value, "approvals")
    if len(approvals) > MAX_BLUEPRINT_ITEMS:
        raise BlueprintValidationError(f"approvals may contain at most {MAX_BLUEPRINT_ITEMS} items")
    result: dict[str, str] = {}
    for action, approver in approvals.items():
        result[_identifier(action, "approval action")] = _text(approver, f"approvals.{action}")
    return result


def _risk(value: object) -> BlueprintRisk:
    if not isinstance(value, str) or value not in {"low", "medium", "high"}:
        raise BlueprintValidationError("risk must be one of: low, medium, high")
    return cast(BlueprintRisk, value)


def _unique_ids(values: list[str], field: str) -> None:
    if len(values) != len(set(values)):
        raise BlueprintValidationError(f"{field} ids must be unique")


def _has_forbidden_key(value: str) -> bool:
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    tokens = tuple(re.sub(r"[^A-Za-z0-9]+", " ", normalized).lower().split())
    return bool(_FORBIDDEN_KEY_TOKENS.intersection(tokens)) or "".join(tokens) in {
        "apikey",
        "privatekey",
    }
