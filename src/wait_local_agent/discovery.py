"""Deterministic consultant discovery intake and ROI/risk analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, cast

from wait_local_agent.environment import EnvironmentDiscoveryError, discover_environment
from wait_local_agent.models import ConnectorStatus

MAX_DISCOVERY_ANSWERS = 28
MAX_DISCOVERY_LIST_ITEMS = 16
MAX_DISCOVERY_TEXT = 500
MAX_MONTHLY_RUNS = 100_000
MAX_MINUTES_SAVED = 480
MAX_AFFECTED_USERS = 1_000_000
MAX_HOURLY_VALUE = 100_000

_QUESTION_DEFS: tuple[dict[str, object], ...] = (
    {"id": "solution_name", "prompt": "What should this solution be called?", "kind": "text", "required": False},
    {"id": "business_goal", "prompt": "What business problem should improve?", "kind": "text", "required": True},
    {"id": "users", "prompt": "Who uses or owns the process?", "kind": "list", "required": True},
    {"id": "knowledge", "prompt": "What sources may the solution read?", "kind": "list", "required": True},
    {"id": "systems", "prompt": "Which systems are involved?", "kind": "list", "required": True},
    {"id": "reads", "prompt": "What may the solution read?", "kind": "list", "required": True},
    {"id": "changes", "prompt": "What may the solution change?", "kind": "list", "required": True},
    {"id": "approvals", "prompt": "Which changes require human approval?", "kind": "list", "required": True},
    {
        "id": "failure_handling",
        "prompt": "What should happen when an operation fails?",
        "kind": "text",
        "required": True,
    },
    {"id": "licenses", "prompt": "Which Microsoft licenses are available?", "kind": "list", "required": False},
    {"id": "data_location", "prompt": "Where is the data located?", "kind": "list", "required": True},
    {"id": "data_leaves_tenant", "prompt": "May information leave the tenant?", "kind": "boolean", "required": True},
    {"id": "current_process", "prompt": "What happens today, step by step?", "kind": "text", "required": False},
    {"id": "owners", "prompt": "Who owns the process and its outcome?", "kind": "list", "required": False},
    {
        "id": "approvers",
        "prompt": "Who can approve the sensitive or state-changing steps?",
        "kind": "list",
        "required": False,
    },
    {
        "id": "sensitive_operations",
        "prompt": "Which operations are sensitive or high impact?",
        "kind": "list",
        "required": False,
    },
    {"id": "compliance", "prompt": "Which compliance or policy requirements apply?", "kind": "list", "required": False},
    {"id": "data_residency", "prompt": "Where must data remain?", "kind": "list", "required": False},
    {
        "id": "existing_apis",
        "prompt": "Which existing APIs or connector interfaces are available?",
        "kind": "list",
        "required": False,
    },
    {"id": "existing_automation", "prompt": "What automation already exists?", "kind": "list", "required": False},
    {"id": "channels", "prompt": "Which user or operational channels are needed?", "kind": "list", "required": False},
    {
        "id": "expected_volume",
        "prompt": "What volume or frequency should the solution handle?",
        "kind": "text",
        "required": False,
    },
    {"id": "business_value", "prompt": "What business value should this create?", "kind": "text", "required": False},
    {"id": "success_metrics", "prompt": "How will success be measured?", "kind": "list", "required": False},
    {
        "id": "rollback_expectations",
        "prompt": "What must be reversible, and how should rollback work?",
        "kind": "text",
        "required": False,
    },
)
_QUESTION_IDS = {cast(str, item["id"]) for item in _QUESTION_DEFS}
_SECRET_TOKENS = ("key", "token", "secret", "password", "credential", "bearer")


class DiscoveryValidationError(ValueError):
    """Raised when discovery evidence is malformed or unsafe."""


def build_solution_discovery(
    *,
    client_id: str,
    answers: Mapping[str, object],
    environment: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    tenant = _text(client_id, "client_id", 128)
    if len(set(answers) - {"impact"}) > MAX_DISCOVERY_ANSWERS:
        raise DiscoveryValidationError(f"answers may contain at most {MAX_DISCOVERY_ANSWERS} fields")
    unknown = sorted(set(answers) - _QUESTION_IDS - {"impact"})
    if unknown:
        raise DiscoveryValidationError(f"unsupported discovery fields: {', '.join(unknown)}")
    normalized = {key: _answer(key, value) for key, value in answers.items() if key != "impact"}
    missing = [
        cast(str, question["id"])
        for question in _QUESTION_DEFS
        if question["required"]
        and (question["id"] not in normalized or not _answer_present(normalized[cast(str, question["id"])]))
    ]
    risk = _risk_review(normalized, missing)
    environment_view = dict(environment) if environment is not None else _not_run_environment(tenant)
    candidate = _blueprint_candidate(normalized)
    candidate["environment"] = list(cast(list[dict[str, object]], environment_view.get("systems", [])))
    questions = [
        dict(
            question,
            answered=question["id"] in normalized and _answer_present(normalized[cast(str, question["id"])]),
        )
        for question in _QUESTION_DEFS
    ]
    next_question = next(
        (question for question in questions if question["required"] and not question["answered"]),
        None,
    )
    if next_question is None:
        next_question = next((question for question in questions if not question["answered"]), None)
    unanswered = [cast(str, question["id"]) for question in questions if not question["answered"]]
    return {
        "format": "wait-local-agent.solution-discovery",
        "format_version": 1,
        "client_id": tenant,
        "questions": questions,
        "answered": normalized,
        "missing_required": missing,
        "unanswered": unanswered,
        "next_question": next_question,
        "assistant_message": (
            cast(str, next_question["prompt"])
            if next_question is not None
            else "Discovery evidence is complete enough for architecture review."
        ),
        "status": "complete" if next_question is None else "active",
        "readiness": "ready_for_architecture" if not missing else "needs_discovery",
        "risk_review": risk,
        "roi_analysis": _roi_analysis(answers.get("impact")),
        "blueprint_candidate": candidate,
        "environment": environment_view,
        "inference_started": False,
        "execution_started": False,
        "deployment_started": False,
    }


def discover_solution_environment(
    *,
    client_id: str,
    systems: Sequence[object],
    connector_statuses: Iterable[ConnectorStatus],
    configured_client_id: str | None = None,
) -> dict[str, Any]:
    """Build environment evidence for a discovery request without probing."""

    try:
        return discover_environment(
            client_id=client_id,
            requested_systems=systems,
            connector_statuses=connector_statuses,
            configured_client_id=configured_client_id,
        )
    except EnvironmentDiscoveryError as exc:
        raise DiscoveryValidationError(str(exc)) from exc


def _not_run_environment(client_id: str) -> dict[str, object]:
    return {
        "format": "wait-local-agent.environment-discovery",
        "format_version": 1,
        "client_id": client_id,
        "source": "not_requested",
        "probe_performed": False,
        "systems": [],
        "unresolved": [],
        "limitations": [{"system": "environment", "reason": "environment discovery was not requested"}],
        "readiness": "needs_environment_verification",
        "inference_started": False,
        "execution_started": False,
        "deployment_started": False,
    }


def _answer(field: str, value: object) -> str | bool | list[str]:
    if field == "data_leaves_tenant":
        if not isinstance(value, bool):
            raise DiscoveryValidationError("data_leaves_tenant must be boolean evidence")
        return value
    if field in {
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
    }:
        return _list(value, field)
    return _text(value, field, MAX_DISCOVERY_TEXT)


def _blueprint_candidate(answers: Mapping[str, object]) -> dict[str, object]:
    return {
        "discovery": dict(answers),
        "solution": {"name": answers.get("solution_name", "")},
        "business_goal": {"statement": answers.get("business_goal", "")},
        "users": list(cast(list[str], answers.get("users", []))),
        "knowledge": list(cast(list[str], answers.get("knowledge", []))),
        "systems": list(cast(list[str], answers.get("systems", []))),
        "agents": [],
        "workflows": [],
        "approvals": {item: "human_review_required" for item in cast(list[str], answers.get("approvals", []))},
        "deployment": [],
        "risk": "needs_review",
    }


def _answer_present(value: object) -> bool:
    return not isinstance(value, list) or bool(value)


def _risk_review(answers: Mapping[str, object], missing: list[str]) -> dict[str, object]:
    factors: list[str] = []
    changes = cast(list[str], answers.get("changes", []))
    if changes:
        factors.append("state_change_scope_present")
    if answers.get("data_leaves_tenant") is True:
        factors.append("cross_tenant_data_transfer")
    if "approvals" in missing:
        factors.append("approval_boundary_not_defined")
    if "failure_handling" in missing:
        factors.append("failure_path_not_defined")
    level = "high" if answers.get("data_leaves_tenant") is True else "medium" if changes else "low"
    if missing:
        level = "needs_review"
    return {"level": level, "factors": factors, "evidence_only": True}


def _roi_analysis(value: object) -> dict[str, object]:
    if value is None:
        return {"status": "needs_estimates", "formula": "monthly_runs * minutes_saved_per_run / 60"}
    if not isinstance(value, Mapping):
        raise DiscoveryValidationError("impact must be an object")
    allowed = {"monthly_runs", "minutes_saved_per_run", "affected_users", "hourly_value"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise DiscoveryValidationError(f"unsupported impact fields: {', '.join(unknown)}")
    runs = _bounded_int(value.get("monthly_runs"), "monthly_runs", MAX_MONTHLY_RUNS, minimum=1)
    minutes = _bounded_int(value.get("minutes_saved_per_run"), "minutes_saved_per_run", MAX_MINUTES_SAVED)
    users = _bounded_int(value.get("affected_users"), "affected_users", MAX_AFFECTED_USERS, minimum=1)
    hours = Decimal(runs * minutes) / Decimal(60)
    result: dict[str, object] = {
        "status": "estimated",
        "monthly_runs": runs,
        "affected_users": users,
        "estimated_monthly_hours_saved": float(hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        "formula": "monthly_runs * minutes_saved_per_run / 60",
        "evidence_only": True,
    }
    if "hourly_value" in value:
        hourly_value = _bounded_number(value["hourly_value"], "hourly_value", MAX_HOURLY_VALUE)
        result["hourly_value"] = hourly_value
        result["estimated_monthly_value"] = round(float(hours) * hourly_value, 2)
    return result


def _list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_DISCOVERY_LIST_ITEMS:
        raise DiscoveryValidationError(f"{field} must contain 0-{MAX_DISCOVERY_LIST_ITEMS} items")
    result = [_text(item, f"{field} item", 160) for item in value]
    if len(set(result)) != len(result):
        raise DiscoveryValidationError(f"{field} must not contain duplicates")
    return result


def _text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise DiscoveryValidationError(f"{field} must be non-empty text of at most {maximum} characters")
    normalized = value.strip()
    lowered = normalized.casefold()
    if any(f"{token}=" in lowered for token in _SECRET_TOKENS):
        raise DiscoveryValidationError("discovery field may not contain secret material")
    if any(ord(character) < 32 for character in normalized):
        raise DiscoveryValidationError(f"{field} contains unsupported control characters")
    return normalized


def _bounded_int(value: object, field: str, maximum: int, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise DiscoveryValidationError(f"{field} must be an integer between {minimum} and {maximum}")
    return value


def _bounded_number(value: object, field: str, maximum: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > maximum:
        raise DiscoveryValidationError(f"{field} must be a number between 0 and {maximum}")
    return float(value)
