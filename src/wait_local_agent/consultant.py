from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Literal, cast
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
}


class BlueprintValidationError(ValueError):
    """Raised when an offline solution blueprint is not structurally safe."""


def architect_solution_blueprint(
    blueprint: SolutionBlueprint,
    *,
    available_tool_ids: Iterable[str],
    workflow_templates: Iterable[WorkflowTemplate],
) -> dict[str, object]:
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
        open_items.append(
            {
                "kind": "system_connector",
                "component_id": name,
                "detail": "connector selection and configuration are not inferred",
            }
        )
        components.append(
            {
                "id": name,
                "kind": "system_connector",
                "name": name,
                "implementation": "existing_connector_or_mcp_boundary",
                "status": "needs_review",
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

    return {
        "blueprint_id": blueprint.id,
        "client_id": blueprint.client_id,
        "solution": {"name": blueprint.solution_name},
        "risk": blueprint.risk,
        "approval_policy": dict(blueprint.approvals),
        "components": components,
        "supervisor": _supervisor_plan(blueprint),
        "open_items": open_items,
        "readiness": "ready" if not open_items else "needs_review",
        "execution_started": False,
        "deployment_started": False,
    }


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
