"""Approval-backed, staged Power Platform solution deployment.

Planning remains deterministic and side-effect free. Execution is deliberately
separate: it accepts only a stored approval payload, invokes a fixed ``pac``
command set without a shell, confines writes to the configured workspace, and
returns redacted bounded output.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import subprocess  # nosec B404 - argv is fixed and shell execution is disabled below
import zipfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from wait_local_agent.config import Settings
from wait_local_agent.power_platform import OpenApiDefinitionError, build_solution_command_plan
from wait_local_agent.reports.renderers import redact_text

MAX_DEPLOYMENT_TARGETS = 3
MAX_STAGE_OUTPUT = 4_000
MAX_COMMAND_TIMEOUT_SECONDS = 1_800.0
MAX_ARTIFACT_BYTES = 500_000_000
MAX_ARTIFACT_ENTRIES = 4_096
_TARGET_NAMES = ("dev", "test", "prod")
_PROMOTION_SOURCE_STAGES: dict[str, str | None] = {
    "build": None,
    "dev": None,
    "test": "dev",
    "prod": "test",
}
_SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class PowerPlatformDeploymentError(ValueError):
    """Raised when a Power Platform deployment request is unsafe or malformed."""


CommandRunner = Callable[[list[str], Path, float], subprocess.CompletedProcess[str]]


def build_power_platform_deployment_plan(
    *,
    solution_name: str,
    publisher_name: str,
    publisher_prefix: str,
    output_directory: str,
    deployment_targets: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Build a staged plan without invoking ``pac`` or touching the filesystem."""

    try:
        base = build_solution_command_plan(
            solution_name,
            publisher_name,
            publisher_prefix,
            output_directory,
        )
    except OpenApiDefinitionError as exc:
        raise PowerPlatformDeploymentError(str(exc)) from exc
    targets = _targets(deployment_targets)
    commands = cast(list[list[str]], base["commands"])
    zipfile = f"{output_directory.rstrip('/')}/{base['solution_name']}.zip"
    stages: list[dict[str, object]] = [
        {
            "id": "build",
            "name": "Build and solution checker",
            "commands": commands,
            "approval_required": True,
            "deployment_started": False,
            "promotion_gate": {"required": False, "source_stage": None},
        }
    ]
    for target in targets:
        name = cast(str, target["name"])
        stages.append(
            {
                "id": name,
                "name": f"Import solution into {name.upper()}",
                "commands": [[
                    "pac",
                    "solution",
                    "import",
                    "--path",
                    zipfile,
                    "--environment",
                    cast(str, target["environment_url"]),
                ]],
                "approval_required": True,
                "deployment_started": False,
                "promotion_gate": {
                    "required": name in {"test", "prod"},
                    "source_stage": _PROMOTION_SOURCE_STAGES[name],
                },
            }
        )
    return {
        "format": "wait-local-agent.power-platform.deployment-plan",
        "format_version": 1,
        "solution": {
            "name": base["solution_name"],
            "publisher_name": base["publisher_name"],
            "publisher_prefix": base["publisher_prefix"],
            "output_directory": base["output_directory"],
        },
        "deployment_targets": targets,
        "stages": stages,
        "credentials_included": False,
        "approval_required_for_every_stage": True,
        "promotion_policy": {
            stage: {
                "required": source_stage is not None,
                "source_stage": source_stage,
                "evidence": (
                    [
                        "source_stage_success",
                        "artifact_digest",
                        "evaluation_pass",
                        "governance_pass",
                        "rollback_metadata",
                    ]
                    if source_stage is not None
                    else []
                ),
            }
            for stage, source_stage in _PROMOTION_SOURCE_STAGES.items()
        },
        "execution_started": False,
        "deployment_started": False,
    }


