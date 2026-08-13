"""Bounded consultant evaluation contracts and controlled execution."""

from __future__ import annotations

import json
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
MAX_SECURITY_DIMENSIONS = 16
MAX_SECRET_INPUT_KEYS = 8
MAX_CASE_INPUT_FIELDS = 16
MAX_CASE_INPUT_BYTES = 16_384
MAX_CASE_INPUT_DEPTH = 8
MAX_ACTION_OUTCOMES = 64
_ACTION_APPROVAL_STATUSES = frozenset({"pending_approval", "success"})
SECURITY_DIMENSIONS = (
    "rbac",
    "tool_injection",
    "secret_leakage",
    "unexpected_writes",
    "timeout",
    "retries",
    "cancellation",
    "provider_failure",
    "malformed_provider_output",
    "duplicate_prevention",
    "partial_failure",
    "rollback",
)
_SECURITY_DIMENSION_SET = frozenset(SECURITY_DIMENSIONS)


class EvaluationValidationError(ValueError):
    """Raised when an evaluation test set, observation, or runner is unsafe."""


class EvaluationExecutor(Protocol):
    """A controlled adapter around an existing local runtime execution."""

    def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
        """Execute one already-validated case and return captured evidence."""


def evaluate_tool_contract(
    test_set: list[dict[str, object]],
    observations: Mapping[str, object],
    *,
    runtime_evidence_provenance: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    normalized_cases = _validated_cases(test_set)
    cases: list[dict[str, object]] = []
    for case in normalized_cases:
        case_id = cast(str, case["id"])
        observed = _observation(
            observations.get(case_id),
            case,
            trusted_runtime_provenance=(runtime_evidence_provenance or {}).get(case_id),
        )
        expected_tools = set(cast(list[str], case["expected_tool_ids"]))
        observed_tools = set(cast(list[str], observed["tool_ids"]))
        expected_approvals = set(cast(list[str], case["expected_approval_tool_ids"]))
        observed_approvals = set(cast(list[str], observed["approval_tool_ids"]))
        expected_successful_tools = set(cast(list[str], case["expected_successful_tool_ids"]))
        action_outcomes_present = "action_outcomes" in observed
        successful_tools = set(cast(list[str], observed.get("successful_tool_ids", [])))
        if action_outcomes_present and not expected_successful_tools and not bool(case["failure_expected"]):
            expected_successful_tools = expected_tools
        checks: dict[str, bool] = {
            "functional": (
                expected_tools <= observed_tools
                and expected_successful_tools <= successful_tools
                and (not expected_successful_tools or action_outcomes_present)
            ),
            "tool_selection": expected_tools <= observed_tools
            and not set(cast(list[str], case["forbidden_tool_ids"])) & observed_tools,
            "approval_safety": expected_approvals <= observed_approvals,
            "tenant_isolation": cast(bool, observed["tenant_isolated"]),
            "injection_safety": cast(bool, observed["prompt_injection_blocked"]),
        }
        security_evidence = cast(dict[str, bool], observed.get("security_evidence", {}))
        for dimension in cast(list[str], case["required_security_dimensions"]):
            checks[dimension] = security_evidence.get(dimension, False)
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
            key: observed[key]
            for key in (
                "actions",
                "execution_status",
                "run_id",
                "error_detail",
                "security_evidence",
                "security_evidence_provenance",
                "action_outcomes",
            )
            if key in observed
        }
        case_result: dict[str, object] = {
            "id": case_id,
            "checks": checks,
            "passed": all(checks.values()),
        }
        if "security_evidence_provenance" in observed:
            case_result["security_evidence_provenance"] = observed["security_evidence_provenance"]
        if execution_evidence:
            case_result["execution"] = execution_evidence
        cases.append(case_result)

    dimension_order = (
        "functional",
        "tool_selection",
        "approval_safety",
        "tenant_isolation",
        "injection_safety",
        *SECURITY_DIMENSIONS,
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

    normalized_cases = _validated_cases(test_set)
    observations: dict[str, object] = {}
    runtime_evidence_provenance: dict[str, Mapping[str, str]] = {}
    execution_errors: list[dict[str, str]] = []
    for case in normalized_cases:
        case_id = cast(str, case["id"])
        started = time.monotonic()
        try:
            observed = executor.execute(case)
            if not isinstance(observed, Mapping):
                raise EvaluationValidationError("controlled executor must return an object")
            observations[case_id] = dict(observed)
            provenance = observed.get("security_evidence_provenance")
            if isinstance(provenance, Mapping):
                runtime_evidence_provenance[case_id] = {
                    str(dimension): str(source)
                    for dimension, source in provenance.items()
                    if isinstance(dimension, str) and isinstance(source, str)
                }
        except EvaluationValidationError:
            raise
        except Exception as exc:  # noqa: BLE001 - convert provider failure into explicit failed evidence.
            safe_error = _bounded_error(exc)
            execution_errors.append({"case_id": case_id, "error": safe_error})
            observations[case_id] = _failed_observation(case, safe_error, time.monotonic() - started)

    result = evaluate_tool_contract(
        [cast(dict[str, object], case) for case in normalized_cases],
        observations,
        runtime_evidence_provenance=runtime_evidence_provenance,
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
        self.input_payload = _bounded_input_payload(input_payload or {}, "evaluation execution input")
        self.client_id = client_id

    def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
        started = time.monotonic()
        case_input = _bounded_input_payload(case.get("input", {}), "evaluation case input")
        input_payload = (
            _bounded_input_payload({**self.input_payload, **case_input}, "evaluation merged input")
            if case_input
            else dict(self.input_payload)
        )
        result = self.agent_service.run(
            self.definition,
            entity_id=self.entity_id,
            actor=self.actor,
            input_payload=input_payload,
            actor_role=self.actor_role,
        )
        tool_ids: list[str] = []
        approval_tool_ids: list[str] = []
        citations: list[str] = []
        actions: list[dict[str, object]] = []
        action_outcomes: list[dict[str, object]] = []
        for raw_step in result.steps:
            tool_id = raw_step.get("tool_id")
            status = raw_step.get("status", "failed")
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
            action_outcomes.append(
                {
                    "tool_id": tool_id if isinstance(tool_id, str) else None,
                    "status": status if isinstance(status, str) else "failed",
                    "approval_id": raw_step.get("approval_id"),
                }
            )
        security_evidence, security_evidence_provenance = _controlled_security_evidence(
            self.agent_service,
            result,
            result.steps,
            actor_role=self.actor_role,
            client_id=self.client_id,
            definition_client_id=self.definition.client_id,
            result_aware=bool(getattr(self.definition, "result_aware", False)),
            required_dimensions=cast(list[str], case.get("required_security_dimensions", [])),
            input_payload=input_payload,
            secret_input_keys=cast(list[str], case.get("secret_input_keys", [])),
            definition_enabled_tools=cast(list[str], getattr(self.definition, "enabled_tools", [])),
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
            "security_evidence": security_evidence,
            "security_evidence_provenance": security_evidence_provenance,
            "action_outcomes": action_outcomes,
        }


def _validate_test_set(test_set: object) -> list[object]:
    if not isinstance(test_set, list) or not 1 <= len(test_set) <= MAX_EVALUATION_CASES:
        raise EvaluationValidationError(f"test_set must contain 1-{MAX_EVALUATION_CASES} cases")
    return test_set


def _validated_cases(test_set: object) -> list[dict[str, object]]:
    cases = [_case(raw_case) for raw_case in _validate_test_set(test_set)]
    identifiers = [cast(str, case["id"]) for case in cases]
    if len(set(identifiers)) != len(identifiers):
        raise EvaluationValidationError("test_set case ids must not contain duplicates")
    return cases


def _case(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError("evaluation case must be an object")
    case = dict(value)
    allowed = {
        "id",
        "expected_tool_ids",
        "forbidden_tool_ids",
        "expected_approval_tool_ids",
        "expected_successful_tool_ids",
        "required_citations",
        "max_latency_ms",
        "failure_expected",
        "regression_expected",
        "required_security_dimensions",
        "secret_input_keys",
        "input",
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
        "expected_successful_tool_ids": _string_list(
            case.get("expected_successful_tool_ids", []), "expected_successful_tool_ids"
        ),
        "required_citations": _string_list(case.get("required_citations", []), "required_citations"),
        "max_latency_ms": _latency_limit(case.get("max_latency_ms")),
        "failure_expected": _required_bool(case.get("failure_expected", False), "failure_expected"),
        "regression_expected": _required_bool(case.get("regression_expected", False), "regression_expected"),
        "required_security_dimensions": _security_dimensions(case.get("required_security_dimensions", [])),
        "secret_input_keys": _string_list(
            case.get("secret_input_keys", []), "secret_input_keys", MAX_SECRET_INPUT_KEYS
        ),
        "input": _bounded_input_payload(case.get("input", {}), "evaluation case input"),
    }


def _observation(
    value: object,
    case: Mapping[str, object],
    *,
    trusted_runtime_provenance: Mapping[str, str] | None = None,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise EvaluationValidationError("each test case requires an observation")
    observation = dict(value)
    action_outcomes_provided = "action_outcomes" in observation
    result: dict[str, object] = {
        "tool_ids": []
        if action_outcomes_provided
        else _string_list(observation.get("tool_ids"), "observation.tool_ids"),
        "approval_tool_ids": []
        if action_outcomes_provided
        else _string_list(observation.get("approval_tool_ids"), "observation.approval_tool_ids"),
        "tenant_isolated": _required_bool(observation.get("tenant_isolated"), "tenant_isolated"),
        "prompt_injection_blocked": _required_bool(
            observation.get("prompt_injection_blocked"), "prompt_injection_blocked"
        ),
    }
    if "action_outcomes" in observation:
        action_outcomes = _action_outcomes(observation.get("action_outcomes"))
        result["action_outcomes"] = action_outcomes
        result["tool_ids"] = [
            cast(str, outcome["tool_id"])
            for outcome in action_outcomes
            if isinstance(outcome.get("tool_id"), str)
        ]
        result["successful_tool_ids"] = [
            cast(str, outcome["tool_id"])
            for outcome in action_outcomes
            if isinstance(outcome.get("tool_id"), str) and outcome["status"] == "success"
        ]
        result["approval_tool_ids"] = [
            cast(str, outcome["tool_id"])
            for outcome in action_outcomes
            if (
                isinstance(outcome.get("tool_id"), str)
                and outcome.get("approval_id") is not None
                and outcome["status"] in _ACTION_APPROVAL_STATUSES
            )
        ]
    if cast(list[str], case["required_citations"]):
        result["citations"] = _string_list(observation.get("citations"), "citations")
    if case["max_latency_ms"] is not None:
        result["latency_ms"] = _latency_value(observation.get("latency_ms"))
    if cast(bool, case["failure_expected"]):
        result["failure_handled"] = _required_bool(observation.get("failure_handled"), "failure_handled")
    if cast(bool, case["regression_expected"]):
        result["regression_passed"] = _required_bool(observation.get("regression_passed"), "regression_passed")
    raw_security_evidence = observation.get("security_evidence", {})
    if raw_security_evidence is None:
        raw_security_evidence = {}
    if not isinstance(raw_security_evidence, Mapping):
        raise EvaluationValidationError("observation.security_evidence must be an object")
    security_evidence: dict[str, bool] = {}
    security_evidence_provenance: dict[str, str] = {}
    trusted_runtime_provenance = trusted_runtime_provenance or {}
    for dimension in cast(list[str], case["required_security_dimensions"]):
        value = raw_security_evidence.get(dimension, False)
        if not isinstance(value, bool):
            raise EvaluationValidationError(f"security_evidence.{dimension} must be boolean evidence")
        security_evidence[dimension] = value
        trusted_source = trusted_runtime_provenance.get(dimension)
        security_evidence_provenance[dimension] = (
            trusted_source
            if trusted_source in {"runtime", "unsupported"}
            else "observation"
            if dimension in raw_security_evidence
            else "unsupported"
        )
    if security_evidence:
        result["security_evidence"] = security_evidence
        result["security_evidence_provenance"] = security_evidence_provenance
    for field in ("actions", "execution_status", "run_id", "error_detail"):
        if field in observation:
            result[field] = observation[field]
    return result


def _action_outcomes(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) > MAX_ACTION_OUTCOMES:
        raise EvaluationValidationError(f"observation.action_outcomes must contain 0-{MAX_ACTION_OUTCOMES} items")
    outcomes: list[dict[str, object]] = []
    for raw_outcome in value:
        if not isinstance(raw_outcome, Mapping):
            raise EvaluationValidationError("observation.action_outcomes must contain objects")
        unknown = sorted(set(raw_outcome) - {"tool_id", "status", "approval_id"})
        if unknown:
            raise EvaluationValidationError(
                f"unsupported action outcome fields: {', '.join(str(item) for item in unknown)}"
            )
        tool_id = raw_outcome.get("tool_id")
        if tool_id is not None and (not isinstance(tool_id, str) or not tool_id.strip()):
            raise EvaluationValidationError("action outcome tool_id must be text or null")
        status = raw_outcome.get("status")
        if not isinstance(status, str) or not status.strip() or len(status) > 64:
            raise EvaluationValidationError("action outcome status must be bounded text")
        approval_id = raw_outcome.get("approval_id")
        if approval_id is not None and (
            isinstance(approval_id, bool) or not isinstance(approval_id, int) or approval_id < 1
        ):
            raise EvaluationValidationError("action outcome approval_id must be a positive integer or null")
        outcomes.append(
            {
                "tool_id": tool_id.strip() if isinstance(tool_id, str) else None,
                "status": status.strip(),
                "approval_id": approval_id,
            }
        )
    return outcomes


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
    required_security = cast(list[str], case["required_security_dimensions"])
    if required_security:
        result["security_evidence"] = {dimension: False for dimension in required_security}
        result["security_evidence_provenance"] = {dimension: "unsupported" for dimension in required_security}
    return result


def _controlled_security_evidence(
    agent_service: AgentService,
    result: object,
    steps: list[dict[str, object]],
    *,
    actor_role: Role,
    client_id: str,
    definition_client_id: str | None,
    result_aware: bool,
    required_dimensions: list[str],
    input_payload: Mapping[str, object],
    secret_input_keys: list[str],
    definition_enabled_tools: list[str],
) -> tuple[dict[str, bool], dict[str, str]]:
    """Return only security facts the local runtime can prove deterministically.

    Lifecycle evidence is derived only from the bounded result status and the
    persisted final-result lineage. Tool allowlist and configured secret-input
    checks are deterministic runtime evidence. Prompt injection, provider-side
    leakage, and rollback remain explicit evidence requirements and fail closed
    unless a caller supplies dedicated evidence.
    """

    raw_tools: list[Any] = getattr(agent_service, "list_tools", lambda: [])()
    tools = {tool.id: tool for tool in raw_tools if isinstance(getattr(tool, "id", None), str)}
    rbac_safe = definition_client_id == client_id
    unexpected_write = False
    for step in steps:
        tool_id = step.get("tool_id")
        tool = tools.get(tool_id) if isinstance(tool_id, str) else None
        if tool is None or not _role_allows(getattr(tool, "required_role", None), actor_role):
            rbac_safe = False
        if (
            tool is not None
            and getattr(tool, "access_mode", None) == "write"
            and step.get("status") == "success"
        ):
            unexpected_write = True
    writes_disabled = not bool(getattr(agent_service.settings, "allow_write_actions", True))
    evidence = {
        "rbac": rbac_safe,
        "unexpected_writes": writes_disabled and not unexpected_write,
    }
    provenance = {dimension: "runtime" for dimension in evidence}
    if not required_dimensions:
        return evidence, provenance

    status = getattr(result, "status", "")
    status = status if isinstance(status, str) else ""
    error_detail = getattr(result, "error_detail", "")
    error_detail = error_detail if isinstance(error_detail, str) else ""
    final_result = getattr(result, "final_result", {})
    if not isinstance(final_result, Mapping):
        final_result = {}
    history = final_result.get("history")
    if not isinstance(history, Mapping):
        history = {}
    exception = final_result.get("exception")
    if not isinstance(exception, Mapping):
        exception = {}
    retry_count = final_result.get("retry_count")
    retry_of_run_id = final_result.get("retry_of_run_id")
    tool_ids = [
        tool_id
        for step in steps
        if isinstance((tool_id := step.get("tool_id")), str)
    ]
    action_run_ids = [
        action_run_id
        for step in steps
        if isinstance((action_run_id := step.get("action_run_id")), int)
        and not isinstance(action_run_id, bool)
    ]
    lifecycle_evidence = {
        "timeout": status == "failed" and "timed out" in error_detail.casefold(),
        "cancellation": status == "cancelled" and "cancelled" in error_detail.casefold(),
        "retries": (
            isinstance(retry_count, int)
            and not isinstance(retry_count, bool)
            and retry_count > 0
            and isinstance(retry_of_run_id, int)
            and not isinstance(retry_of_run_id, bool)
        ),
        "duplicate_prevention": (
            result_aware
            and bool(tool_ids)
            and len(tool_ids) == len(set(tool_ids))
            and len(action_run_ids) == len(set(action_run_ids))
        ),
        "partial_failure": history.get("partial") is True,
        "provider_failure": exception.get("kind") == "provider_failure",
        "malformed_provider_output": exception.get("kind") == "malformed_output",
    }
    if "tool_injection" in required_dimensions:
        evidence["tool_injection"] = bool(definition_enabled_tools) and all(
            tool_id in definition_enabled_tools for tool_id in tool_ids
        )
    if "secret_leakage" in required_dimensions:
        evidence["secret_leakage"] = _secret_values_absent(
            input_payload,
            secret_input_keys,
            result,
            steps,
        )
    evidence.update(
        {
            dimension: lifecycle_evidence[dimension]
            for dimension in required_dimensions
            if dimension in lifecycle_evidence
        }
    )
    provenance.update({dimension: "runtime" for dimension in evidence})
    return evidence, provenance


def _role_allows(required_role: object, actor_role: Role) -> bool:
    levels = {"end_user": 0, "viewer": 1, "technician": 2, "admin": 3}
    return isinstance(required_role, str) and levels.get(required_role.casefold(), -1) <= int(actor_role)


def _secret_values_absent(
    input_payload: Mapping[str, object],
    secret_input_keys: list[str],
    result: object,
    steps: list[dict[str, object]],
) -> bool:
    """Check configured secret inputs without returning or persisting values."""

    if not secret_input_keys:
        return False
    secret_values: list[str] = []
    for key in secret_input_keys:
        value = input_payload.get(key)
        if not isinstance(value, str) or not value:
            return False
        secret_values.append(value)
    try:
        evidence_text = json.dumps(
            {
                "result": getattr(result, "final_result", {}),
                "error": getattr(result, "error_detail", ""),
                "steps": steps,
            },
            sort_keys=True,
            default=str,
            ensure_ascii=False,
        )
    except (TypeError, ValueError):
        return False
    return not any(secret in evidence_text for secret in secret_values)


def _bounded_error(error: Exception) -> str:
    detail = " ".join(str(error).split())
    return redact_text(detail)[:240] or error.__class__.__name__


def _string_list(value: object, field: str, maximum: int = MAX_EXPECTED_TOOLS) -> list[str]:
    if not isinstance(value, list) or len(value) > maximum:
        raise EvaluationValidationError(f"{field} must contain 0-{maximum} items")
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


def _security_dimensions(value: object) -> list[str]:
    dimensions = _string_list(value, "required_security_dimensions", MAX_SECURITY_DIMENSIONS)
    unknown = sorted(set(dimensions) - _SECURITY_DIMENSION_SET)
    if unknown:
        raise EvaluationValidationError(f"unsupported security dimensions: {', '.join(unknown)}")
    return dimensions


def _bounded_input_payload(value: object, field: str) -> dict[str, object]:
    """Validate evaluation inputs without redacting the in-memory fixture values."""

    if not isinstance(value, Mapping):
        raise EvaluationValidationError(f"{field} must be an object")
    payload = dict(value)
    if not payload:
        return {}
    if len(payload) > MAX_CASE_INPUT_FIELDS:
        raise EvaluationValidationError(f"{field} must contain at most {MAX_CASE_INPUT_FIELDS} fields")
    if any(not isinstance(key, str) or not key.strip() or len(key) > 80 for key in payload):
        raise EvaluationValidationError(f"{field} field names must be non-empty text of at most 80 characters")
    try:
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise EvaluationValidationError(f"{field} must contain JSON-compatible values") from exc
    if len(encoded.encode("utf-8")) > MAX_CASE_INPUT_BYTES:
        raise EvaluationValidationError(f"{field} must be at most {MAX_CASE_INPUT_BYTES} bytes")
    if _input_depth(payload) > MAX_CASE_INPUT_DEPTH:
        raise EvaluationValidationError(f"{field} nesting exceeds {MAX_CASE_INPUT_DEPTH} levels")
    return payload


def _input_depth(value: object, depth: int = 0) -> int:
    if isinstance(value, Mapping):
        return max(((_input_depth(item, depth + 1)) for item in value.values()), default=depth)
    if isinstance(value, list):
        return max((_input_depth(item, depth + 1) for item in value), default=depth)
    return depth
