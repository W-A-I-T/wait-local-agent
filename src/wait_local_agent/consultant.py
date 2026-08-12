from __future__ import annotations

import re
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import uuid4

from wait_local_agent.models import BlueprintAgent, BlueprintWorkflow, SolutionBlueprint
from wait_local_agent.reports.renderers import redact_text

BlueprintRisk = Literal["low", "medium", "high"]
ArchitectureComponentType = Literal[
    "agent",
    "child_agent",
    "workflow",
    "connector",
    "mcp_tool",
    "knowledge_source",
]

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
}
_KNOWN_SYSTEM_TERMS = (
    "sharepoint",
    "onedrive",
    "teams",
    "outlook",
    "exchange",
    "graph",
    "entra",
    "intune",
    "dataverse",
    "servicenow",
    "confluence",
    "hudu",
    "it glue",
    "notion",
    "halopsa",
    "connectwise",
    "syncro",
    "autotask",
    "ninjaone",
    "datto",
    "n-central",
    "kaseya",
    "screenconnect",
    "rmm",
    "psa",
)
_SUPERVISOR_TERMS = ("supervisor", "orchestrat", "coordinate")
MAX_ARCHITECTURE_COMPONENTS = MAX_BLUEPRINT_ITEMS * 16


class BlueprintValidationError(ValueError):
    """Raised when an offline solution blueprint is not structurally safe."""


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
    missing = sorted(_TOP_LEVEL_FIELDS - set(payload))
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
    )


