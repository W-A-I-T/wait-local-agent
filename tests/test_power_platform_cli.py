from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import wait_local_agent.power_platform_cli as pac_module
from wait_local_agent.power_platform_cli import (
    PowerPlatformCliError,
    build_pac_connector_create_plan,
    run_pac_connector_create,
)


def _artifact_dir(tmp_path: Path) -> Path:
    root = tmp_path / "connector-artifact"
    root.mkdir()
    (root / "apiDefinition.json").write_text(
        json.dumps({"swagger": "2.0", "info": {"title": "WAIT", "version": "1"}}),
        encoding="utf-8",
    )
    (root / "apiProperties.json").write_text(json.dumps({"properties": {}}), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "wait-local-agent.power-platform-connector",
                "format_version": 1,
                "name": "WAIT",
            }
        ),
        encoding="utf-8",
    )
    return root


def test_pac_plan_is_fixed_bounded_and_digest_bound(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _artifact_dir(tmp_path)
    monkeypatch.setattr(pac_module.shutil, "which", lambda name: "/usr/bin/pac" if name == "pac" else None)

    plan = build_pac_connector_create_plan(
        root,
        environment="00000000-0000-0000-0000-000000000001",
        solution_unique_name="WaitConnector",
    )

    assert plan["pac_available"] is True
    assert plan["requires_approval"] is True
    assert plan["mutates_external_state"] is True
    assert plan["command"] == [
        "pac",
        "connector",
        "create",
        "--api-definition-file",
        str(root / "apiDefinition.json"),
        "--api-properties-file",
        str(root / "apiProperties.json"),
        "--environment",
        "00000000-0000-0000-0000-000000000001",
        "--solution-unique-name",
        "WaitConnector",
    ]
    approval_payload = plan["approval_payload"]
    assert isinstance(approval_payload, dict)
    assert set(approval_payload["file_sha256"]) == {"api_definition", "api_properties", "manifest"}


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda root: (root / "manifest.json").write_text("{}", encoding="utf-8"), "manifest"),
        (lambda root: (root / "apiDefinition.json").write_text("[]", encoding="utf-8"), "JSON object"),
        (lambda root: None, "environment"),
        (lambda root: None, "solution unique name"),
    ],
)
def test_pac_plan_rejects_invalid_artifacts_and_targets(
    tmp_path: Path, mutate, message: str
) -> None:
    root = _artifact_dir(tmp_path)
    mutate(root)
    environment: object = "" if message == "environment" else "https://org.crm.dynamics.com"
    solution: object | None = "bad-name" if message == "solution unique name" else None

    with pytest.raises(PowerPlatformCliError, match=message):
        build_pac_connector_create_plan(root, environment=environment, solution_unique_name=solution)


def test_pac_plan_rejects_symlinked_artifacts(tmp_path: Path) -> None:
    root = _artifact_dir(tmp_path)
    external = tmp_path / "external.json"
    external.write_text("{}", encoding="utf-8")
    (root / "apiProperties.json").unlink()
    (root / "apiProperties.json").symlink_to(external)

    with pytest.raises(PowerPlatformCliError, match="apiProperties.json"):
        build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")


def test_pac_execution_requires_approval_and_reports_missing_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _artifact_dir(tmp_path)
    plan = build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")
    with pytest.raises(PowerPlatformCliError, match="approved"):
        run_pac_connector_create(plan, approved=False)

    monkeypatch.setattr(pac_module.shutil, "which", lambda name: None)
    result = run_pac_connector_create(plan, approved=True)
    assert result["status"] == "not_configured"
    assert "install Power Platform CLI" in str(result["message"])


def test_pac_execution_uses_no_shell_and_redacts_environment_and_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _artifact_dir(tmp_path)
    plan = build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="token=secret-value", stderr="")

    monkeypatch.setenv("WAIT_SECRET_VALUE", "should-not-reach-pac")
    monkeypatch.setattr(pac_module.shutil, "which", lambda name: "/usr/bin/pac")
    monkeypatch.setattr(pac_module.subprocess, "run", fake_run)

    result = run_pac_connector_create(plan, approved=True)

    assert result["status"] == "succeeded"
    assert result["stdout"] == "token=[redacted]"
    assert captured["shell"] is False
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert "WAIT_SECRET_VALUE" not in environment


def test_pac_execution_reports_nonzero_exit_and_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _artifact_dir(tmp_path)
    plan = build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")
    monkeypatch.setattr(pac_module.shutil, "which", lambda name: "/usr/bin/pac")
    monkeypatch.setattr(
        pac_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="bad", stderr="error"),
    )
    failed = run_pac_connector_create(plan, approved=True)
    assert failed["status"] == "failed"
    assert failed["exit_code"] == 2

    def timeout(*args, **kwargs):
        raise pac_module.subprocess.TimeoutExpired(kwargs["args"] if "args" in kwargs else args[0], 1, output=b"out")

    monkeypatch.setattr(pac_module.subprocess, "run", timeout)
    timed_out = run_pac_connector_create(plan, approved=True)
    assert timed_out["status"] == "timed_out"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda root: (root / "apiDefinition.json").write_text(
                json.dumps({"swagger": "3.0"}), encoding="utf-8"
            ),
            "OpenAPI 2.0",
        ),
        (lambda root: (root / "apiProperties.json").write_text(json.dumps({}), encoding="utf-8"), "properties object"),
        (
            lambda root: (root / "manifest.json").write_text(
                json.dumps(
                    {"format": "wait-local-agent.power-platform-connector", "format_version": 2}
                ),
                encoding="utf-8",
            ),
            "version",
        ),
        (lambda root: (root / "apiDefinition.json").write_text("not json", encoding="utf-8"), "valid UTF-8 JSON"),
    ],
)
def test_pac_plan_rejects_bad_factory_artifacts(tmp_path: Path, mutate, message: str) -> None:
    root = _artifact_dir(tmp_path)
    mutate(root)
    with pytest.raises(PowerPlatformCliError, match=message):
        build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")


