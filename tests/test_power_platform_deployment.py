from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import wait_local_agent.power_platform_deployment as deployment
from wait_local_agent.power_platform_deployment import (
    PowerPlatformDeploymentError,
    build_power_platform_deployment_plan,
    build_power_platform_deployment_plan_from_payload,
    execute_power_platform_stage,
    validate_promotion_evidence,
)


def _targets() -> list[dict[str, object]]:
    return [
        {"name": "dev", "environment_url": "https://dev.crm.dynamics.com"},
        {"name": "test", "environment_url": "https://test.crm.dynamics.com"},
        {"name": "prod", "environment_url": "https://prod.crm.dynamics.com"},
    ]


def _plan(output_directory: str = "/tmp/power-platform/solution") -> dict[str, object]:
    return build_power_platform_deployment_plan(
        solution_name="onboarding_review",
        publisher_name="WAITConsulting",
        publisher_prefix="wlp",
        output_directory=output_directory,
        deployment_targets=_targets(),
    )


def test_deployment_plan_is_staged_and_metadata_only() -> None:
    plan = _plan()

    assert plan["format"] == "wait-local-agent.power-platform.deployment-plan"
    stages = cast(list[dict[str, object]], plan["stages"])
    assert [stage["id"] for stage in stages] == ["build", "dev", "test", "prod"]
    assert plan["credentials_included"] is False
    assert plan["execution_started"] is False
    assert plan["deployment_started"] is False
    stages = cast(list[dict[str, object]], plan["stages"])
    assert all(stage["deployment_started"] is False for stage in stages)
    assert cast(dict[str, object], plan["promotion_policy"])["test"] == {
        "required": True,
        "source_stage": "dev",
        "evidence": [
            "source_stage_success",
            "artifact_digest",
            "evaluation_pass",
            "governance_pass",
            "rollback_metadata",
        ],
    }


def test_promotion_evidence_is_required_and_normalized_for_test_and_prod() -> None:
    digest = "sha256:" + "a" * 64
    rollback_digest = "sha256:" + "b" * 64
    evidence = {
        "source_stage": "dev",
        "source_status": "succeeded",
        "artifact_digest": digest,
        "evaluation": {"production_readiness": "pass", "case_count": 3},
        "governance": {"status": "pass"},
        "rollback": {
            "available": True,
            "strategy": "reimport_previous_package",
            "artifact_digest": rollback_digest,
        },
    }

    normalized = validate_promotion_evidence("test", evidence)
    assert normalized == {
        "source_stage": "dev",
        "source_status": "succeeded",
        "artifact_digest": digest,
        "evaluation": {"production_readiness": "pass", "case_count": 3},
        "governance": {"status": "pass"},
        "rollback": {
            "available": True,
            "strategy": "reimport_previous_package",
            "artifact_digest": rollback_digest,
        },
    }
    with pytest.raises(PowerPlatformDeploymentError, match="requires promotion_evidence"):
        validate_promotion_evidence("test", {})
    with pytest.raises(PowerPlatformDeploymentError, match="source_stage must be test"):
        validate_promotion_evidence("prod", evidence)
    with pytest.raises(PowerPlatformDeploymentError, match="production_readiness=pass"):
        validate_promotion_evidence("test", {**evidence, "evaluation": {"production_readiness": "needs_review"}})


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ([], "contain 1-3"),
        ([{"name": "test", "environment_url": "https://test.crm.dynamics.com"}], "ordered"),
        ([{"name": "dev", "environment_url": "https://user:pass@dev.crm.dynamics.com"}], "safe HTTPS"),
    ],
)
def test_deployment_plan_rejects_unsafe_promotion_targets(
    targets: list[dict[str, object]], message: str,
) -> None:
    with pytest.raises(PowerPlatformDeploymentError, match=message):
        build_power_platform_deployment_plan(
            solution_name="onboarding_review",
            publisher_name="WAITConsulting",
            publisher_prefix="wlp",
            output_directory="/tmp/power-platform/solution",
            deployment_targets=targets,
        )


