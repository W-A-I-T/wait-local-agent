from __future__ import annotations

from typing import Any

import pytest

from wait_local_agent.delivery_plan import DeliveryPlanError, build_consultant_delivery_plan


def _architecture() -> dict[str, object]:
    return {
        "client_id": "acme",
        "readiness": "ready",
        "approval_policy": {"assign_license": "IT"},
        "components": [
            {"kind": "agent", "id": "supervisor"},
            {"kind": "workflow", "id": "onboarding"},
            {"kind": "knowledge_source", "id": "handbook"},
        ],
    }


def test_delivery_plan_composes_evidence_and_requires_production_approval() -> None:
    result = build_consultant_delivery_plan(
        client_id="acme",
        architecture=_architecture(),
        evaluation={"production_readiness": "pass", "case_count": 48},
        governance={"client_id": "acme", "status": "pass"},
        deployment_targets=["Teams", "Microsoft 365 Copilot"],
        connector_artifacts=[{"connector_id": "m365", "credentials_included": False}],
    )

    assert result["format"] == "wait-local-agent.consultant-delivery-plan"
    assert result["production_readiness"] == "pass"
    assert result["summary"]["agents_designed"] == 1
    assert result["summary"]["test_scenarios"] == 48
    assert result["production_deployment_requires_approval"] is True
    assert result["execution_started"] is False
    assert result["deployment_started"] is False


def test_delivery_plan_reports_unready_evidence_and_rejects_foreign_architecture() -> None:
    result = build_consultant_delivery_plan(
        client_id="acme",
        architecture={**_architecture(), "readiness": "needs_review"},
        evaluation={"production_readiness": "needs_review", "case_count": 1},
        governance={"client_id": "acme", "status": "needs_review"},
        deployment_targets=["Teams"],
    )
    assert result["production_readiness"] == "needs_review"
    assert result["checks"] == {
        "architecture": False,
        "evaluation": False,
        "governance": False,
        "credentials": True,
    }
    with pytest.raises(DeliveryPlanError, match="outside the requested tenant"):
        build_consultant_delivery_plan(
            client_id="acme",
            architecture={**_architecture(), "client_id": "beta"},
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
        )


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("empty_targets", "deployment_targets must contain"),
        ("duplicate_targets", "must not contain duplicates"),
        ("connector_object", "must contain objects"),
        ("components_type", "components must be an array"),
        ("approval_policy_type", "approval_policy must be an object"),
        ("negative_cases", "case_count must be a non-negative integer"),
        ("boolean_cases", "case_count must be a non-negative integer"),
    ],
)
def test_delivery_plan_rejects_unbounded_or_malformed_evidence(case, message) -> None:
    architecture = _architecture()
    evaluation = {"production_readiness": "pass", "case_count": 1}
    kwargs: dict[str, Any] = {
        "client_id": "acme",
        "architecture": architecture,
        "evaluation": evaluation,
        "governance": {"client_id": "acme", "status": "pass"},
        "deployment_targets": ["Teams"],
        "connector_artifacts": [],
    }
    if case == "components_type":
        architecture["components"] = "agent"
    elif case == "approval_policy_type":
        architecture["approval_policy"] = []
    elif case == "negative_cases":
        evaluation["case_count"] = -1
    elif case == "boolean_cases":
        evaluation["case_count"] = True
    elif case == "connector_object":
        kwargs["connector_artifacts"] = [object()]
    elif case == "empty_targets":
        kwargs["deployment_targets"] = []
    elif case == "duplicate_targets":
        kwargs["deployment_targets"] = ["Teams", "Teams"]
    with pytest.raises(DeliveryPlanError, match=message):
        build_consultant_delivery_plan(**kwargs)


def test_delivery_plan_rejects_governance_and_connector_limits() -> None:
    with pytest.raises(DeliveryPlanError, match="governance is outside"):
        build_consultant_delivery_plan(
            client_id="acme",
            architecture=_architecture(),
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "beta", "status": "pass"},
            deployment_targets=["Teams"],
        )
    with pytest.raises(DeliveryPlanError, match="at most 16"):
        build_consultant_delivery_plan(
            client_id="acme",
            architecture=_architecture(),
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
            connector_artifacts=[{}] * 17,
        )
    for value, message in (("", "non-empty"), ("bad\nvalue", "control")):
        with pytest.raises(DeliveryPlanError, match=message):
            build_consultant_delivery_plan(
                client_id="acme",
                architecture=_architecture(),
                evaluation={"production_readiness": "pass", "case_count": 1},
                governance={"client_id": "acme", "status": "pass"},
                deployment_targets=[value],
            )
