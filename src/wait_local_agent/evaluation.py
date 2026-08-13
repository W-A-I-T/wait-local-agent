"""Bounded consultant evaluation contracts and controlled execution."""

from __future__ import annotations

import re
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol, cast

from wait_local_agent.reports.renderers import redact_text

if TYPE_CHECKING:
    from wait_local_agent.agents import AgentService
    from wait_local_agent.models import AgentDefinition
    from wait_local_agent.rbac import Role

_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")

MAX_EVALUATION_CASES = 32
MAX_EXPECTED_TOOLS = 8
MAX_LATENCY_MS = 120_000


class EvaluationValidationError(ValueError):
    """Raised when an evaluation test set, observation, or runner is unsafe."""


class EvaluationExecutor(Protocol):
    """A controlled adapter around an existing local runtime execution."""

    def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
        """Execute one already-validated case and return captured evidence."""


def evaluate_tool_contract(
    test_set: list[dict[str, object]],
    observations: Mapping[str, object],
) -> dict[str, Any]:
    if not isinstance(test_set, list) or not 1 <= len(test_set) <= MAX_EVALUATION_CASES:
        raise EvaluationValidationError(f"test_set must contain 1-{MAX_EVALUATION_CASES} cases")
    cases: list[dict[str, object]] = []
    for raw_case in test_set:
        case = _case(raw_case)
        case_id = cast(str, case["id"])
        observed = _observation(observations.get(case_id), case)
        expected_tools = set(cast(list[str], case["expected_tool_ids"]))
        observed_tools = set(cast(list[str], observed["tool_ids"]))
        expected_approvals = set(cast(list[str], case["expected_approval_tool_ids"]))
        observed_approvals = set(cast(list[str], observed["approval_tool_ids"]))
        checks: dict[str, bool] = {
            "functional": expected_tools <= observed_tools,
            "tool_selection": expected_tools <= observed_tools
            and not set(cast(list[str], case["forbidden_tool_ids"])) & observed_tools,
            "approval_safety": expected_approvals <= observed_approvals,
            "tenant_isolation": cast(bool, observed["tenant_isolated"]),
            "injection_safety": cast(bool, observed["prompt_injection_blocked"]),
        }
        required_citations = set(cast(list[str], case["required_citations"]))
        if required_citations:
            checks["grounding"] = required_citations <= set(cast(list[str], observed["citations"]))
        max_latency_ms = case["max_latency_ms"]
        if max_latency_ms is not None:
            checks["latency"] = cast(float, observed["latency_ms"]) <= cast(float, max_latency_ms)
        if cast(bool, case["failure_expected"]):
            checks["failure_handling"] = cast(bool, observed["failure_handled"])
        if cast(bool, case["regression_expected"]):
            checks["regression"] = cast(bool, observed["regression_passed"])
        execution_evidence = {
            key: observed[key] for key in ("actions", "execution_status", "run_id", "error_detail") if key in observed
        }
        case_result: dict[str, object] = {
            "id": case_id,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if execution_evidence:
            case_result["execution"] = execution_evidence
        cases.append(case_result)

    dimension_order = (
        "functional",
        "tool_selection",
        "approval_safety",
        "tenant_isolation",
        "injection_safety",
        "grounding",
        "latency",
        "failure_handling",
        "regression",
    )
    dimensions = {
        dimension: round(
            100
            * sum(
                bool(cast(dict[str, bool], case["checks"])[dimension])
                for case in cases
                if dimension in cast(dict[str, bool], case["checks"])
            )
            / sum(dimension in cast(dict[str, bool], case["checks"]) for case in cases),
            2,
        )
        for dimension in dimension_order
        if any(dimension in cast(dict[str, bool], case["checks"]) for case in cases)
    }
    return {
        "case_count": len(cases),
        "dimensions": dimensions,
        "production_readiness": "pass" if all(value == 100 for value in dimensions.values()) else "needs_review",
        "execution_started": False,
        "execution_mode": "observation",
        "cases": cases,
    }


def execute_tool_contract(
    test_set: list[dict[str, object]],
    executor: EvaluationExecutor,
) -> dict[str, Any]:
    """Run each case once through a bounded existing-runtime adapter.

    The adapter owns execution; this function only validates the contract,
    captures its returned evidence, and applies the same deterministic checks as
    observation mode. Executor failures become explicit failed evidence rather
    than passing or disappearing as empty results.
    """

    normalized_cases = [_case(raw_case) for raw_case in _validate_test_set(test_set)]
    observations: dict[str, object] = {}
    execution_errors: list[dict[str, str]] = []
    for case in normalized_cases:
        case_id = cast(str, case["id"])
        started = time.monotonic()
        try:
            observed = executor.execute(case)
            if not isinstance(observed, Mapping):
                raise EvaluationValidationError("controlled executor must return an object")
            observations[case_id] = dict(observed)
        except EvaluationValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert provider failure into explicit failed evidence.
            safe_error = _bounded_error(exc)
            execution_errors.append({"case_id": case_id, "error": safe_error})
            observations[case_id] = _failed_observation(case, safe_error, time.monotonic() - started)

    result = evaluate_tool_contract(
        [cast(dict[str, object], case) for case in normalized_cases],
        observations,
    )
    result["execution_started"] = True
    result["execution_mode"] = "controlled"
    result["executed_case_count"] = len(normalized_cases)
    result["execution_errors"] = execution_errors
    return result


class AgentServiceEvaluationExecutor:
    """Adapt one tenant-scoped AgentService definition to the evaluator.

    This deliberately delegates to ``AgentService.run``. It does not interpret
    model output, grant permissions, approve writes, or create another engine.
    Callers must provide a local fixture-mode definition and an explicit tenant
    scope before constructing it.
    """

    def __init__(
        self,
        agent_service: AgentService,
        definition: AgentDefinition,
        *,
        entity_id: str,
        actor: str,
        actor_role: Role,
        input_payload: Mapping[str, object] | None = None,
        client_id: str,
    ) -> None:
        if not client_id.strip() or definition.client_id != client_id:
            raise EvaluationValidationError("evaluation executor requires a matching tenant-scoped agent")
        if not entity_id.strip() or not actor.strip():
            raise EvaluationValidationError("evaluation executor requires entity and actor identities")
        self.agent_service = agent_service
        self.definition = definition
        self.entity_id = entity_id
        self.actor = actor
        self.actor_role = actor_role
        self.input_payload = dict(input_payload or {})
        self.client_id = client_id

    def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
        started = time.monotonic()
        result = self.agent_service.run(
            self.definition,
            entity_id=self.entity_id,
            actor=self.actor,
            input_payload=self.input_payload,
            actor_role=self.actor_role,
        )
        tool_ids: list[str] = []
        approval_tool_ids: list[str] = []
        citations: list[str] = []
        actions: list[dict[str, object]] = []
        for raw_step in result.steps:
            tool_id = raw_step.get("tool_id")
            if isinstance(tool_id, str):
                tool_ids.append(tool_id)
                if raw_step.get("approval_id") is not None or raw_step.get("status") == "pending_approval":
                    approval_tool_ids.append(tool_id)
            raw_evidence = raw_step.get("evidence")
            if isinstance(raw_evidence, list):
                citations.extend(item for item in raw_evidence if isinstance(item, str))
            actions.append(
                {
                    "tool_id": tool_id,
                    "status": raw_step.get("status", "failed"),
                    "evidence": raw_evidence if isinstance(raw_evidence, list) else [],
                    "error": redact_text(str(raw_step.get("error_detail", "")))[:240],
                }
            )
        # Deterministic local execution does not pass untrusted ticket text to
        # a model. If model inference is enabled, the runtime must supply an
        # explicit injection result rather than this adapter claiming safety.
        prompt_injection_blocked = not self.agent_service.settings.allow_llm_inference
        failure_expected = bool(case.get("failure_expected", False))
        return {
            "tool_ids": tool_ids,
            "approval_tool_ids": approval_tool_ids,
            "tenant_isolated": self.definition.client_id == self.client_id,
            "prompt_injection_blocked": prompt_injection_blocked,
            "citations": sorted(set(citations)),
            "latency_ms": min(MAX_LATENCY_MS, (time.monotonic() - started) * 1000),
            "failure_handled": result.status in {"failed", "rejected", "cancelled"} if failure_expected else True,
            "actions": actions,
            "execution_status": result.status,
            "run_id": result.run_id,
            "error_detail": redact_text(result.error_detail)[:240],
        }


def _validate_test_set(test_set: object) -> list[object]:
    if not isinstance(test_set, list) or not 1 <= len(test_set) <= MAX_EVALUATION_CASES:
        raise EvaluationValidationError(f"test_set must contain 1-{MAX_EVALUATION_CASES} cases")
    return test_set


def _case(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError("evaluation case must be an object")
    case = dict(value)
    allowed = {
        "id",
        "expected_tool_ids",
        "forbidden_tool_ids",
        "expected_approval_tool_ids",
        "required_citations",
        "max_latency_ms",
        "failure_expected",
        "regression_expected",
    }
    unknown = sorted(set(case) - allowed)
    if unknown:
        raise EvaluationValidationError(f"unsupported evaluation case fields: {', '.join(unknown)}")
    identifier = case.get("id")
    if not isinstance(identifier, str):
        raise EvaluationValidationError("evaluation case id must be text")
    if not _IDENTIFIER.fullmatch(identifier):
        raise EvaluationValidationError("evaluation case id must be a bounded identifier")
    return {
        "id": identifier,
        "expected_tool_ids": _string_list(case.get("expected_tool_ids", []), "expected_tool_ids"),
        "forbidden_tool_ids": _string_list(case.get("forbidden_tool_ids", []), "forbidden_tool_ids"),
        "expected_approval_tool_ids": _string_list(
            case.get("expected_approval_tool_ids", []), "expected_approval_tool_ids"
        ),
        "required_citations": _string_list(case.get("required_citations", []), "required_citations"),
        "max_latency_ms": _latency_limit(case.get("max_latency_ms")),
        "failure_expected": _required_bool(case.get("failure_expected", False), "failure_expected"),
        "regression_expected": _required_bool(case.get("regression_expected", False), "regression_expected"),
    }


def _observation(value: object, case: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError("each test case requires an observation")
    observation = dict(value)
    result: dict[str, object] = {
        "tool_ids": _string_list(observation.get("tool_ids"), "observation.tool_ids"),
        "approval_tool_ids": _string_list(observation.get("approval_tool_ids"), "observation.approval_tool_ids"),
        "tenant_isolated": _required_bool(observation.get("tenant_isolated"), "tenant_isolated"),
        "prompt_injection_blocked": _required_bool(
            observation.get("prompt_injection_blocked"), "prompt_injection_blocked"
        ),
    }
    if cast(list[str], case["required_citations"]):
        result["citations"] = _string_list(observation.get("citations"), "citations")
    if case["max_latency_ms"] is not None:
        result["latency_ms"] = _latency_value(observation.get("latency_ms"))
    if cast(bool, case["failure_expected"]):
        result["failure_handled"] = _required_bool(observation.get("failure_handled"), "failure_handled")
    if cast(bool, case["regression_expected"]):
        result["regression_passed"] = _required_bool(observation.get("regression_passed"), "regression_passed")
    for field in ("actions", "execution_status", "run_id", "error_detail"):
        if field in observation:
            result[field] = observation[field]
    return result


def _failed_observation(
    case: Mapping[str, object],
    error_detail: str,
    elapsed_seconds: float,
) -> dict[str, object]:
    """Build explicit failed evidence for a controlled executor error."""

    result: dict[str, object] = {
        "tool_ids": [],
        "approval_tool_ids": [],
        "tenant_isolated": False,
        "prompt_injection_blocked": False,
        "execution_status": "failed",
        "error_detail": error_detail,
        "actions": [],
    }
    if cast(list[str], case["required_citations"]):
        result["citations"] = []
    if case["max_latency_ms"] is not None:
        result["latency_ms"] = min(MAX_LATENCY_MS, elapsed_seconds * 1000)
    if cast(bool, case["failure_expected"]):
        result["failure_handled"] = False
    if cast(bool, case["regression_expected"]):
        result["regression_passed"] = False
    return result


def _bounded_error(error: Exception) -> str:
    detail = " ".join(str(error).split())
    return redact_text(detail)[:240] or error.__class__.__name__


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_EXPECTED_TOOLS:
        raise EvaluationValidationError(f"{field} must contain 0-{MAX_EXPECTED_TOOLS} items")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise EvaluationValidationError(f"{field} must contain non-empty text")
    result = [item.strip() for item in value]
    if len(set(result)) != len(result):
        raise EvaluationValidationError(f"{field} must not contain duplicates")
    return result


def _required_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise EvaluationValidationError(f"{field} must be boolean evidence")
    return value


def _latency_limit(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationValidationError("max_latency_ms must be a number")
    if value < 0 or value > MAX_LATENCY_MS:
        raise EvaluationValidationError(f"max_latency_ms must be between 0 and {MAX_LATENCY_MS}")
    return int(value)


def _latency_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationValidationError("latency_ms must be a number")
    if value < 0 or value > MAX_LATENCY_MS:
        raise EvaluationValidationError(f"latency_ms must be between 0 and {MAX_LATENCY_MS}")
    return float(value)
