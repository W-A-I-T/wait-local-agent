from __future__ import annotations

from typing import Any

import pytest

from wait_local_agent.copilot_studio import CopilotStudioPlanError, build_copilot_studio_plan


def _plan(**overrides: object) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "client_id": "acme",
        "copilot_name": "Employee onboarding copilot",
        "business_goal": "Guide HR through an auditable onboarding request.",
        "topics": [
            {
                "id": "onboarding_request",
                "name": "Onboarding request",
                "trigger_phrases": ["start onboarding", "new employee"],
            }
        ],
        "knowledge_sources": ["employee-handbook", "onboarding-runbook"],
        "actions": [
            {"id": "lookup_employee", "connector_id": "m365", "method": "GET"},
            {
                "id": "prepare_identity",
                "connector_id": "m365",
                "method": "POST",
                "approval_required": True,
            },
        ],
    }
    payload.update(overrides)
    return payload


def test_copilot_studio_plan_is_review_only_and_preserves_boundaries() -> None:
    result = build_copilot_studio_plan(**_plan())

    assert result["target"] == "microsoft_copilot_studio"
    assert result["client_id"] == "acme"
    assert result["requires_approval"] is True
    assert result["generation_status"] == "review_only"
    assert result["provider_verification"] == "not_run"
    assert result["credentials_included"] is False
    assert result["execution_started"] is False
    assert result["deployment_started"] is False
    assert result["topics"][0]["id"] == "onboarding_request"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "actions",
            [{"id": "write", "connector_id": "m365", "method": "POST", "approval_required": False}],
            "requires approval",
        ),
        ("topics", [{"id": "Bad ID", "name": "Topic"}], "safe lowercase identifier"),
        ("topics", [{"id": "topic", "name": "Topic", "instructions": "run"}], "unsupported fields"),
        (
            "actions",
            [{"id": "lookup", "connector_id": "m365", "method": "GET", "url": "https://example.test"}],
            "unsupported fields",
        ),
        ("knowledge_sources", ["token=secret"], "secret-like"),
        ("topics", [{"id": "topic", "name": "Topic"}, {"id": "topic", "name": "Again"}], "duplicate topic"),
        (
            "actions",
            [{"id": "lookup", "connector_id": "m365"}, {"id": "lookup", "connector_id": "m365"}],
            "duplicate action",
        ),
        (
            "actions",
            [{"id": "lookup", "connector_id": "m365", "method": "TRACE"}],
            "unsupported action method",
        ),
        (
            "actions",
            [{"id": "lookup", "connector_id": "m365", "approval_required": "yes"}],
            "approval_required must be boolean",
        ),
        ("topics", "not-a-list", "topics must contain"),
        ("topics", ["not-an-object"], "topics must contain objects"),
        ("topics", [{"id": "topic", "name": "Topic", "trigger_phrases": "start"}], "trigger_phrases must contain"),
        (
            "topics",
            [{"id": "topic", "name": "Topic", "trigger_phrases": ["start", "start"]}],
            "trigger_phrases must not contain duplicates",
        ),
        ("copilot_name", "", "copilot_name must be non-empty text"),
    ],
)
def test_copilot_studio_plan_rejects_unsafe_or_unreviewable_inputs(
    field: str,
    value: object,
    message: str,
) -> None:
    with pytest.raises(CopilotStudioPlanError, match=message):
        build_copilot_studio_plan(**_plan(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "topics",
            [
                {"id": "topic", "name": "One"},
                {"id": "topic", "name": "Two"},
            ],
            "duplicate topic id",
        ),
        (
            "actions",
            [
                {"id": "lookup", "connector_id": "m365"},
                {"id": "lookup", "connector_id": "m365"},
            ],
            "duplicate action id",
        ),
        (
            "actions",
            [{"id": "lookup", "connector_id": "m365", "method": "OPTIONS"}],
            "unsupported action method",
        ),
        (
            "actions",
            [{"id": "lookup", "connector_id": "m365", "approval_required": "yes"}],
            "approval_required must be boolean",
        ),
        ("topics", ["not-an-object"], "topics must contain objects"),
        ("knowledge_sources", ["duplicate", "duplicate"], "must not contain duplicates"),
        ("client_id", "", "client_id must be non-empty text"),
    ],
)
def test_copilot_studio_plan_rejects_duplicate_and_malformed_collections(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(CopilotStudioPlanError, match=message):
        build_copilot_studio_plan(**_plan(**{field: value}))


def test_copilot_studio_plan_rejects_collection_limits() -> None:
    with pytest.raises(CopilotStudioPlanError, match="topics must contain 0-32"):
        build_copilot_studio_plan(**_plan(topics=[{"id": f"topic-{index}", "name": "Topic"} for index in range(33)]))
    with pytest.raises(CopilotStudioPlanError, match="knowledge_sources must contain 0-32"):
        build_copilot_studio_plan(**_plan(knowledge_sources=[f"source-{index}" for index in range(33)]))
