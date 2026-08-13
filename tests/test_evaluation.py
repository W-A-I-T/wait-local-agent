from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from wait_local_agent.agents import AgentService
from wait_local_agent.evaluation import (
    AgentServiceEvaluationExecutor,
    EvaluationValidationError,
    evaluate_tool_contract,
    execute_tool_contract,
)
from wait_local_agent.rbac import Role


def _case(case_id: str = "onboarding") -> dict[str, object]:
    return {
        "id": case_id,
        "expected_tool_ids": ["m365-user-create"],
        "forbidden_tool_ids": ["m365-license-change"],
        "expected_approval_tool_ids": ["m365-user-create"],
    }


def _observation(**overrides: object) -> dict[str, object]:
    return {
        "tool_ids": ["m365-user-create"],
        "approval_tool_ids": ["m365-user-create"],
        "tenant_isolated": True,
        "prompt_injection_blocked": True,
        **overrides,
    }


def test_evaluation_scores_observed_contract_without_execution() -> None:
    result = evaluate_tool_contract([_case()], {"onboarding": _observation()})

    assert result["production_readiness"] == "pass"
    assert result["execution_started"] is False
    assert result["dimensions"] == {
        "functional": 100.0,
        "tool_selection": 100.0,
        "approval_safety": 100.0,
        "tenant_isolation": 100.0,
        "injection_safety": 100.0,
    }
    assert result["cases"][0]["passed"] is True


def test_evaluation_reports_failed_security_and_forbidden_tool_checks() -> None:
    result = evaluate_tool_contract(
        [_case("safe"), _case("unsafe")],
        {
            "safe": _observation(),
            "unsafe": _observation(
                tool_ids=["m365-user-create", "m365-license-change"],
                tenant_isolated=False,
                prompt_injection_blocked=False,
            ),
        },
    )

    assert result["production_readiness"] == "needs_review"
    assert result["dimensions"]["tenant_isolation"] == 50.0
    assert result["dimensions"]["injection_safety"] == 50.0
    assert result["cases"][1]["passed"] is False


def test_evaluation_supports_grounding_latency_failure_and_regression_evidence() -> None:
    case = {
        **_case(),
        "required_citations": ["sharepoint:handbook"],
        "max_latency_ms": 1000,
        "failure_expected": True,
        "regression_expected": True,
    }
    result = evaluate_tool_contract(
        [case],
        {
            "onboarding": _observation(
                citations=["sharepoint:handbook"],
                latency_ms=240,
                failure_handled=True,
                regression_passed=True,
            )
        },
    )

    assert result["production_readiness"] == "pass"
    assert result["dimensions"]["grounding"] == 100.0
    assert result["dimensions"]["latency"] == 100.0
    assert result["dimensions"]["failure_handling"] == 100.0
    assert result["dimensions"]["regression"] == 100.0


def test_evaluation_reports_grounding_and_latency_failures() -> None:
    case = {**_case(), "required_citations": ["sharepoint:handbook"], "max_latency_ms": 100}
    result = evaluate_tool_contract(
        [case],
        {"onboarding": _observation(citations=["other:source"], latency_ms=101)},
    )

    assert result["production_readiness"] == "needs_review"
    assert result["dimensions"]["grounding"] == 0.0
    assert result["dimensions"]["latency"] == 0.0
    assert result["cases"][0]["passed"] is False