@pytest.mark.parametrize(
    ("artifact_dir", "environment", "solution", "message"),
    [
        (None, "https://org.crm.dynamics.com", None, "local path"),
        ("/missing", "https://org.crm.dynamics.com", None, "does not exist"),
        ("", "https://org.crm.dynamics.com", None, "missing apiDefinition"),
        ("__root__", "http://org.crm.dynamics.com", None, "HTTPS"),
        ("__root__", "https://org.crm.dynamics.com?x=1", None, "GUID or"),
        ("__root__", "https://org.crm.dynamics.com", 3, "solution unique name"),
    ],
)
def test_pac_plan_rejects_invalid_path_target_and_solution(
    tmp_path: Path, artifact_dir, environment, solution, message: str
) -> None:
    root = _artifact_dir(tmp_path)
    selected = root if artifact_dir == "__root__" else artifact_dir
    with pytest.raises(PowerPlatformCliError, match=message):
        build_pac_connector_create_plan(selected, environment=environment, solution_unique_name=solution)


def test_pac_plan_rejects_symlinked_root_and_missing_files(tmp_path: Path) -> None:
    root = _artifact_dir(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(root, target_is_directory=True)
    with pytest.raises(PowerPlatformCliError, match="symlinks"):
        build_pac_connector_create_plan(linked, environment="https://org.crm.dynamics.com")
    (root / "manifest.json").unlink()
    with pytest.raises(PowerPlatformCliError, match="manifest.json"):
        build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")


def test_pac_plan_rejects_file_root_and_oversized_artifact(tmp_path: Path) -> None:
    file_root = tmp_path / "not-a-directory"
    file_root.write_text("x", encoding="utf-8")
    with pytest.raises(PowerPlatformCliError, match="directory"):
        build_pac_connector_create_plan(file_root, environment="https://org.crm.dynamics.com")
    root = _artifact_dir(tmp_path)
    (root / "apiDefinition.json").write_bytes(b"x" * (pac_module.MAX_PAC_ARTIFACT_BYTES + 1))
    with pytest.raises(PowerPlatformCliError, match="byte limit"):
        build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")


def test_pac_plan_rejects_unreadable_or_escaped_artifact_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _artifact_dir(tmp_path)
    original_resolve = Path.resolve

    def unreadable(self: Path, strict: bool = False) -> Path:
        if self.name == "apiProperties.json":
            raise OSError("unreadable")
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(pac_module.Path, "resolve", unreadable)
    with pytest.raises(PowerPlatformCliError, match="cannot be read"):
        build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")

    def escaped(self: Path, strict: bool = False) -> Path:
        if self.name == "apiProperties.json":
            return tmp_path / "outside" / self.name
        return original_resolve(self, strict=strict)

    monkeypatch.setattr(pac_module.Path, "resolve", escaped)
    with pytest.raises(PowerPlatformCliError, match="remain inside"):
        build_pac_connector_create_plan(root, environment="https://org.crm.dynamics.com")


def test_pac_execution_rejects_invalid_plan_and_process_start_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(PowerPlatformCliError, match="timeout"):
        run_pac_connector_create({"command": [], "artifact_dir": "x"}, approved=True, timeout_seconds=301)
    with pytest.raises(PowerPlatformCliError, match="command"):
        run_pac_connector_create({"command": "pac", "artifact_dir": "x"}, approved=True)
    with pytest.raises(PowerPlatformCliError, match="artifact directory"):
        run_pac_connector_create({"command": ["pac"], "artifact_dir": ""}, approved=True)
    monkeypatch.setattr(pac_module.shutil, "which", lambda name: "/usr/bin/pac")
    def fail_to_start(*args, **kwargs):
        raise OSError("token=bad")

    monkeypatch.setattr(pac_module.subprocess, "run", fail_to_start)
    result = run_pac_connector_create(
        {"command": ["pac", "connector", "create"], "artifact_dir": str(tmp_path)}, approved=True
    )
    assert result["status"] == "failed"
    assert result["stderr"] == "token=[redacted]"


def test_pac_execution_bounds_bytes_and_non_text_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pac_module.shutil, "which", lambda name: "/usr/bin/pac")
    monkeypatch.setattr(
        pac_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=b"token=secret", stderr=None),
    )
    result = run_pac_connector_create(
        {"command": ["pac", "connector", "create"], "artifact_dir": str(tmp_path)}, approved=True
    )
    assert result["stdout"] == "token=[redacted]"
    assert result["stderr"] == ""
