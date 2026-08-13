from __future__ import annotations

from collections.abc import Mapping

import pytest

from wait_local_agent.evaluation import (
    EvaluationValidationError,
    evaluate_tool_contract,
    execute_tool_contract,
)


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
    ],
)
def test_evaluation_rejects_malformed_contracts(test_set, observations, message) -> None:
    with pytest.raises(EvaluationValidationError, match=message):
        evaluate_tool_contract(test_set, observations)