def test_execution_requires_both_explicit_gates_and_approval(settings, tmp_path: Path) -> None:
    plan = _plan(str(tmp_path / "solution"))
    blocked = execute_power_platform_stage(plan, "build", settings, approved=True)
    assert blocked["status"] == "blocked"
    assert blocked["execution_started"] is False


def test_execution_is_shell_free_bounded_and_stops_on_failure(settings, tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    plan = _plan(str(workspace / "solution"))
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    monkeypatch.setattr(deployment.shutil, "which", lambda _: "/usr/local/bin/pac")
    calls: list[tuple[list[str], Path, float]] = []

    def runner(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd, timeout))
        return subprocess.CompletedProcess(command, 1, "token=secret", "failed")

    result = execute_power_platform_stage(plan, "build", configured, approved=True, runner=runner)

    assert result["status"] == "failed"
    assert len(calls) == 1
    assert calls[0][0][0] == "/usr/local/bin/pac"
    assert calls[0][1] == workspace.resolve()
    assert calls[0][2] <= 1_800
    assert result["commands"][0]["stdout"] == "token=[redacted]"  # type: ignore[index]


def test_deployment_payload_rebuild_rejects_missing_fields_and_accepts_canonical_payload() -> None:
    plan = _plan()
    payload: dict[str, object] = {
        "solution_name": "onboarding_review",
        "publisher_name": "WAITConsulting",
        "publisher_prefix": "wlp",
        "output_directory": "/tmp/power-platform/solution",
        "deployment_targets": _targets(),
    }
    rebuilt = build_power_platform_deployment_plan_from_payload(payload)
    assert rebuilt["stages"] == plan["stages"]

    for field in (
        "solution_name",
        "publisher_name",
        "publisher_prefix",
        "output_directory",
    ):
        invalid = dict(payload)
        invalid[field] = None
        with pytest.raises(PowerPlatformDeploymentError, match=field):
            build_power_platform_deployment_plan_from_payload(invalid)
    invalid_targets = dict(payload, deployment_targets=["dev"])
    with pytest.raises(PowerPlatformDeploymentError, match="deployment_targets"):
        build_power_platform_deployment_plan_from_payload(invalid_targets)

    promotion_payload = {
        **payload,
        "stage": "test",
        "promotion_evidence": {
            "source_stage": "dev",
            "source_status": "succeeded",
            "artifact_digest": "sha256:" + "a" * 64,
            "evaluation": {"production_readiness": "pass", "case_count": 1},
            "governance": {"status": "pass"},
            "rollback": {
                "available": True,
                "strategy": "reimport_previous_package",
                "artifact_digest": "sha256:" + "b" * 64,
            },
        },
    }
    promoted = build_power_platform_deployment_plan_from_payload(promotion_payload)
    assert promoted["promotion_evidence"]["source_stage"] == "dev"  # type: ignore[index]
    with pytest.raises(PowerPlatformDeploymentError, match="requires promotion_evidence"):
        build_power_platform_deployment_plan_from_payload({**promotion_payload, "promotion_evidence": {}})