def test_evaluation_requires_explicit_security_and_failure_evidence() -> None:
    case = {
        **_case(),
        "required_security_dimensions": [
            "rbac",
            "tool_injection",
            "secret_leakage",
            "unexpected_writes",
            "provider_failure",
            "rollback",
        ],
    }
    evidence = {
        "rbac": True,
        "tool_injection": True,
        "secret_leakage": True,
        "unexpected_writes": True,
        "provider_failure": True,
        "rollback": True,
    }
    result = evaluate_tool_contract(
        [case],
        {"onboarding": _observation(security_evidence=evidence)},
    )

    assert result["production_readiness"] == "pass"
    assert result["dimensions"]["rbac"] == 100.0
    assert result["dimensions"]["rollback"] == 100.0
    assert result["cases"][0]["checks"]["unexpected_writes"] is True

    incomplete = evaluate_tool_contract(
        [case],
        {"onboarding": _observation(security_evidence={"rbac": True})},
    )
    assert incomplete["production_readiness"] == "needs_review"
    assert incomplete["cases"][0]["checks"]["tool_injection"] is False
    assert incomplete["cases"][0]["checks"]["rollback"] is False


def test_controlled_evaluation_executes_each_case_and_captures_runtime_evidence() -> None:
    class Runner:
        def __init__(self) -> None:
            self.case_ids: list[str] = []

        def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
            self.case_ids.append(str(case["id"]))
            return {
                **_observation(),
                "actions": [{"tool_id": "m365-user-create", "status": "pending_approval"}],
                "execution_status": "pending_approval",
                "run_id": 7,
            }

    runner = Runner()
    result = execute_tool_contract([_case("first"), _case("second")], runner)

    assert runner.case_ids == ["first", "second"]
    assert result["execution_started"] is True
    assert result["execution_mode"] == "controlled"
    assert result["executed_case_count"] == 2
    assert result["execution_errors"] == []
    assert result["cases"][0]["execution"]["run_id"] == 7


def test_controlled_evaluation_turns_provider_failure_into_failed_evidence() -> None:
    class FailingRunner:
        def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
            raise RuntimeError("provider unavailable")

    result = execute_tool_contract([_case()], FailingRunner())

    assert result["execution_started"] is True
    assert result["production_readiness"] == "needs_review"
    assert result["execution_errors"] == [{"case_id": "onboarding", "error": "provider unavailable"}]
    assert result["cases"][0]["execution"]["execution_status"] == "failed"
    assert result["cases"][0]["passed"] is False


@pytest.mark.parametrize(
    "runner",
    [
        type("NonMappingRunner", (), {"execute": lambda self, case: []})(),
        type(
            "ValidationRunner",
            (),
            {"execute": lambda self, case: (_ for _ in ()).throw(EvaluationValidationError("invalid evidence"))},
        )(),
    ],
)
def test_controlled_evaluation_rejects_invalid_executor_contracts(runner) -> None:
    with pytest.raises(EvaluationValidationError):
        execute_tool_contract([_case()], runner)


def test_controlled_failure_preserves_all_requested_failure_evidence() -> None:
    case = {
        **_case(),
        "required_citations": ["fixture:source"],
        "max_latency_ms": 1000,
        "failure_expected": True,
        "regression_expected": True,
        "required_security_dimensions": ["provider_failure", "rollback"],
    }

    class FailingRunner:
        def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
            raise RuntimeError("provider unavailable")

    result = execute_tool_contract([case], FailingRunner())
    evidence = result["cases"][0]["execution"]
    assert evidence["security_evidence"] == {"provider_failure": False, "rollback": False}
    assert result["cases"][0]["checks"]["failure_handling"] is False
    assert result["cases"][0]["checks"]["regression"] is False


