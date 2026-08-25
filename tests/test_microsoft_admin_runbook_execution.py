from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import cast

from packs.microsoft_admin.runbooks import (
    build_runbook_plan,
    execute_runbook_plan,
    resolve_powershell_executable,
    runbook_runtime_status,
)
from tests.microsoft_admin_runbook_support import _execution_settings, _fake_powershell


def test_runbook_runtime_status_requires_gate_windows_and_absolute_executable(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    assert runbook_runtime_status(replace(configured, demo_mode=True)).status == "blocked"
    assert runbook_runtime_status(replace(configured, allow_write_actions=False)).status == "blocked"
    assert runbook_runtime_status(
        configured,
        platform_is_windows=lambda: False,
    ).status == "not_configured"
    assert runbook_runtime_status(
        configured,
        platform_is_windows=lambda: True,
        executable_resolver=lambda: None,
    ).status == "not_configured"
    assert runbook_runtime_status(
        configured,
        platform_is_windows=lambda: True,
        executable_resolver=lambda: "pwsh.exe",
    ).status == "not_configured"
    assert runbook_runtime_status(
        configured,
        platform_is_windows=lambda: True,
        executable_resolver=lambda: str(tmp_path / "missing.exe"),
    ).status == "not_configured"
    directory = tmp_path / "powershell-directory"
    directory.mkdir()
    assert runbook_runtime_status(
        configured,
        platform_is_windows=lambda: True,
        executable_resolver=lambda: str(directory.resolve()),
    ).status == "not_configured"
    ready = runbook_runtime_status(
        configured,
        platform_is_windows=lambda: True,
        executable_resolver=lambda: executable,
    )
    assert ready.status == "ready"
    assert ready.executable == executable


def test_resolve_powershell_executable_uses_only_fixed_local_candidates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import packs.microsoft_admin.runbook_execution as module

    executable = _fake_powershell(tmp_path)
    calls: list[str] = []

    def which(command: str) -> str | None:
        calls.append(command)
        return executable if command == "powershell.exe" else None

    monkeypatch.setattr(module.shutil, "which", which)
    assert resolve_powershell_executable() == executable
    assert calls == ["pwsh.exe", "powershell.exe"]

    monkeypatch.setattr(module.shutil, "which", lambda command: None)
    assert resolve_powershell_executable() is None


def test_execute_runbook_uses_fixed_argv_private_files_and_bounded_json(
    settings,
    tmp_path: Path,
    monkeypatch,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    monkeypatch.setenv("WAIT_M365_ACCESS_TOKEN", "must-not-be-inherited")
    plan = build_runbook_plan(
        "windows.endpoint_health",
        {"include_event_logs": False, "event_hours": 4, "max_events": 3},
        client_id="client-1",
    )
    captured: dict[str, object] = {}

    def runner(
        argv: list[str],
        cwd: Path,
        timeout_seconds: float,
        environment,
    ) -> subprocess.CompletedProcess[str]:
        captured["argv"] = list(argv)
        captured["cwd"] = cwd
        captured["timeout"] = timeout_seconds
        captured["environment"] = dict(environment)
        captured["script_digest"] = hashlib.sha256((cwd / "runbook.ps1").read_bytes()).hexdigest()
        captured["input"] = json.loads((cwd / "input.json").read_text(encoding="utf-8"))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "runbook_id": "windows.endpoint_health",
                    "computer": {"name": "LAPTOP-001"},
                    "access_token": "must-be-redacted",
                }
            ),
            stderr="",
        )

    result = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        runner=runner,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )

    assert result.status == "succeeded"
    assert result.output == {
        "runbook_id": "windows.endpoint_health",
        "computer": {"name": "LAPTOP-001"},
        "access_token": "[redacted]",
    }
    argv = cast(list[str], captured["argv"])
    assert argv[:7] == [
        executable,
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
    ]
    assert argv[-2] == "-InputJsonPath"
    assert "client-1" not in argv
    assert captured["input"] == {
        "event_hours": 4,
        "include_event_logs": False,
        "max_events": 3,
    }
    assert captured["script_digest"] == cast(str, plan["script_sha256"]).removeprefix("sha256:")
    assert "WAIT_M365_ACCESS_TOKEN" not in cast(dict[str, str], captured["environment"])
    assert not cast(Path, captured["cwd"]).exists()


