from __future__ import annotations

from typing import Any

import pytest

from wait_local_agent.delivery_plan import (
    DeliveryPlanError,
    build_consultant_artifact_review_package,
    build_consultant_delivery_bundle,
    build_consultant_delivery_plan,
)


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
    assert result["review_package_generated"] is True
    assert result["review_package"]["package_status"] == "review_only"
    assert result["review_package"]["credentials_included"] is False
    assert result["review_package"]["artifacts"][0]["credentials_included"] is False
    assert result["review_package_digest"].startswith("sha256:")
    assert result["delivery_bundle_generated"] is True
    assert result["delivery_bundle_status"] == "review_only"
    assert result["delivery_bundle"]["manifest"]["deployable"] is False
    assert result["delivery_bundle_digest"].startswith("sha256:")
    assert result["deployment_package_generated"] is False
    assert result["deployment_package_status"] == "not_generated"
    assert result["execution_started"] is False
    assert result["deployment_started"] is False


def test_delivery_plan_review_package_is_deterministic_and_redacted() -> None:
    kwargs: dict[str, Any] = {
        "client_id": "acme",
        "architecture": _architecture(),
        "evaluation": {"production_readiness": "pass", "case_count": 1},
        "governance": {"client_id": "acme", "status": "pass"},
        "deployment_targets": ["Teams"],
        "connector_artifacts": [
            {
                "connector_id": "m365",
                "credentials_included": False,
                "client_secret": "do-not-export",
                "notes": "token=do-not-export",
            }
        ],
    }

    first = build_consultant_delivery_plan(**kwargs)
    second = build_consultant_delivery_plan(**kwargs)

    assert first["review_package_digest"] == second["review_package_digest"]
    artifact = first["review_package"]["artifacts"][0]
    assert artifact["client_secret"] == "[redacted]"
    assert artifact["notes"] == "token=[redacted]"


def test_delivery_bundle_is_deterministic_redacted_and_explicitly_non_deployable() -> None:
    review_package, _ = build_consultant_artifact_review_package(
        client_id="acme",
        artifacts=[
            {
                "format": "wait-local-agent.power-automate-flow-plan",
                "client_id": "acme",
                "credentials_included": False,
                "secret_value": "do-not-export",
                "execution_started": False,
                "deployment_started": False,
            }
        ],
    )
    kwargs: dict[str, Any] = {
        "client_id": "acme",
        "architecture": _architecture(),
        "evaluation": {"production_readiness": "pass", "case_count": 4},
        "governance": {"client_id": "acme", "status": "pass"},
        "deployment_targets": ["Power Automate"],
        "review_package": review_package,
    }

    first, first_digest = build_consultant_delivery_bundle(**kwargs)
    second, second_digest = build_consultant_delivery_bundle(**kwargs)

    assert first is not None
    assert second is not None
    assert first_digest == second_digest
    assert first == second
    assert first["manifest"]["bundle_status"] == "review_only"
    assert first["manifest"]["deployable"] is False
    assert first["manifest"]["deployment_started"] is False
    assert first["files"][0]["path"] == "architecture.json"
    artifact_file = first["files"][-1]
    assert artifact_file["content"]["secret_value"] == "[redacted]"


def test_delivery_bundle_requires_a_review_only_tenant_scoped_package() -> None:
    with pytest.raises(DeliveryPlanError, match="outside the requested tenant"):
        build_consultant_delivery_bundle(
            client_id="acme",
            architecture=_architecture(),
            evaluation={"production_readiness": "pass"},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Power Apps"],
            review_package={"client_id": "beta", "package_status": "review_only", "artifacts": []},
        )
    with pytest.raises(DeliveryPlanError, match="review_only"):
        build_consultant_delivery_bundle(
            client_id="acme",
            architecture=_architecture(),
            evaluation={"production_readiness": "pass"},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Power Apps"],
            review_package={"client_id": "acme", "package_status": "deployable", "artifacts": []},
        )


def test_delivery_bundle_rejects_foreign_evidence_and_unsafe_package_state() -> None:
    base: dict[str, Any] = {
        "client_id": "acme",
        "architecture": _architecture(),
        "evaluation": {"production_readiness": "pass"},
        "governance": {"client_id": "acme", "status": "pass"},
        "deployment_targets": ["Power Apps"],
        "review_package": {"client_id": "acme", "package_status": "review_only", "artifacts": []},
    }
    for field, message in (
        ("architecture", "architecture is outside"),
        ("evaluation", "evaluation is outside"),
        ("governance", "governance is outside"),
    ):
        invalid = dict(base)
        invalid[field] = {"client_id": "beta"}
        with pytest.raises(DeliveryPlanError, match=message):
            build_consultant_delivery_bundle(**invalid)

    for package, message in (
        (
            {"client_id": "acme", "package_status": "review_only", "credentials_included": True, "artifacts": []},
            "credentials",
        ),
        (
            {"client_id": "acme", "package_status": "review_only", "deployment_started": True, "artifacts": []},
            "deployment started",
        ),
        ({"client_id": "acme", "package_status": "review_only", "artifacts": {}}, "artifacts must be an array"),
        ({"client_id": "acme", "package_status": "review_only", "artifacts": [object()]}, "JSON-compatible"),
    ):
        with pytest.raises(DeliveryPlanError, match=message):
            build_consultant_delivery_bundle(**{**base, "review_package": package})


def test_delivery_bundle_enforces_bounded_source_and_digest_sizes() -> None:
    base: dict[str, Any] = {
        "client_id": "acme",
        "architecture": _architecture(),
        "evaluation": {"production_readiness": "pass"},
        "governance": {"client_id": "acme", "status": "pass"},
        "deployment_targets": ["Power Apps"],
    }
    with pytest.raises(DeliveryPlanError, match="at most 32 files"):
        build_consultant_delivery_bundle(
            **base,
            review_package={
                "client_id": "acme",
                "package_status": "review_only",
                "artifacts": [{}] * 30,
            },
        )
    with pytest.raises(DeliveryPlanError, match="delivery bundle may be at most"):
        oversized_source = dict(base)
        oversized_source["architecture"] = {**_architecture(), "large": "x" * 260_000}
        build_consultant_delivery_bundle(
            **oversized_source,
            review_package={"client_id": "acme", "package_status": "review_only", "artifacts": []},
        )
    with pytest.raises(DeliveryPlanError, match="review package exceeds"):
        build_consultant_delivery_bundle(
            **base,
            review_package={
                "client_id": "acme",
                "package_status": "review_only",
                "artifacts": [],
                "large": "x" * 260_000,
            },
        )


def test_delivery_plan_rejects_non_json_review_artifacts() -> None:
    with pytest.raises(DeliveryPlanError, match="JSON-compatible"):
        build_consultant_delivery_plan(
            client_id="acme",
            architecture=_architecture(),
            evaluation={"production_readiness": "pass", "case_count": 1},
            governance={"client_id": "acme", "status": "pass"},
            deployment_targets=["Teams"],
            connector_artifacts=[{"connector_id": "m365", "value": object()}],
        )


def test_review_package_rejects_foreign_or_started_artifacts() -> None:
    with pytest.raises(DeliveryPlanError, match="outside the requested tenant"):
        build_consultant_artifact_review_package(
            client_id="acme",
            artifacts=[{"client_id": "beta", "format": "review"}],
        )
    with pytest.raises(DeliveryPlanError, match="execution or deployment"):
        build_consultant_artifact_review_package(
            client_id="acme",
            artifacts=[{"client_id": "acme", "deployment_started": True}],
        )


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