def test_execution_covers_gates_path_confinement_and_command_failures(settings, tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    plan = _plan(str(workspace / "solution"))

    assert execute_power_platform_stage(plan, "build", settings, approved=False)["status"] == "blocked"
    assert execute_power_platform_stage(
        plan, "build", replace(settings, allow_write_actions=True), approved=True
    )["status"] == "blocked"
    assert execute_power_platform_stage(
        plan,
        "build",
        replace(settings, allow_write_actions=True, allow_power_platform_deployment=False),
        approved=True,
    )["status"] == "blocked"
    assert execute_power_platform_stage(
        dict(plan, credentials_included=True), "build", configured, approved=True
    )["status"] == "blocked"

    monkeypatch.setattr(deployment.shutil, "which", lambda _: None)
    assert execute_power_platform_stage(plan, "build", configured, approved=True)["status"] == "blocked"
    monkeypatch.setattr(deployment.shutil, "which", lambda _: "/usr/local/bin/pac")
    assert execute_power_platform_stage(plan, "unknown", configured, approved=True)["status"] == "blocked"
    assert execute_power_platform_stage(
        dict(plan, stages=None), "build", configured, approved=True
    )["status"] == "blocked"
    assert execute_power_platform_stage(
        dict(plan, solution={"output_directory": str(tmp_path / "outside")}),
        "build",
        configured,
        approved=True,
    )["status"] == "blocked"
    assert execute_power_platform_stage(
        dict(plan, solution={"output_directory": str(workspace)}), "build", configured, approved=True
    )["status"] == "blocked"
    missing_workspace = replace(configured, power_platform_workspace=tmp_path / "missing")
    assert execute_power_platform_stage(plan, "build", missing_workspace, approved=True)["status"] == "blocked"

    def invalid_command_runner(command, cwd, timeout):
        return subprocess.CompletedProcess(command, 0, "", "")

    invalid_command_plan = dict(plan, stages=[{"id": "build", "commands": [["not-pac"]]}])
    assert execute_power_platform_stage(
        invalid_command_plan, "build", configured, approved=True, runner=invalid_command_runner
    )["status"] == "failed"
    malformed_command_plan = dict(plan, stages=[{"id": "build", "commands": ["pac"]}])
    assert execute_power_platform_stage(
        malformed_command_plan, "build", configured, approved=True, runner=invalid_command_runner
    )["status"] == "failed"

    def timeout_runner(command, cwd, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    assert execute_power_platform_stage(
        plan, "build", configured, approved=True, runner=timeout_runner
    )["status"] == "failed"

    def os_error_runner(command, cwd, timeout):
        raise OSError("pac unavailable")

    assert execute_power_platform_stage(
        plan, "build", configured, approved=True, runner=os_error_runner
    )["status"] == "failed"

    def success_runner(command, cwd, timeout):
        return subprocess.CompletedProcess(command, 0, "ok", "")

    succeeded = execute_power_platform_stage(plan, "build", configured, approved=True, runner=success_runner)
    assert succeeded["status"] == "succeeded"


def test_deployment_shape_guards_cover_target_and_execution_path_edges(settings, tmp_path: Path) -> None:
    with pytest.raises(PowerPlatformDeploymentError):
        build_power_platform_deployment_plan(
            solution_name="bad name",
            publisher_name="WAIT",
            publisher_prefix="wlp",
            output_directory="/tmp/solution",
            deployment_targets=_targets(),
        )
    for targets in (
        ["dev"],
        [{"name": "test", "environment_url": "https://test.example"}],
        [{"name": "dev", "environment_url": "https://user:pass@example"}],
        [{"name": "dev", "environment_url": "https://example?x=1"}],
    ):
        with pytest.raises(PowerPlatformDeploymentError):
            deployment._targets(targets)  # type: ignore[arg-type]
    stage_cases: tuple[tuple[str, dict[str, object]], ...] = (
        ("missing", {}),
        ("build", {"stages": "bad"}),
        ("prod", {"stages": []}),
    )
    for stage_id, plan in stage_cases:
        with pytest.raises(PowerPlatformDeploymentError):
            deployment._stage(plan, stage_id)
    invalid_plans: tuple[dict[str, object], ...] = (
        {},
        {"solution": {}},
        {"solution": {"output_directory": ""}},
    )
    for invalid_plan in invalid_plans:
        with pytest.raises(PowerPlatformDeploymentError):
            deployment._execution_paths(invalid_plan, settings)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    confined = replace(settings, power_platform_workspace=workspace)
    with pytest.raises(PowerPlatformDeploymentError, match="already exist"):
        deployment._execution_paths(
            {"solution": {"output_directory": str(workspace / "missing" / "child")}}, confined
        )