def test_execute_runbook_handles_approval_timeout_failure_and_malformed_output(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    plan = build_runbook_plan(
        "windows.service_restart",
        {"service_name": "BITS", "wait_seconds": 5},
        client_id="client-1",
    )

    blocked = execute_runbook_plan(
        plan,
        configured,
        approved=False,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert blocked.status == "blocked"

    def timeout_runner(argv, cwd, timeout_seconds, environment):
        raise subprocess.TimeoutExpired(argv, timeout_seconds)

    timed_out = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        runner=timeout_runner,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert timed_out.status == "failed"
    assert "timeout" in timed_out.message

    def failed_runner(argv, cwd, timeout_seconds, environment):
        return subprocess.CompletedProcess(
            argv,
            5,
            stdout="x" * 40_000,
            stderr="password=must-not-leak",
        )

    failed = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        runner=failed_runner,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert failed.status == "failed"
    assert failed.exit_code == 5
    assert failed.stdout_truncated is True
    assert "must-not-leak" not in failed.stderr

    for stdout, expected in [
        ("not-json", "malformed"),
        ("[]", "unsupported"),
        (json.dumps({"runbook_id": "other"}), "identity"),
        (
            json.dumps(
                {
                    "runbook_id": "windows.service_restart",
                    "service_name": "wuauserv",
                }
            ),
            "target",
        ),
    ]:
        result = execute_runbook_plan(
            plan,
            configured,
            approved=True,
            runner=lambda argv, cwd, timeout_seconds, environment, value=stdout: subprocess.CompletedProcess(
                argv,
                0,
                stdout=value,
                stderr="",
            ),
            executable_resolver=lambda: executable,
            platform_is_windows=lambda: True,
        )
        assert result.status == "failed"
        assert expected in result.message


def test_execute_runbook_preserves_approval_when_runtime_is_unavailable(
    settings,
    tmp_path: Path,
) -> None:
    configured = _execution_settings(settings, tmp_path)
    plan = build_runbook_plan("windows.endpoint_health", {}, client_id="client-1")
    result = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        executable_resolver=lambda: None,
        platform_is_windows=lambda: True,
    )
    assert result.status == "not_configured"


def test_execute_runbook_sanitizes_pre_execution_os_failures(
    settings,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import packs.microsoft_admin.runbook_execution as module

    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    plan = build_runbook_plan("windows.endpoint_health", {}, client_id="client-1")

    def fail_write(path: Path, data: bytes, *, replace_existing: bool) -> None:
        raise OSError("password=must-not-leak")

    monkeypatch.setattr(module, "write_private_bytes", fail_write)
    result = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert result.status == "failed"
    assert result.message == "PowerShell runbook execution failed before a result was returned."
    assert "must-not-leak" not in result.message


def test_execute_runbook_detects_materialized_script_tampering(
    settings,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import packs.microsoft_admin.runbook_execution as module

    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    plan = build_runbook_plan("windows.endpoint_health", {}, client_id="client-1")
    original = module.write_private_bytes

    def tampering_write(path: Path, data: bytes, *, replace_existing: bool) -> None:
        if path.suffix == ".ps1":
            data += b"\n# tampered"
        original(path, data, replace_existing=replace_existing)

    monkeypatch.setattr(module, "write_private_bytes", tampering_write)
    result = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert result.status == "failed"
    assert "digest" in result.message


def test_execute_runbook_detects_materialized_input_tampering(
    settings,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import packs.microsoft_admin.runbook_execution as module

    configured = _execution_settings(settings, tmp_path)
    executable = _fake_powershell(tmp_path)
    plan = build_runbook_plan("windows.endpoint_health", {}, client_id="client-1")
    original = module.write_private_bytes

    def tampering_write(path: Path, data: bytes, *, replace_existing: bool) -> None:
        if path.suffix == ".json":
            data = b"{}"
        original(path, data, replace_existing=replace_existing)

    monkeypatch.setattr(module, "write_private_bytes", tampering_write)
    result = execute_runbook_plan(
        plan,
        configured,
        approved=True,
        executable_resolver=lambda: executable,
        platform_is_windows=lambda: True,
    )
    assert result.status == "failed"
    assert "input" in result.message
