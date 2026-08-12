"""Review-only Power Automate workflow plan generation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast

MAX_FLOW_STEPS = 32
MAX_FLOW_TEXT = 240
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}
_KINDS = {"action", "condition", "approval"}
_SECRET_TOKENS = ("key", "token", "secret", "password", "credential")


class PowerAutomatePlanError(ValueError):
    """Raised when a Power Automate plan is malformed or unsafe."""


def build_power_automate_flow_plan(
    *,
    client_id: str,
    workflow_id: str,
    workflow_name: str,
    trigger: str,
    steps: list[dict[str, object]],
) -> dict[str, object]:
    tenant = _text(client_id, "client_id", 128)
    flow_id = _identifier(workflow_id, "workflow_id")
    name = _text(workflow_name, "workflow_name", MAX_FLOW_TEXT)
    trigger_name = _text(trigger, "trigger", MAX_FLOW_TEXT)
    step_views = _steps(steps)
    return {
        "format": "wait-local-agent.power-automate-flow-plan",
        "format_version": 1,
        "client_id": tenant,
        "workflow_id": flow_id,
        "workflow_name": name,
        "power_automate": {
            "trigger": {"type": "manual_review_trigger", "name": trigger_name},
            "actions": step_views,
        },
        "requires_approval": any(bool(step["approval_required"]) for step in step_views),
        "credentials_included": False,
        "execution_started": False,
        "deployment_started": False,
        "export_status": "review_only",
    }


def _steps(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_FLOW_STEPS:
        raise PowerAutomatePlanError(f"steps must contain 1-{MAX_FLOW_STEPS} objects")
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, Mapping):
            raise PowerAutomatePlanError("steps must contain objects")
        step = dict(raw)
        unknown = sorted(set(step) - {"id", "name", "kind", "tool_id", "method", "approval_required"})
        if unknown:
            raise PowerAutomatePlanError(f"unsupported step fields: {', '.join(unknown)}")
        step_id = _identifier(step.get("id"), "step.id")
        if step_id in seen:
            raise PowerAutomatePlanError(f"duplicate step id: {step_id}")
        seen.add(step_id)
        kind = step.get("kind", "action")
        if kind not in _KINDS:
            raise PowerAutomatePlanError(f"unsupported step kind: {kind}")
        method = step.get("method", "GET")
        if method not in _METHODS:
            raise PowerAutomatePlanError(f"unsupported step method: {method}")
        approval_required = step.get("approval_required", kind == "approval")
        if not isinstance(approval_required, bool):
            raise PowerAutomatePlanError("step approval_required must be boolean")
        if method != "GET" and not approval_required:
            raise PowerAutomatePlanError(f"write step requires approval: {step_id}")
        if kind == "approval" and not approval_required:
            raise PowerAutomatePlanError(f"approval step must require approval: {step_id}")
        tool_id = step.get("tool_id")
        if tool_id is not None:
            tool_id = _identifier(tool_id, "step.tool_id")
            if any(token in cast(str, tool_id) for token in _SECRET_TOKENS):
                raise PowerAutomatePlanError("tool identifiers may not contain secret material")
        result.append(
            {
                "id": step_id,
                "name": _text(step.get("name"), "step.name", MAX_FLOW_TEXT),
                "kind": kind,
                "type": "Approval" if kind == "approval" else "Condition" if kind == "condition" else "Action",
                "tool_id": tool_id,
                "method": method,
                "approval_required": approval_required,
            }
        )
    return result


def _identifier(value: object, field: str) -> str:
    normalized = _text(value, field, 64).casefold()
    if not _IDENTIFIER.fullmatch(normalized):
        raise PowerAutomatePlanError(f"{field} must be a lowercase identifier")
    return normalized


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise PowerAutomatePlanError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    if any(ord(character) < 32 for character in normalized):
        raise PowerAutomatePlanError(f"{field} contains unsupported control characters")
    return normalized