def test_evaluation_normalizes_optional_security_evidence_and_rejects_bounds() -> None:
    case = {**_case(), "required_security_dimensions": ["rbac"]}
    missing = evaluate_tool_contract([case], {"onboarding": _observation(security_evidence=None)})
    assert missing["cases"][0]["checks"]["rbac"] is False

    with pytest.raises(EvaluationValidationError, match="security_evidence must be an object"):
        evaluate_tool_contract([case], {"onboarding": _observation(security_evidence="nope")})
    with pytest.raises(EvaluationValidationError, match="test_set must contain"):
        evaluate_tool_contract([_case()] * 33, {"onboarding": _observation()})
    with pytest.raises(EvaluationValidationError, match="max_latency_ms must be a number"):
        evaluate_tool_contract([{**_case(), "max_latency_ms": "fast"}], {"onboarding": _observation()})
    with pytest.raises(EvaluationValidationError, match="latency_ms must be a number"):
        evaluate_tool_contract(
            [{**_case(), "max_latency_ms": 100}],
            {"onboarding": _observation(latency_ms="fast")},
        )
    with pytest.raises(EvaluationValidationError, match="latency_ms must be between"):
        evaluate_tool_contract(
            [{**_case(), "max_latency_ms": 100}],
            {"onboarding": _observation(latency_ms=120001)},
        )
    with pytest.raises(EvaluationValidationError, match="required_security_dimensions must contain 0-16"):
        evaluate_tool_contract(
            [{**_case(), "required_security_dimensions": ["rbac"] * 17}],
            {"onboarding": _observation()},
        )
    with pytest.raises(EvaluationValidationError, match="case ids must not contain duplicates"):
        evaluate_tool_contract(
            [_case("duplicate"), _case("duplicate")],
            {"duplicate": _observation()},
        )


def test_evaluation_reports_security_evidence_provenance_without_overriding_scores() -> None:
    case = {**_case(), "required_security_dimensions": ["rbac", "rollback"]}
    observed = evaluate_tool_contract(
        [case],
        {"onboarding": _observation(security_evidence={"rbac": True})},
    )

    assert observed["cases"][0]["security_evidence_provenance"] == {
        "rbac": "observation",
        "rollback": "unsupported",
    }
    assert observed["cases"][0]["passed"] is False

    class RuntimeRunner:
        def execute(self, case: Mapping[str, object]) -> Mapping[str, object]:
            return {
                **_observation(security_evidence={"rbac": True, "rollback": False}),
                "security_evidence_provenance": {"rbac": "runtime", "rollback": "runtime"},
            }

    controlled = execute_tool_contract([case], RuntimeRunner())
    assert controlled["cases"][0]["security_evidence_provenance"] == {
        "rbac": "runtime",
        "rollback": "runtime",
    }
    assert controlled["cases"][0]["passed"] is False


def test_controlled_evaluation_requires_tenant_and_identity_boundaries() -> None:
    definition = type("Definition", (), {"client_id": "acme"})()
    with pytest.raises(EvaluationValidationError, match="matching tenant"):
        AgentServiceEvaluationExecutor(
            cast(AgentService, object()),
            definition,
            entity_id="T-1",
            actor="tester",
            actor_role=Role.TECHNICIAN,
            client_id="beta",
        )
    with pytest.raises(EvaluationValidationError, match="entity and actor"):
        AgentServiceEvaluationExecutor(
            cast(AgentService, object()),
            definition,
            entity_id="",
            actor="tester",
            actor_role=Role.TECHNICIAN,
            client_id="acme",
        )
    with pytest.raises(EvaluationValidationError, match="test_set must contain"):
        execute_tool_contract([_case()] * 33, type("Runner", (), {})())


def test_runtime_evaluation_adapter_preserves_step_evidence() -> None:
    class Result:
        run_id = 9
        status = "completed"
        error_detail = ""
        steps = [
            {
                "tool_id": "m365-user-create",
                "approval_id": 3,
                "status": "pending_approval",
                "evidence": ["fixture:source", 4],
                "error_detail": "",
            },
            {"tool_id": None, "evidence": "not-a-list"},
        ]

    class Service:
        settings = type("Settings", (), {"allow_llm_inference": False, "allow_write_actions": False})()

        def list_tools(self):
            return [
                type("Tool", (), {"id": "m365-user-create", "required_role": "technician", "access_mode": "write"})()
            ]

        def run(self, *args, **kwargs):
            return Result()

    definition = type("Definition", (), {"client_id": "acme", "result_aware": False})()
    executor = AgentServiceEvaluationExecutor(
        cast(AgentService, Service()),
        definition,
        entity_id="T-1",
        actor="tester",
        actor_role=Role.TECHNICIAN,
        client_id="acme",
    )
    result = executor.execute({"failure_expected": False})
    assert result["tool_ids"] == ["m365-user-create"]
    assert result["approval_tool_ids"] == ["m365-user-create"]
    assert result["citations"] == ["fixture:source"]
    actions = cast(list[dict[str, object]], result["actions"])
    assert actions[1]["status"] == "failed"
    assert result["security_evidence"] == {"rbac": False, "unexpected_writes": True}


