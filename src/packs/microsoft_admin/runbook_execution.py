"""Execution boundary for fixed Microsoft administrator PowerShell runbooks."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess  # nosec B404 - fixed local executable, fixed argv, no shell.
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from wait_local_agent import platform_support
from wait_local_agent.config import Settings
from wait_local_agent.fs_permissions import (
    create_private_directory,
    restrict_existing_directory,
    write_private_bytes,
)
from wait_local_agent.models import ApprovalRequest
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.store import Store

from .runbook_catalog import (
    _bounded_client_id,
    _canonical_json,
    _definition,
    validate_runbook_plan,
)
from .runbook_types import (
    MAX_RUNBOOK_OUTPUT_CHARS,
    RUNBOOK_ACTION_TYPE,
    ExecutableResolver,
    PlatformPredicate,
    RunbookApprovalError,
    RunbookDefinition,
    RunbookError,
    RunbookExecutionResult,
    RunbookExecutionStatus,
    RunbookRunner,
    RunbookRuntimeStatus,
)


def runbook_runtime_status(
    settings: Settings,
    *,
    executable_resolver: ExecutableResolver | None = None,
    platform_is_windows: PlatformPredicate | None = None,
) -> RunbookRuntimeStatus:
    """Evaluate execution prerequisites without running PowerShell."""

    if settings.demo_mode:
        return RunbookRuntimeStatus(
            "blocked",
            "PowerShell runbooks are disabled in demo mode.",
        )
    if not settings.allow_write_actions:
        return RunbookRuntimeStatus(
            "blocked",
            "PowerShell runbooks are blocked until WAIT_ALLOW_WRITE_ACTIONS=true.",
        )
    windows_predicate = platform_is_windows or platform_support.is_windows
    if not windows_predicate():
        return RunbookRuntimeStatus(
            "not_configured",
            "PowerShell runbooks currently require a Windows host.",
        )
    resolver = executable_resolver or resolve_powershell_executable
    executable = resolver()
    if not executable:
        return RunbookRuntimeStatus(
            "not_configured",
            "A supported PowerShell executable was not found on the Windows host.",
        )
    candidate = Path(executable)
    if not candidate.is_absolute():
        return RunbookRuntimeStatus(
            "not_configured",
            "The resolved PowerShell executable path is not absolute.",
        )
    try:
        resolved_candidate = candidate.resolve(strict=True)
    except OSError:
        return RunbookRuntimeStatus(
            "not_configured",
            "The resolved PowerShell executable does not exist.",
        )
    if not resolved_candidate.is_file():
        return RunbookRuntimeStatus(
            "not_configured",
            "The resolved PowerShell executable is not a regular file.",
        )
    return RunbookRuntimeStatus(
        "ready",
        "PowerShell runbook execution prerequisites are ready.",
        str(resolved_candidate),
    )


def resolve_powershell_executable() -> str | None:
    """Resolve a fixed local PowerShell executable; callers cannot supply one."""

    for command in ("pwsh.exe", "powershell.exe", "pwsh", "powershell"):
        resolved = shutil.which(command)
        if not resolved:
            continue
        path = Path(resolved)
        try:
            absolute = path.resolve(strict=True)
        except OSError:
            continue
        if absolute.is_file():
            return str(absolute)
    return None


def execute_runbook_plan(
    payload: Mapping[str, object],
    settings: Settings,
    *,
    approved: bool,
    runner: RunbookRunner | None = None,
    executable_resolver: ExecutableResolver | None = None,
    platform_is_windows: PlatformPredicate | None = None,
) -> RunbookExecutionResult:
    """Execute only a canonical, approved, fixed-script runbook."""

    validated = validate_runbook_plan(payload)
    definition = _definition(cast(str, validated["runbook_id"]))
    if not approved:
        return _execution_result(
            definition,
            validated,
            status="blocked",
            message="PowerShell runbook execution requires an approved request.",
        )
    readiness = runbook_runtime_status(
        settings,
        executable_resolver=executable_resolver,
        platform_is_windows=platform_is_windows,
    )
    if readiness.status != "ready":
        return _execution_result(
            definition,
            validated,
            status=readiness.status,
            message=readiness.message,
        )

    run_directory: Path | None = None
    try:
        run_directory = _create_run_directory(settings)
        script_path = run_directory / "runbook.ps1"
        input_path = run_directory / "input.json"
        write_private_bytes(
            script_path,
            definition.script.encode("utf-8"),
            replace_existing=False,
        )
        input_bytes = _canonical_json(
            cast(dict[str, object], validated["parameters"])
        ).encode("utf-8")
        write_private_bytes(
            input_path,
            input_bytes,
            replace_existing=False,
        )
        actual_script_digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
        if actual_script_digest != definition.script_sha256:
            raise RunbookError("Materialized PowerShell script failed digest verification.")
        if input_path.read_bytes() != input_bytes:
            raise RunbookError("Materialized PowerShell input failed verification.")

        argv = [
            readiness.executable,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-InputJsonPath",
            str(input_path),
        ]
        active_runner = runner or _default_runner
        completed = active_runner(
            argv,
            run_directory,
            float(definition.timeout_seconds),
            _safe_powershell_environment(),
        )
    except subprocess.TimeoutExpired:
        return _execution_result(
            definition,
            validated,
            status="failed",
            message=f"PowerShell runbook exceeded its {definition.timeout_seconds}-second timeout.",
        )
    except (OSError, RunbookError) as exc:
        return _execution_result(
            definition,
            validated,
            status="failed",
            message=_safe_failure_message(exc),
        )
    finally:
        if run_directory is not None:
            shutil.rmtree(run_directory, ignore_errors=True)

    stdout, stdout_truncated = _bounded_text(completed.stdout or "")
    stderr, stderr_truncated = _bounded_text(completed.stderr or "")
    if completed.returncode != 0:
        return _execution_result(
            definition,
            validated,
            status="failed",
            message=f"PowerShell runbook failed with exit code {completed.returncode}.",
            exit_code=completed.returncode,
            output={"stdout": stdout} if stdout else None,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
    try:
        parsed_output = json.loads(stdout)
    except (TypeError, json.JSONDecodeError):
        return _execution_result(
            definition,
            validated,
            status="failed",
            message="PowerShell runbook returned malformed JSON.",
            exit_code=completed.returncode,
            output={"stdout": stdout} if stdout else None,
            stderr=stderr,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
        )
    if not isinstance(parsed_output, dict):
        return _execution_result(
            definition,
            validated,
            status="failed",
            message="PowerShell runbook returned an unsupported result shape.",
            exit_code=completed.returncode,
            stderr=stderr,
            stderr_truncated=stderr_truncated,
        )
    if parsed_output.get("runbook_id") != definition.runbook_id:
        return _execution_result(
            definition,
            validated,
            status="failed",
            message="PowerShell runbook result identity does not match the approved plan.",
            exit_code=completed.returncode,
            stderr=stderr,
            stderr_truncated=stderr_truncated,
        )
    expected_service = cast(dict[str, object], validated["parameters"]).get("service_name")
    if expected_service is not None and parsed_output.get("service_name") != expected_service:
        return _execution_result(
            definition,
            validated,
            status="failed",
            message="PowerShell runbook result target does not match the approved plan.",
            exit_code=completed.returncode,
            stderr=stderr,
            stderr_truncated=stderr_truncated,
        )
    return _execution_result(
        definition,
        validated,
        status="succeeded",
        message="PowerShell runbook completed and returned bounded JSON evidence.",
        exit_code=completed.returncode,
        output=redact_value(parsed_output),
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def execute_approved_runbook(
    store: Store,
    request_id: int,
    settings: Settings,
    *,
    expected_client_id: str,
    runner: RunbookRunner | None = None,
    executable_resolver: ExecutableResolver | None = None,
    platform_is_windows: PlatformPredicate | None = None,
) -> tuple[ApprovalRequest, RunbookExecutionResult]:
    """Execute a stored approval once and persist bounded evidence."""

    approval = store.get_approval_request(request_id)
    if approval is None:
        raise RunbookApprovalError("PowerShell runbook approval was not found.")
    if approval.action_type != RUNBOOK_ACTION_TYPE:
        raise RunbookApprovalError("Approval request is not a PowerShell runbook.")
    if approval.client_id != _bounded_client_id(expected_client_id):
        raise RunbookApprovalError("PowerShell runbook approval belongs to a different tenant.")
    if approval.status != "approved":
        raise RunbookApprovalError("PowerShell runbook approval is not approved.")
    if approval.execution_status != "not_started":
        raise RunbookApprovalError("PowerShell runbook approval has already been executed.")
    try:
        raw_payload = json.loads(approval.payload_json)
    except json.JSONDecodeError as exc:
        raise RunbookApprovalError("Stored PowerShell runbook approval is malformed.") from exc
    if not isinstance(raw_payload, dict):
        raise RunbookApprovalError("Stored PowerShell runbook approval is malformed.")
    validated = validate_runbook_plan(
        cast(dict[str, object], raw_payload),
        expected_client_id=expected_client_id,
    )
    result = execute_runbook_plan(
        validated,
        settings,
        approved=True,
        runner=runner,
        executable_resolver=executable_resolver,
        platform_is_windows=platform_is_windows,
    )
    if result.status in {"blocked", "not_configured"}:
        raise RunbookApprovalError(result.message)
    updated = store.record_approval_execution(
        request_id,
        status=result.status,
        message=result.message,
        result=result.to_dict(),
        audit_event_type="microsoft_admin.powershell_runbook",
    )
    return updated, result


def _create_run_directory(settings: Settings) -> Path:
    root = settings.data_path.parent / "powershell-runbooks"
    create_private_directory(root)
    restrict_existing_directory(root)
    run_directory = root / uuid.uuid4().hex
    run_directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    restrict_existing_directory(run_directory)
    return run_directory


def _safe_powershell_environment() -> dict[str, str]:
    allowed = (
        "SystemRoot",
        "WINDIR",
        "TEMP",
        "TMP",
        "PSModulePath",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["POWERSHELL_TELEMETRY_OPTOUT"] = "1"
    environment["POWERSHELL_UPDATECHECK"] = "Off"
    return environment


def _default_runner(
    argv: list[str],
    cwd: Path,
    timeout_seconds: float,
    environment: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - fixed absolute executable and fixed argv.
        argv,
        cwd=cwd,
        timeout=timeout_seconds,
        shell=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=dict(environment),
        check=False,
    )


def _execution_result(
    definition: RunbookDefinition,
    plan: Mapping[str, object],
    *,
    status: RunbookExecutionStatus,
    message: str,
    exit_code: int | None = None,
    output: object = None,
    stderr: str = "",
    stdout_truncated: bool = False,
    stderr_truncated: bool = False,
) -> RunbookExecutionResult:
    return RunbookExecutionResult(
        status=status,
        message=message,
        runbook_id=definition.runbook_id,
        runbook_version=definition.version,
        effect=definition.effect,
        risk_level=definition.risk_level,
        plan_digest=cast(str, plan["plan_digest"]),
        script_sha256=cast(str, plan["script_sha256"]),
        exit_code=exit_code,
        output=output,
        stderr=stderr,
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
    )


def _safe_failure_message(exc: BaseException) -> str:
    if isinstance(exc, RunbookError):
        return redact_text(str(exc))[:512]
    return "PowerShell runbook execution failed before a result was returned."


def _bounded_text(value: str) -> tuple[str, bool]:
    redacted = redact_text(value)
    if len(redacted) <= MAX_RUNBOOK_OUTPUT_CHARS:
        return redacted, False
    return redacted[:MAX_RUNBOOK_OUTPUT_CHARS] + "...[truncated]", True
