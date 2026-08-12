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
    execute_power_platform_stage,
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