def test_runtime_evaluation_security_evidence_fails_closed_for_unknown_tool_or_enabled_writes() -> None:
    class Result:
        run_id = 10
        status = "completed"
        error_detail = ""
        steps = [{"tool_id": "unknown", "status": "success", "evidence": []}]

    class Service:
        settings = type("Settings", (), {"allow_llm_inference": False, "allow_write_actions": True})()

        def list_tools(self):
            return []

        def run(self, *args, **kwargs):
            return Result()

    definition = type("Definition", (), {"client_id": "acme", "result_aware": False})()
    result = AgentServiceEvaluationExecutor(
        cast(AgentService, Service()),
        definition,
        entity_id="T-1",
        actor="tester",
        actor_role=Role.TECHNICIAN,
        client_id="acme",
    ).execute({"failure_expected": False})
    assert result["security_evidence"] == {"rbac": False, "unexpected_writes": False}


@pytest.mark.parametrize(
    ("dimension", "result", "expected"),
    [
        (
            "timeout",
            type("Result", (), {"run_id": 1, "status": "failed", "error_detail": "agent execution timed out"})(),
            True,
        ),
        (
            "cancellation",
            type("Result", (), {"run_id": 1, "status": "cancelled", "error_detail": "agent run cancelled"})(),
            True,
        ),
        (
            "retries",
            type(
                "Result",
                (),
                {
                    "run_id": 1,
                    "status": "completed",
                    "error_detail": "",
                    "final_result": {"retry_count": 1, "retry_of_run_id": 4},
                },
            )(),
            True,
        ),
        (
            "partial_failure",
            type(
                "Result",
                (),
                {
                    "run_id": 1,
                    "status": "failed",
                    "error_detail": "step failed",
                    "final_result": {"history": {"partial": True}},
                },
            )(),
            True,
        ),
        (
            "provider_failure",
            type(
                "Result",
                (),
                {
                    "run_id": 1,
                    "status": "failed",
                    "error_detail": "provider unavailable",
                    "final_result": {"exception": {"kind": "provider_failure"}},
                },
            )(),
            True,
        ),
        (
            "malformed_provider_output",
            type(
                "Result",
                (),
                {
                    "run_id": 1,
                    "status": "failed",
                    "error_detail": "malformed model output",
                    "final_result": {"exception": {"kind": "malformed_output"}},
                },
            )(),
            True,
        ),
    ],
)
def test_runtime_evaluation_derives_bounded_lifecycle_evidence(dimension, result, expected) -> None:
    result.steps = [{"tool_id": "ticket-triage", "status": "success", "action_run_id": 1}]

    class Service:
        settings = type("Settings", (), {"allow_llm_inference": False, "allow_write_actions": False})()

        def list_tools(self):
            return [type("Tool", (), {"id": "ticket-triage", "required_role": "technician", "access_mode": "read"})()]

        def run(self, *args, **kwargs):
            return result

    definition = type("Definition", (), {"client_id": "acme", "result_aware": False})()
    executor = AgentServiceEvaluationExecutor(
        cast(AgentService, Service()),
        definition,
        entity_id="T-1",
        actor="tester",
        actor_role=Role.TECHNICIAN,
        client_id="acme",
    )
    observed = executor.execute({"required_security_dimensions": [dimension]})
    security_evidence = cast(dict[str, bool], observed["security_evidence"])
    assert security_evidence[dimension] is expected
    provenance = cast(dict[str, str], observed["security_evidence_provenance"])
    assert provenance[dimension] == "runtime"


