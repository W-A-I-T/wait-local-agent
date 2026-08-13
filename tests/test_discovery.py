from __future__ import annotations

import pytest

from wait_local_agent.discovery import DiscoveryValidationError, build_solution_discovery


def _answers() -> dict[str, object]:
    return {
        "solution_name": "Employee onboarding",
        "business_goal": "Reduce manual onboarding work",
        "users": ["HR", "IT"],
        "knowledge": ["SharePoint HR policies"],
        "systems": ["Microsoft Entra", "Teams"],
        "reads": ["Employee record", "HR policy"],
        "changes": ["Create user", "Assign license"],
        "approvals": ["Assign license"],
        "failure_handling": "Pause and create an approval review",
        "licenses": ["Microsoft 365 E3"],
        "data_location": ["Tenant SharePoint"],
        "data_leaves_tenant": False,
        "impact": {
            "monthly_runs": 80,
            "minutes_saved_per_run": 25,
            "affected_users": 12,
            "hourly_value": 60,
        },
    }


def test_discovery_returns_evidence_bound_blueprint_and_roi() -> None:
    result = build_solution_discovery(client_id="acme", answers=_answers())

    assert result["readiness"] == "ready_for_architecture"
    assert result["missing_required"] == []
    assert result["risk_review"]["level"] == "medium"
    assert result["roi_analysis"]["estimated_monthly_hours_saved"] == 33.33
    assert result["roi_analysis"]["estimated_monthly_value"] == 2000.0
    assert result["blueprint_candidate"]["approvals"] == {"Assign license": "human_review_required"}
    assert result["execution_started"] is False
    assert result["deployment_started"] is False


def test_discovery_reports_missing_answers_without_inventing_them() -> None:
    result = build_solution_discovery(client_id="acme", answers={"business_goal": "Improve onboarding"})

    assert result["readiness"] == "needs_discovery"
    assert "systems" in result["missing_required"]
    assert result["blueprint_candidate"]["systems"] == []
    assert result["roi_analysis"]["status"] == "needs_estimates"


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        ({"unknown": "value"}, "unsupported discovery"),
        ({"data_leaves_tenant": "yes"}, "must be boolean"),
        ({"users": ["HR", "HR"]}, "must not contain duplicates"),
        ({"impact": {"monthly_runs": 0}}, "monthly_runs must be an integer"),
        (
            {
                "impact": {
                    "monthly_runs": 1,
                    "minutes_saved_per_run": 1,
                    "affected_users": 1,
                    "hourly_value": -1,
                }
            },
            "hourly_value must be a number",
        ),
        ({"business_goal": "password=secret"}, "secret material"),
        ({"business_goal": "bad\nvalue"}, "unsupported control characters"),
        ({"users": "HR"}, "users must contain"),
        ({"impact": "not-an-object"}, "impact must be an object"),
        ({"impact": {"unexpected": 1}}, "unsupported impact fields"),
        (
            {"impact": {"monthly_runs": 1, "minutes_saved_per_run": 1, "affected_users": 1}},
            "estimated_monthly",
        ),
    ],
)
def test_discovery_rejects_unsafe_or_invalid_answers(answers, message) -> None:
    if message == "estimated_monthly":
        result = build_solution_discovery(client_id="acme", answers=answers)
        assert "estimated_monthly_value" not in result["roi_analysis"]
    else:
        with pytest.raises(DiscoveryValidationError, match=message):
            build_solution_discovery(client_id="acme", answers=answers)