def build_power_platform_deployment_plan_from_payload(
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Rebuild a canonical plan from the minimal approval payload."""

    required_text = ("solution_name", "publisher_name", "publisher_prefix", "output_directory")
    values: dict[str, str] = {}
    for field in required_text:
        value = payload.get(field)
        if not isinstance(value, str):
            raise PowerPlatformDeploymentError(f"approval payload field {field} is invalid")
        values[field] = value
    targets = payload.get("deployment_targets")
    if not isinstance(targets, list) or any(not isinstance(item, Mapping) for item in targets):
        raise PowerPlatformDeploymentError("approval payload deployment_targets is invalid")
    plan = build_power_platform_deployment_plan(
        **values,
        deployment_targets=cast(Sequence[Mapping[str, object]], targets),
    )
    stage = payload.get("stage")
    if isinstance(stage, str):
        evidence = validate_promotion_evidence(stage, payload.get("promotion_evidence", {}))
        if evidence:
            plan["promotion_evidence"] = evidence
    return plan


def validate_promotion_evidence(stage_id: str, evidence: object) -> dict[str, object]:
    """Validate evidence required before a solution can be promoted.

    Build and DEV approvals establish the initial artifact and environment
    boundary. TEST and PROD require explicit evidence from the immediately
    preceding stage; a declaration without that evidence is not a promotion.
    """

    source_stage = _PROMOTION_SOURCE_STAGES.get(stage_id)
    if stage_id not in _PROMOTION_SOURCE_STAGES:
        raise PowerPlatformDeploymentError("stage must be build, dev, test, or prod")
    if source_stage is None:
        if evidence not in ({}, None):
            raise PowerPlatformDeploymentError(f"{stage_id} does not accept promotion_evidence")
        return {}
    if not isinstance(evidence, Mapping):
        raise PowerPlatformDeploymentError(f"{stage_id} requires promotion_evidence")
    raw = dict(evidence)
    if not raw:
        raise PowerPlatformDeploymentError(f"{stage_id} requires promotion_evidence")
    _reject_keys(
        raw,
        {
            "source_stage",
            "source_status",
            "source_approval_request_id",
            "artifact_digest",
            "evaluation",
            "governance",
            "rollback",
        },
        "promotion_evidence",
    )
    if raw.get("source_stage") != source_stage:
        raise PowerPlatformDeploymentError(f"promotion_evidence.source_stage must be {source_stage}")
    if raw.get("source_status") != "succeeded":
        raise PowerPlatformDeploymentError("promotion_evidence.source_status must be succeeded")
    source_approval_request_id = raw.get("source_approval_request_id")
    if (
        isinstance(source_approval_request_id, bool)
        or not isinstance(source_approval_request_id, int)
        or source_approval_request_id <= 0
    ):
        raise PowerPlatformDeploymentError(
            "promotion_evidence.source_approval_request_id must be a positive integer"
        )
    artifact_digest = _digest(raw.get("artifact_digest"), "promotion_evidence.artifact_digest")

    evaluation = raw.get("evaluation")
    if not isinstance(evaluation, Mapping) or evaluation.get("production_readiness") != "pass":
        raise PowerPlatformDeploymentError("promotion_evidence.evaluation must have production_readiness=pass")
    case_count = evaluation.get("case_count", 0)
    if isinstance(case_count, bool) or not isinstance(case_count, int) or not 0 <= case_count <= 100_000:
        raise PowerPlatformDeploymentError("promotion_evidence.evaluation.case_count must be a bounded integer")

    governance = raw.get("governance")
    if not isinstance(governance, Mapping) or governance.get("status") != "pass":
        raise PowerPlatformDeploymentError("promotion_evidence.governance must have status=pass")

    rollback = raw.get("rollback")
    if not isinstance(rollback, Mapping) or rollback.get("available") is not True:
        raise PowerPlatformDeploymentError("promotion_evidence.rollback.available must be true")
    strategy = rollback.get("strategy")
    if not isinstance(strategy, str) or not 1 <= len(strategy.strip()) <= 120:
        raise PowerPlatformDeploymentError("promotion_evidence.rollback.strategy is required")
    rollback_digest = _digest(rollback.get("artifact_digest"), "promotion_evidence.rollback.artifact_digest")
    return {
        "source_stage": source_stage,
        "source_status": "succeeded",
        "source_approval_request_id": source_approval_request_id,
        "artifact_digest": artifact_digest,
        "evaluation": {"production_readiness": "pass", "case_count": case_count},
        "governance": {"status": "pass"},
        "rollback": {
            "available": True,
            "strategy": strategy.strip(),
            "artifact_digest": rollback_digest,
        },
    }


def validate_promotion_source(
    stage_id: str,
    evidence: Mapping[str, object],
    *,
    source_approval: Mapping[str, object] | None,
    current_payload: Mapping[str, object],
) -> None:
    """Require promotion evidence to reference a persisted successful stage.

    The evidence shape is still explicit and reviewable, but a caller cannot
    turn a declaration into promotion evidence without a same-tenant approval
    whose stored payload and execution result prove the immediately preceding
    stage succeeded for the same solution package.
    """

    source_stage = _PROMOTION_SOURCE_STAGES.get(stage_id)
    if source_stage is None:
        return
    if source_approval is None:
        raise PowerPlatformDeploymentError("promotion evidence source approval was not found")
    source_id = evidence.get("source_approval_request_id")
    if source_approval.get("id") != source_id:
        raise PowerPlatformDeploymentError("promotion evidence source approval does not match")
    if source_approval.get("client_id") != current_payload.get("client_id"):
        raise PowerPlatformDeploymentError("promotion evidence source approval is outside the tenant scope")
    if source_approval.get("action_type") != "power_platform.solution_stage":
        raise PowerPlatformDeploymentError("promotion evidence source approval has the wrong action type")
    if source_approval.get("status") != "approved":
        raise PowerPlatformDeploymentError("promotion evidence source approval is not approved")
    if source_approval.get("execution_status") != "succeeded":
        raise PowerPlatformDeploymentError("promotion evidence source stage has not succeeded")
    source_payload = source_approval.get("payload")
    if not isinstance(source_payload, Mapping):
        raise PowerPlatformDeploymentError("promotion evidence source approval payload is invalid")
    if source_payload.get("stage") != source_stage:
        raise PowerPlatformDeploymentError(f"promotion evidence source stage must be {source_stage}")
    for field in ("solution_name", "publisher_name", "publisher_prefix", "deployment_targets"):
        if source_payload.get(field) != current_payload.get(field):
            raise PowerPlatformDeploymentError(f"promotion evidence source {field} does not match")
    source_result = source_approval.get("execution_result")
    if not isinstance(source_result, Mapping) or source_result.get("status") != "succeeded":
        raise PowerPlatformDeploymentError("promotion evidence source execution result is not succeeded")
    if source_result.get("artifact_digest") != evidence.get("artifact_digest"):
        raise PowerPlatformDeploymentError("promotion evidence artifact digest does not match source execution")


def _reject_keys(value: Mapping[str, object], allowed: set[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise PowerPlatformDeploymentError(f"{field} contains unsupported fields: {', '.join(unknown)}")


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_DIGEST.fullmatch(value.strip()):
        raise PowerPlatformDeploymentError(f"{field} must be a sha256 digest")
    return value.strip()


def execute_power_platform_stage(
    plan: Mapping[str, object],
    stage_id: str,
    settings: Settings,
    *,
    approved: bool,
    runner: CommandRunner | None = None,
) -> dict[str, object]:
    """Execute one approved stage using a fixed, shell-free ``pac`` invocation."""

    if not approved:
        return _blocked(stage_id, "Power Platform execution requires a completed approval.")
    if not settings.allow_write_actions:
        return _blocked(stage_id, "Power Platform execution is blocked until WAIT_ALLOW_WRITE_ACTIONS=true.")
    if not settings.allow_power_platform_deployment:
        return _blocked(
            stage_id,
            "Power Platform deployment is blocked until WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true.",
        )
    if plan.get("credentials_included") is True:
        return _blocked(stage_id, "Power Platform deployment plans must not contain credentials.")
    try:
        stage = _stage(plan, stage_id)
        workspace, output_directory = _execution_paths(plan, settings)
        pac = shutil.which("pac")
        if not pac:
            return _blocked(stage_id, "The pac executable is not available on the local PATH.")
    except PowerPlatformDeploymentError as exc:
        return _blocked(stage_id, str(exc))

    run = runner or _run_command
    commands = cast(list[object], stage["commands"])
    results: list[dict[str, object]] = []
    timeout = min(max(float(settings.power_platform_command_timeout_seconds), 1.0), MAX_COMMAND_TIMEOUT_SECONDS)
    for raw_command in commands:
        if not isinstance(raw_command, list) or not all(isinstance(item, str) for item in raw_command):
            return _failed(stage_id, "Power Platform stage contains an invalid command.", results)
        if not raw_command or raw_command[0] != "pac":
            return _failed(stage_id, "Power Platform stage contains a non-canonical command.", results)
        command = [pac, *raw_command[1:]]
        try:
            completed = run(command, workspace, timeout)
        except subprocess.TimeoutExpired:
            return _failed(stage_id, "Power Platform command timed out.", results)
        except OSError:
            return _failed(stage_id, "Power Platform command could not be started.", results)
        command_result = {
            "command": [redact_text(item) for item in command[:4]],
            "return_code": completed.returncode,
            "stdout": _bounded_output(completed.stdout),
            "stderr": _bounded_output(completed.stderr),
        }
        results.append(command_result)
        if completed.returncode != 0:
            return _failed(stage_id, "Power Platform command failed.", results)
    artifact_digest = _artifact_digest(plan, workspace, output_directory)
    if artifact_digest is None:
        return _failed(stage_id, "Power Platform stage did not produce a verifiable solution artifact.", results)
    result = {
        "format": "wait-local-agent.power-platform.stage-result",
        "format_version": 1,
        "stage_id": stage_id,
        "status": "succeeded",
        "message": f"Power Platform stage {stage_id} completed.",
        "commands": results,
        "artifact_digest": artifact_digest,
        "execution_started": True,
        "deployment_started": bool(stage.get("deployment_started")),
    }
    return result


def _targets(value: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise PowerPlatformDeploymentError("deployment_targets must be an array")
    if not 1 <= len(value) <= MAX_DEPLOYMENT_TARGETS:
        raise PowerPlatformDeploymentError(f"deployment_targets must contain 1-{MAX_DEPLOYMENT_TARGETS} items")
    result: list[dict[str, str]] = []
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise PowerPlatformDeploymentError("deployment targets must contain objects")
        name = raw.get("name")
        if name != _TARGET_NAMES[index]:
            raise PowerPlatformDeploymentError(
                f"deployment targets must be ordered as {_TARGET_NAMES[:len(value)]}"
            )
        environment_url = raw.get("environment_url")
        if not isinstance(environment_url, str) or not _safe_environment_url(environment_url):
            raise PowerPlatformDeploymentError(f"{name}.environment_url must be a safe HTTPS URL")
        result.append({"name": name, "environment_url": environment_url.strip()})
    return result


def _safe_environment_url(value: str) -> bool:
    if len(value.strip()) > 253 or any(ord(char) < 32 for char in value):
        return False
    parsed = urlsplit(value.strip())
    return (
        parsed.scheme == "https"
        and bool(parsed.netloc)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _stage(plan: Mapping[str, object], stage_id: str) -> Mapping[str, object]:
    if not isinstance(stage_id, str) or stage_id not in {"build", "dev", "test", "prod"}:
        raise PowerPlatformDeploymentError("stage_id must be build, dev, test, or prod")
    stages = plan.get("stages")
    if not isinstance(stages, list):
        raise PowerPlatformDeploymentError("deployment plan stages are missing")
    for stage in stages:
        if isinstance(stage, Mapping) and stage.get("id") == stage_id:
            return stage
    raise PowerPlatformDeploymentError(f"stage is not present in the deployment plan: {stage_id}")


def _execution_paths(plan: Mapping[str, object], settings: Settings) -> tuple[Path, Path]:
    solution = plan.get("solution")
    if not isinstance(solution, Mapping):
        raise PowerPlatformDeploymentError("deployment plan solution is missing")
    raw_output = solution.get("output_directory")
    if not isinstance(raw_output, str) or not raw_output.strip():
        raise PowerPlatformDeploymentError("deployment output directory is missing")
    workspace = settings.power_platform_workspace.expanduser().resolve()
    output = Path(raw_output).expanduser().resolve()
    if workspace == output or workspace not in output.parents:
        raise PowerPlatformDeploymentError("deployment output directory must be inside WAIT_POWER_PLATFORM_WORKSPACE")
    if not workspace.is_dir():
        raise PowerPlatformDeploymentError("WAIT_POWER_PLATFORM_WORKSPACE must already exist")
    if not output.exists() and output.parent != workspace and not output.parent.is_dir():
        raise PowerPlatformDeploymentError("deployment output parent must already exist")
    return workspace, output


def _run_command(command: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - command is fixed and validated before execution
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        shell=False,
    )


def _bounded_output(value: str | None) -> str:
    return redact_text((value or "")[:MAX_STAGE_OUTPUT])


def _artifact_digest(plan: Mapping[str, object], workspace: Path, output_directory: Path) -> str | None:
    solution = plan.get("solution")
    if not isinstance(solution, Mapping):
        return None
    name = solution.get("name")
    if not isinstance(name, str) or not name:
        return None
    artifact = (output_directory / f"{name}.zip").resolve()
    try:
        return validate_power_platform_solution_package(artifact, workspace)
    except PowerPlatformDeploymentError:
        return None


def validate_power_platform_solution_package(
    artifact_path: str | Path,
    workspace: str | Path,
) -> str:
    """Validate a PAC solution archive before treating its digest as evidence.

    PAC execution is allowed to write only inside the configured workspace. The
    resulting file must also be a bounded, readable ZIP with no traversal,
    duplicate, encrypted, or symlink members. The returned digest is computed
    only after those checks pass, so a stage cannot report a successful package
    merely because an arbitrary file has the expected name.
    """

    workspace_path = Path(workspace).expanduser().resolve()
    artifact = Path(artifact_path).expanduser().resolve()
    if workspace_path == artifact or workspace_path not in artifact.parents:
        raise PowerPlatformDeploymentError("solution artifact must be inside WAIT_POWER_PLATFORM_WORKSPACE")
    if artifact.is_symlink() or not artifact.is_file():
        raise PowerPlatformDeploymentError("solution artifact is missing or is not a regular file")
    try:
        if artifact.stat().st_size > MAX_ARTIFACT_BYTES:
            raise PowerPlatformDeploymentError("solution artifact exceeds the bounded size limit")
        with zipfile.ZipFile(artifact) as archive:
            entries = archive.infolist()
            if not entries:
                raise PowerPlatformDeploymentError("solution artifact archive is empty")
            if len(entries) > MAX_ARTIFACT_ENTRIES:
                raise PowerPlatformDeploymentError("solution artifact contains too many entries")
            names: set[str] = set()
            total_size = 0
            for entry in entries:
                name = entry.filename
                if not name or any(ord(character) < 32 for character in name):
                    raise PowerPlatformDeploymentError("solution artifact contains an unsafe member name")
                if name in names:
                    raise PowerPlatformDeploymentError("solution artifact contains duplicate member names")
                names.add(name)
                if name.startswith(("/", "\\")) or "\\" in name:
                    raise PowerPlatformDeploymentError("solution artifact contains an unsafe member path")
                parts = name.split("/")
                if any(part in {"", ".", ".."} for part in parts[:-1]) or parts[-1] == "..":
                    raise PowerPlatformDeploymentError("solution artifact contains a traversal member path")
                if stat.S_ISLNK((entry.external_attr >> 16) & 0xFFFF):
                    raise PowerPlatformDeploymentError("solution artifact contains a symlink member")
                if entry.flag_bits & 0x1:
                    raise PowerPlatformDeploymentError("solution artifact contains an encrypted member")
                total_size += entry.file_size
                if total_size > MAX_ARTIFACT_BYTES:
                    raise PowerPlatformDeploymentError("solution artifact expands beyond the bounded size limit")
            if archive.testzip() is not None:
                raise PowerPlatformDeploymentError("solution artifact contains a member with an invalid checksum")
    except PowerPlatformDeploymentError:
        raise
    except zipfile.BadZipFile as exc:
        raise PowerPlatformDeploymentError("solution artifact is not a valid ZIP archive") from exc
    except (OSError, RuntimeError, ValueError) as exc:
        raise PowerPlatformDeploymentError("solution artifact could not be read safely") from exc

    digest = hashlib.sha256()
    try:
        with artifact.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise PowerPlatformDeploymentError("solution artifact could not be hashed") from exc
    return f"sha256:{digest.hexdigest()}"


def _blocked(stage_id: str, message: str) -> dict[str, object]:
    return {
        "format": "wait-local-agent.power-platform.stage-result",
        "format_version": 1,
        "stage_id": stage_id,
        "status": "blocked",
        "message": message,
        "commands": [],
        "execution_started": False,
        "deployment_started": False,
    }


def _failed(stage_id: str, message: str, commands: list[dict[str, object]]) -> dict[str, object]:
    return {
        "format": "wait-local-agent.power-platform.stage-result",
        "format_version": 1,
        "stage_id": stage_id,
        "status": "failed",
        "message": message,
        "commands": commands,
        "execution_started": bool(commands),
        "deployment_started": stage_id != "build" and bool(commands),
    }


__all__ = [
    "PowerPlatformDeploymentError",
    "build_power_platform_deployment_plan",
    "build_power_platform_deployment_plan_from_payload",
    "execute_power_platform_stage",
    "validate_power_platform_solution_package",
    "validate_promotion_evidence",
    "validate_promotion_source",
]