def test_runtime_evaluation_derives_result_aware_duplicate_prevention() -> None:
    class Result:
        run_id = 12
        status = "completed"
        error_detail = ""
        final_result: dict[str, object] = {}
        steps = [
            {"tool_id": "ticket-triage", "status": "success", "action_run_id": 1},
            {"tool_id": "ticket-summary", "status": "success", "action_run_id": 2},
        ]

    class Service:
        settings = type("Settings", (), {"allow_llm_inference": False, "allow_write_actions": False})()

        def list_tools(self):
            return [
                type("Tool", (), {"id": tool_id, "required_role": "technician", "access_mode": "read"})()
                for tool_id in ("ticket-triage", "ticket-summary")
            ]

        def run(self, *args, **kwargs):
            return Result()

    definition = type("Definition", (), {"client_id": "acme", "result_aware": True})()
    observed = AgentServiceEvaluationExecutor(
        cast(AgentService, Service()),
        definition,
        entity_id="T-1",
        actor="tester",
        actor_role=Role.TECHNICIAN,
        client_id="acme",
    ).execute({"required_security_dimensions": ["duplicate_prevention"]})
    evidence = cast(dict[str, bool], observed["security_evidence"])
    assert evidence["duplicate_prevention"] is True

    Result.steps.append({"tool_id": "ticket-summary", "status": "success", "action_run_id": 3})
    duplicate_observed = AgentServiceEvaluationExecutor(
        cast(AgentService, Service()),
        definition,
        entity_id="T-1",
        actor="tester",
        actor_role=Role.TECHNICIAN,
        client_id="acme",
    ).execute({"required_security_dimensions": ["duplicate_prevention"]})
    duplicate_evidence = cast(dict[str, bool], duplicate_observed["security_evidence"])
    assert duplicate_evidence["duplicate_prevention"] is False


@pytest.mark.parametrize(
    ("test_set", "observations", "message"),
    [
        ([], {}, "test_set must contain"),
        (["not-an-object"], {}, "case must be an object"),
        ([{"id": "Bad ID"}], {}, "bounded identifier"),
        ([{"id": 42}], {}, "id must be text"),
        ([{**_case(), "unknown": True}], {"onboarding": _observation()}, "unsupported"),
        ([_case()], {}, "requires an observation"),
        ([_case()], {"onboarding": {**_observation(), "tenant_isolated": "yes"}}, "must be boolean"),
        ([_case()], {"onboarding": {**_observation(), "tool_ids": ["x"] * 9}}, "contain 0-8"),
        ([_case()], {"onboarding": {**_observation(), "tool_ids": [1]}}, "non-empty text"),
        ([_case()], {"onboarding": {**_observation(), "tool_ids": ["x", "x"]}}, "duplicates"),
        ([{**_case(), "max_latency_ms": 120001}], {"onboarding": _observation()}, "max_latency_ms"),
        (
            [{**_case(), "failure_expected": "yes"}],
            {"onboarding": _observation()},
            "failure_expected",
        ),
        (
            [{**_case(), "required_citations": ["source"]}],
            {"onboarding": _observation()},
            "citations",
        ),
        (
            [{**_case(), "required_security_dimensions": ["not-a-security-dimension"]}],
            {"onboarding": _observation()},
            "unsupported security dimensions",
        ),
        (
            [{**_case(), "required_security_dimensions": ["rbac"]}],
            {"onboarding": _observation(security_evidence={"rbac": "yes"})},
            "must be boolean evidence",
        ),
    ],
)
def test_evaluation_rejects_malformed_contracts(test_set, observations, message) -> None:
    with pytest.raises(EvaluationValidationError, match=message):
        evaluate_tool_contract(test_set, observations)
