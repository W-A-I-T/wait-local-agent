from __future__ import annotations

import stat
import subprocess
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import wait_local_agent.power_platform_deployment as deployment
from wait_local_agent.power_platform_deployment import (
    PowerPlatformDeploymentError,
    build_power_platform_deployment_plan,
    build_power_platform_deployment_plan_from_payload,
    execute_power_platform_rollback,
    execute_power_platform_stage,
    validate_power_platform_solution_package,
    validate_promotion_evidence,
    validate_promotion_source,
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


def _rollback_evidence(digest: str) -> dict[str, object]:
    return {
        "available": True,
        "strategy": "reimport_previous_package",
        "artifact_digest": digest,
    }


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
        "source_approval_request_id": 1,
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
        "source_approval_request_id": 1,
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
    ("stage", "evidence", "message"),
    [
        ("unknown", {}, "stage must be"),
        ("build", {"unexpected": True}, "does not accept"),
        ("test", [], "requires promotion_evidence"),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "pending",
            },
            "source_status must be succeeded",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "not-a-digest",
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "pass"},
                "rollback": {
                    "available": True,
                    "strategy": "restore",
                    "artifact_digest": "sha256:" + "b" * 64,
                },
            },
            "artifact_digest must be",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass", "case_count": "one"},
            },
            "case_count must be",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "needs_review"},
            },
            "governance must have",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "pass"},
                "rollback": {"available": False},
            },
            "rollback.available must be true",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "pass"},
                "rollback": {"available": True, "strategy": ""},
            },
            "rollback.strategy is required",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "pass"},
                "rollback": {
                    "available": True,
                    "strategy": "restore",
                    "artifact_digest": "not-a-digest",
                },
            },
            "rollback.artifact_digest must be",
        ),
        (
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": 1,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "pass"},
                "rollback": {
                    "available": True,
                    "strategy": "restore",
                    "artifact_digest": "sha256:" + "b" * 64,
                },
                "extra": True,
            },
            "unsupported fields",
        ),
    ],
)
def test_promotion_evidence_rejects_unsafe_or_incomplete_values(stage, evidence, message) -> None:
    with pytest.raises(PowerPlatformDeploymentError, match=message):
        validate_promotion_evidence(stage, evidence)


@pytest.mark.parametrize("source_id", [None, 0, -1, True, "1"])
def test_promotion_evidence_requires_positive_source_approval_id(source_id) -> None:
    with pytest.raises(PowerPlatformDeploymentError, match="source_approval_request_id"):
        validate_promotion_evidence(
            "test",
            {
                "source_stage": "dev",
                "source_status": "succeeded",
                "source_approval_request_id": source_id,
                "artifact_digest": "sha256:" + "a" * 64,
                "evaluation": {"production_readiness": "pass"},
                "governance": {"status": "pass"},
                "rollback": {
                    "available": True,
                    "strategy": "restore",
                    "artifact_digest": "sha256:" + "b" * 64,
                },
            },
        )


def test_promotion_source_must_match_persisted_successful_stage() -> None:
    digest = "sha256:" + "a" * 64
    evidence = {"source_stage": "dev", "source_approval_request_id": 7, "artifact_digest": digest}
    current = {
        "client_id": "acme",
        "solution_name": "onboarding_review",
        "publisher_name": "WAITConsulting",
        "publisher_prefix": "wlp",
        "deployment_targets": _targets(),
    }
    source = {
        "id": 7,
        "client_id": "acme",
        "action_type": "power_platform.solution_stage",
        "status": "approved",
        "execution_status": "succeeded",
        "payload": {**current, "stage": "dev"},
        "execution_result": {"status": "succeeded", "artifact_digest": digest},
    }

    validate_promotion_source("test", evidence, source_approval=source, current_payload=current)
    validate_promotion_source("dev", {}, source_approval=None, current_payload=current)

    invalid_sources = [
        (None, "was not found"),
        ({**source, "id": 8}, "does not match"),
        ({**source, "client_id": "beta"}, "outside the tenant"),
        ({**source, "action_type": "other"}, "wrong action"),
        ({**source, "status": "pending"}, "not approved"),
        ({**source, "execution_status": "failed"}, "has not succeeded"),
        ({**source, "payload": None}, "payload is invalid"),
        ({**source, "payload": {**current, "stage": "test"}}, "must be dev"),
        ({**source, "payload": {**current, "stage": "dev", "solution_name": "other"}}, "does not match"),
        ({**source, "execution_result": {"status": "failed"}}, "result is not succeeded"),
        (
            {**source, "execution_result": {"status": "succeeded", "artifact_digest": "sha256:" + "b" * 64}},
            "does not match",
        ),
    ]
    for invalid_source, message in invalid_sources:
        with pytest.raises(PowerPlatformDeploymentError, match=message):
            validate_promotion_source("test", evidence, source_approval=invalid_source, current_payload=current)