def blueprint_payload(blueprint: SolutionBlueprint) -> dict[str, object]:
    return {
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


def blueprint_view(blueprint: SolutionBlueprint) -> dict[str, object]:
    return {
        "id": blueprint.id,
        "client_id": blueprint.client_id,
        "created_by": blueprint.created_by,
        "created_at": blueprint.created_at,
        "updated_at": blueprint.updated_at,
        **blueprint_payload(blueprint),
    }


def architect_solution_blueprint(
    blueprint: SolutionBlueprint,
    *,
    available_tool_ids: Collection[str] = (),
    available_workflow_ids: Collection[str] = (),
    now: str | None = None,
) -> dict[str, object]:
    """Project a stored business blueprint into a bounded implementation plan.

    This is intentionally deterministic and offline. It identifies which
    existing WAIT primitives can be reused, which requirements need a new
    workflow, connector, or MCP boundary, and which items still need review.
    It does not create agents, call providers, execute workflows, or deploy.
    """

    known_tools = {item.strip() for item in available_tool_ids if item.strip()}
    known_workflows = {item.strip() for item in available_workflow_ids if item.strip()}
    components: list[dict[str, object]] = []
    unresolved: list[str] = []
    supervisor_ids = {
        agent.id
        for agent in blueprint.agents
        if _contains_any((agent.id, agent.name, agent.purpose), _SUPERVISOR_TERMS)
    }

    for index, knowledge in enumerate(blueprint.knowledge):
        components.append(
            _architecture_component(
                component_id=f"knowledge-source-{index}",
                component_type="knowledge_source",
                name=knowledge,
                source=f"blueprint.knowledge[{index}]",
                implementation="Configure a tenant-scoped grounding source and verify permissions.",
                status="planned",
                risk=blueprint.risk,
            )
        )

    for index, system in enumerate(blueprint.systems):
        known = _contains_any((system,), _KNOWN_SYSTEM_TERMS)
        status = "candidate_existing_connector" if known else "connector_selection_required"
        if not known:
            unresolved.append(f"Select and validate a connector for system: {system}")
        components.append(
            _architecture_component(
                component_id=f"connector-{index}",
                component_type="connector",
                name=system,
                source=f"blueprint.systems[{index}]",
                implementation=(
                    "Map to an existing WAIT connector/provider and verify operations."
                    if known
                    else "Define an adapter contract, authentication, tenant mapping, and tests."
                ),
                status=status,
                risk=blueprint.risk,
            )
        )

    for agent in blueprint.agents:
        is_child = bool(supervisor_ids) and agent.id not in supervisor_ids
        component_type: ArchitectureComponentType = "child_agent" if is_child else "agent"
        implementation = (
            "Register as a bounded child-agent capability under a supervisor."
            if is_child
            else "Define a bounded WAIT agent using the existing AgentService runtime."
        )
        unresolved.append(
            f"Bind agent {agent.id} to a supported entity, trigger, and execution contract before deployment"
        )
        components.append(
            {
                **_architecture_component(
                    component_id=f"agent-{agent.id}",
                    component_type=component_type,
                    name=agent.name,
                    source=f"blueprint.agents.{agent.id}",
                    implementation=implementation,
                    status="design_only",
                    risk=blueprint.risk,
                ),
                "purpose": redact_text(agent.purpose),
                "tools": list(agent.tools),
                "knowledge": list(agent.knowledge),
                "supervisor": next(
                    (f"agent-{candidate}" for candidate in sorted(supervisor_ids) if candidate != agent.id),
                    None,
                ),
            }
        )

    tool_component_ids: dict[str, str] = {}
    for agent in blueprint.agents:
        for tool in agent.tools:
            if tool in tool_component_ids:
                continue
            component_id = f"tool-{len(tool_component_ids)}"
            tool_component_ids[tool] = component_id
            explicit_mcp = tool.casefold().startswith(("mcp.", "mcp/", "mcp:"))
            known_local = tool in known_tools
            if explicit_mcp:
                tool_component_type: ArchitectureComponentType = "mcp_tool"
                status = "explicit_mcp_boundary"
                implementation = "Validate the remote MCP contract and keep it outside local authority by default."
            elif known_local:
                tool_component_type = "connector"
                status = "existing_wait_tool"
                implementation = "Reuse the existing WAIT tool catalog and its role/approval controls."
            else:
                tool_component_type = "mcp_tool"
                status = "unresolved_tool_boundary"
                implementation = "Confirm whether this is a connector, local tool, or governed MCP capability."
                unresolved.append(f"Classify and register tool boundary: {tool}")
            components.append(
                {
                    **_architecture_component(
                        component_id=component_id,
                        component_type=tool_component_type,
                        name=tool,
                        source=f"agent tool reference: {tool}",
                        implementation=implementation,
                        status=status,
                        risk=blueprint.risk,
                    ),
                    "tool_id": tool,
                    "used_by": [agent.id for agent in blueprint.agents if tool in agent.tools],
                }
            )

    for workflow in blueprint.workflows:
        existing = workflow.id in known_workflows
        if not existing:
            unresolved.append(f"Implement and validate workflow template: {workflow.id}")
        components.append(
            {
                **_architecture_component(
                    component_id=f"workflow-{workflow.id}",
                    component_type="workflow",
                    name=workflow.name,
                    source=f"blueprint.workflows.{workflow.id}",
                    implementation=(
                        "Reuse and configure the existing deterministic workflow template."
                        if existing
                        else "Create a bounded deterministic workflow with preview and approval checkpoints."
                    ),
                    status="existing_workflow_template" if existing else "new_workflow_required",
                    risk=blueprint.risk,
                ),
                "trigger": workflow.trigger,
                "steps": list(workflow.steps),
                "template_id": workflow.id if existing else None,
            }
        )

    if len(components) > MAX_ARCHITECTURE_COMPONENTS:
        raise BlueprintValidationError(
            f"architecture plan may contain at most {MAX_ARCHITECTURE_COMPONENTS} components"
        )
    unique_unresolved = list(dict.fromkeys(unresolved))
    return {
        "blueprint_id": blueprint.id,
        "client_id": blueprint.client_id,
        "solution": {"name": redact_text(blueprint.solution_name)},
        "generated_at": now or datetime.now(UTC).isoformat(),
        "mode": "deterministic_offline_architecture",
        "components": components,
        "approval_boundaries": [
            {
                "action": redact_text(action),
                "approver": redact_text(approver),
                "required_before_side_effect": True,
            }
            for action, approver in sorted(blueprint.approvals.items())
        ],
        "deployment_targets": [redact_text(item) for item in blueprint.deployment],
        "risk": blueprint.risk,
        "unresolved": [redact_text(item) for item in unique_unresolved[:MAX_BLUEPRINT_ITEMS]],
        "readiness": "needs_review" if unique_unresolved else "review_ready",
        "execution": {
            "external_calls_made": False,
            "writes_performed": False,
            "deployment_performed": False,
            "production_deployment_requires_approval": True,
        },
    }


def _architecture_component(
    *,
    component_id: str,
    component_type: ArchitectureComponentType,
    name: str,
    source: str,
    implementation: str,
    status: str,
    risk: BlueprintRisk,
) -> dict[str, object]:
    return {
        "id": component_id,
        "type": component_type,
        "name": redact_text(name),
        "source": redact_text(source),
        "implementation": redact_text(implementation),
        "status": status,
        "risk": risk,
        "requires_approval": risk in {"medium", "high"},
    }


def _contains_any(values: Collection[str], terms: Collection[str]) -> bool:
    lowered = tuple(value.casefold() for value in values)
    return any(term in value for value in lowered for term in terms)


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
            raise BlueprintValidationError(
                f"business_goal.{identifier} must be text, integer, or boolean"
            )
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
