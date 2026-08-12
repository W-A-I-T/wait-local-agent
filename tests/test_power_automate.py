from __future__ import annotations

import pytest

from wait_local_agent.power_automate import PowerAutomatePlanError, build_power_automate_flow_plan


def _plan(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "client_id": "acme",
        "workflow_id": "employee_onboarding",
        "workflow_name": "Employee onboarding",
        "trigger": "HR request",
        "steps": [
            {"id": "validate_manager", "name": "Validate manager", "kind": "condition"},
            {
                "id": "create_user",
                "name": "Create Entra user",
                "tool_id": "m365_user_create",
                "method": "POST",
                "approval_required": True,
            },
            {"id": "notify_manager", "name": "Notify manager", "tool_id": "teams_message", "method": "GET"},
        ],
    }
    payload.update(overrides)
    return payload


def test_power_automate_plan_is_review_only_and_approval_aware() -> None:
    result = build_power_automate_flow_plan(**_plan())

    assert result["format"] == "wait-local-agent.power-automate-flow-plan"
    assert result["power_automate"]["actions"][1]["type"] == "Action"
    assert result["requires_approval"] is True
    assert result["credentials_included"] is False
    assert result["execution_started"] is False
    assert result["deployment_started"] is False


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda value: value.update(
                {"steps": [{"id": "write", "name": "Write", "method": "POST"}]}
            ),
            "requires approval",
        ),
        (
            lambda value: value.update(
                {"steps": [{"id": "write", "name": "Write", "method": "TRACE"}]}
            ),
            "step method",
        ),
        (
            lambda value: value.update(
                {"steps": [{"id": "one", "name": "One"}, {"id": "one", "name": "Again"}]}
            ),
            "duplicate step",
        ),
        (
            lambda value: value.update(
                {"steps": [{"id": "one", "name": "One", "kind": "unknown"}]}
            ),
            "step kind",
        ),
        (
            lambda value: value.update(
                {"steps": [{"id": "one", "name": "One", "tool_id": "api_token"}]}
            ),
            "secret material",
        ),
        (
            lambda value: value.update(
                {"steps": [{"id": "one", "name": "One", "unexpected": True}]}
            ),
            "unsupported step",
        ),
        (lambda value: value.update({"steps": []}), "steps must contain"),
    ],
)
def test_power_automate_plan_rejects_unsafe_shapes(change, message) -> None:
    payload = _plan()
    change(payload)
    with pytest.raises(PowerAutomatePlanError, match=message):
        build_power_automate_flow_plan(**payload)