@pytest.mark.parametrize(
    ("targets", "message"),
    [
        ([], "contain 1-3"),
        ([{"name": "test", "environment_url": "https://test.crm.dynamics.com"}], "ordered"),
        ([{"name": "dev", "environment_url": "https://user:pass@dev.crm.dynamics.com"}], "safe HTTPS"),
        ([{"name": "dev", "environment_url": "https://dev.crm.dynamics.com\n"}], "safe HTTPS"),
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
    with pytest.raises(PowerPlatformDeploymentError, match="must be an array"):
        build_power_platform_deployment_plan(
            solution_name="onboarding_review",
            publisher_name="WAITConsulting",
            publisher_prefix="wlp",
            output_directory="/tmp/power-platform/solution",
            deployment_targets="not-an-array",  # type: ignore[arg-type]
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
            "source_approval_request_id": 1,
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
    dev_plan = build_power_platform_deployment_plan_from_payload({**payload, "stage": "dev"})
    assert "promotion_evidence" not in dev_plan


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
        dict(plan, stages=[{"id": "other"}]), "build", configured, approved=True
    )["status"] == "blocked"
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
    missing_workspace_plan = _plan(str(tmp_path / "missing" / "solution"))
    assert execute_power_platform_stage(
        missing_workspace_plan, "build", missing_workspace, approved=True
    )["status"] == "blocked"

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
        artifact = cwd / "solution" / "onboarding_review.zip"
        artifact.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(artifact, "w") as archive:
            archive.writestr("solution.xml", "<ImportExportXml />")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    succeeded = execute_power_platform_stage(plan, "build", configured, approved=True, runner=success_runner)
    assert succeeded["status"] == "succeeded"
    assert succeeded["deployment_started"] is False

    imported = execute_power_platform_stage(plan, "dev", configured, approved=True, runner=success_runner)
    assert imported["status"] == "succeeded"
    assert imported["deployment_started"] is True


def test_execution_requires_verifiable_artifact_and_uses_shell_free_runner(
    settings, tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    plan = _plan(str(workspace / "solution"))
    monkeypatch.setattr(deployment.shutil, "which", lambda _: "/usr/local/bin/pac")
    result = execute_power_platform_stage(
        plan,
        "build",
        configured,
        approved=True,
        runner=lambda command, cwd, timeout: subprocess.CompletedProcess(command, 0, "ok", ""),
    )
    assert result["status"] == "failed"
    assert "verifiable solution artifact" in str(result["message"])


def test_rollback_reimports_only_a_verified_prior_package(settings, tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    previous = workspace / "previous.zip"
    with zipfile.ZipFile(previous, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    digest = validate_power_platform_solution_package(previous, workspace)
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    plan = _plan(str(workspace / "solution"))
    monkeypatch.setattr(deployment.shutil, "which", lambda _: "/usr/local/bin/pac")
    calls: list[tuple[list[str], Path, float]] = []

    def runner(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
        calls.append((command, cwd, timeout))
        return subprocess.CompletedProcess(command, 0, "rollback ok", "")

    result = execute_power_platform_rollback(
        plan,
        "test",
        configured,
        rollback_artifact_path=previous,
        rollback_evidence=_rollback_evidence(digest),
        approved=True,
        runner=runner,
    )

    assert result["status"] == "succeeded"
    assert result["artifact_digest"] == digest
    assert result["rollback_started"] is True
    assert calls[0][0] == [
        "/usr/local/bin/pac",
        "solution",
        "import",
        "--path",
        str(previous.resolve()),
        "--environment",
        "https://test.crm.dynamics.com",
    ]
    assert calls[0][1] == workspace.resolve()
    assert calls[0][2] <= 1_800
    assert result["commands"][0]["command"] == [  # type: ignore[index]
        "pac",
        "solution",
        "import",
        "--path",
        "previous.zip",
        "--environment",
        "https://test.crm.dynamics.com",
    ]


@pytest.mark.parametrize(
    ("stage", "evidence", "artifact", "message"),
    [
        ("build", {}, "previous.zip", "target must be"),
        ("test", {"available": False}, "previous.zip", "not available"),
        (
            "test",
            {"available": True, "strategy": "custom", "artifact_digest": "sha256:" + "a" * 64},
            "previous.zip",
            "unsupported",
        ),
        ("test", _rollback_evidence("sha256:" + "a" * 64), "missing.zip", "missing"),
    ],
)
def test_rollback_fails_closed_before_pac_for_unsafe_or_unavailable_inputs(
    settings, tmp_path: Path, stage, evidence, artifact, message
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    result = execute_power_platform_rollback(
        _plan(str(workspace / "solution")),
        stage,
        configured,
        rollback_artifact_path=workspace / artifact,
        rollback_evidence=evidence,
        approved=True,
        runner=lambda *_args: (_ for _ in ()).throw(AssertionError("PAC must not run")),
    )
    assert result["status"] == "blocked"
    assert message in str(result["message"])


def test_rollback_rejects_digest_mismatch_and_reports_pac_failure(settings, tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    previous = workspace / "previous.zip"
    with zipfile.ZipFile(previous, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    plan = _plan(str(workspace / "solution"))
    monkeypatch.setattr(deployment.shutil, "which", lambda _: "/usr/local/bin/pac")
    mismatch = execute_power_platform_rollback(
        plan,
        "dev",
        configured,
        rollback_artifact_path=previous,
        rollback_evidence=_rollback_evidence("sha256:" + "a" * 64),
        approved=True,
        runner=lambda *_args: (_ for _ in ()).throw(AssertionError("PAC must not run")),
    )
    assert mismatch["status"] == "failed"
    assert "digest does not match" in str(mismatch["message"])

    def failed_runner(command, cwd, timeout):
        return subprocess.CompletedProcess(command, 7, "token=secret", "provider denied")

    digest = validate_power_platform_solution_package(previous, workspace)
    failed = execute_power_platform_rollback(
        plan,
        "dev",
        configured,
        rollback_artifact_path=previous,
        rollback_evidence=_rollback_evidence(digest),
        approved=True,
        runner=failed_runner,
    )
    assert failed["status"] == "failed"
    assert failed["rollback_started"] is True
    assert failed["artifact_digest"] == digest
    assert failed["commands"][0]["stdout"] == "token=[redacted]"  # type: ignore[index]


@pytest.mark.parametrize(
    ("settings_update", "approved", "plan_update", "evidence", "message"),
    [
        ({}, False, {}, _rollback_evidence("sha256:" + "a" * 64), "completed approval"),
        ({"allow_write_actions": False}, True, {}, _rollback_evidence("sha256:" + "a" * 64), "ALLOW_WRITE_ACTIONS"),
        (
            {"allow_power_platform_deployment": False},
            True,
            {},
            _rollback_evidence("sha256:" + "a" * 64),
            "ALLOW_POWER_PLATFORM_DEPLOYMENT",
        ),
        ({}, True, {"credentials_included": True}, _rollback_evidence("sha256:" + "a" * 64), "credentials"),
        ({}, True, {}, {}, "not available"),
        ({}, True, {}, {"available": True, "strategy": "reimport_previous_package"}, "artifact_digest"),
    ],
)
def test_rollback_enforces_approval_flags_and_evidence_before_file_or_pac(
    settings, tmp_path: Path, settings_update, approved, plan_update, evidence, message
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    configured = replace(
        settings,
        **{
            "allow_write_actions": True,
            "allow_power_platform_deployment": True,
            "power_platform_workspace": workspace,
            **settings_update,
        },
    )
    plan = {**_plan(str(workspace / "solution")), **plan_update}
    result = execute_power_platform_rollback(
        plan,
        "dev",
        configured,
        rollback_artifact_path=workspace / "missing.zip",
        rollback_evidence=evidence,
        approved=approved,
        runner=lambda *_args: (_ for _ in ()).throw(AssertionError("PAC must not run")),
    )
    assert result["status"] == "blocked"
    assert message in str(result["message"])


def test_rollback_reports_missing_pac_timeout_and_start_failure(settings, tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    previous = workspace / "previous.zip"
    with zipfile.ZipFile(previous, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    digest = validate_power_platform_solution_package(previous, workspace)
    configured = replace(
        settings,
        allow_write_actions=True,
        allow_power_platform_deployment=True,
        power_platform_workspace=workspace,
    )
    plan = _plan(str(workspace / "solution"))
    evidence = _rollback_evidence(digest)
    monkeypatch.setattr(deployment.shutil, "which", lambda _: None)
    missing = execute_power_platform_rollback(
        plan,
        "dev",
        configured,
        rollback_artifact_path=previous,
        rollback_evidence=evidence,
        approved=True,
    )
    assert missing["status"] == "blocked"
    assert "not available" in str(missing["message"])

    monkeypatch.setattr(deployment.shutil, "which", lambda _: "/usr/local/bin/pac")

    def timeout_runner(command, cwd, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    timed_out = execute_power_platform_rollback(
        plan,
        "dev",
        configured,
        rollback_artifact_path=previous,
        rollback_evidence=evidence,
        approved=True,
        runner=timeout_runner,
    )
    assert timed_out["status"] == "failed"
    assert "timed out" in str(timed_out["message"])

    def os_error_runner(command, cwd, timeout):
        raise OSError("pac unavailable")

    not_started = execute_power_platform_rollback(
        plan,
        "dev",
        configured,
        rollback_artifact_path=previous,
        rollback_evidence=evidence,
        approved=True,
        runner=os_error_runner,
    )
    assert not_started["status"] == "failed"
    assert "could not be started" in str(not_started["message"])

    calls: list[dict[str, object]] = []

    def fake_run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr(deployment.subprocess, "run", fake_run)
    completed = deployment._run_command(["pac", "solution", "check"], workspace, 5.0)
    assert completed.returncode == 0
    assert calls[0]["shell"] is False


def test_artifact_digest_is_bounded_and_confined(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "solution"
    output.mkdir(parents=True)
    plan = _plan(str(output))
    assert deployment._artifact_digest(dict(plan, solution=None), workspace, output) is None
    assert deployment._artifact_digest(
        dict(plan, solution={"name": ""}), workspace, output
    ) is None
    assert deployment._artifact_digest(plan, workspace, workspace) is None
    artifact = output / "onboarding_review.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
    digest = deployment._artifact_digest(plan, workspace, output)
    assert isinstance(digest, str) and digest.startswith("sha256:")
    monkeypatch.setattr(deployment, "MAX_ARTIFACT_BYTES", 1)
    assert deployment._artifact_digest(plan, workspace, output) is None

    monkeypatch.setattr(deployment, "MAX_ARTIFACT_BYTES", 500_000_000)
    original_open = Path.open

    def failing_open(path, *args, **kwargs):
        if path == artifact:
            raise OSError("artifact disappeared")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing_open)
    assert deployment._artifact_digest(plan, workspace, output) is None


def test_solution_package_validation_rejects_invalid_archive_members(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "solution"
    output.mkdir(parents=True)
    artifact = output / "onboarding_review.zip"

    artifact.write_bytes(b"not a zip")
    with pytest.raises(PowerPlatformDeploymentError, match="valid ZIP"):
        validate_power_platform_solution_package(artifact, workspace)

    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    with pytest.raises(PowerPlatformDeploymentError, match="traversal"):
        validate_power_platform_solution_package(artifact, workspace)

    symlink = zipfile.ZipInfo("linked.txt")
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr(symlink, "outside")
    with pytest.raises(PowerPlatformDeploymentError, match="symlink"):
        validate_power_platform_solution_package(artifact, workspace)


def test_solution_package_validation_returns_digest_for_safe_archive(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    output = workspace / "solution"
    output.mkdir(parents=True)
    artifact = output / "onboarding_review.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("solution.xml", "<ImportExportXml />")
        archive.writestr("customizations.xml", "<ImportExportXml />")

    digest = validate_power_platform_solution_package(artifact, workspace)
    assert digest.startswith("sha256:")


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
