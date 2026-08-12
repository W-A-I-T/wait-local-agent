from __future__ import annotations

import pytest

from wait_local_agent.evaluation import EvaluationValidationError, evaluate_tool_contract


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
    ],
)
def test_evaluation_rejects_malformed_contracts(test_set, observations, message) -> None:
    with pytest.raises(EvaluationValidationError, match=message):
        evaluate_tool_contract(test_set, observations)
