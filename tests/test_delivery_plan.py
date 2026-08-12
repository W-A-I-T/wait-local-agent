from __future__ import annotations

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
