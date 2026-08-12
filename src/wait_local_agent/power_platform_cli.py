"""Bounded Power Platform CLI planning and approval-gated execution."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess  # nosec B404 - execution is restricted to the generated fixed PAC argv below.
from pathlib import Path
from typing import Literal, cast

from wait_local_agent.reports.renderers import redact_text

MAX_PAC_ARTIFACT_BYTES = 1_000_000
MAX_PAC_OUTPUT_BYTES = 64_000
MAX_PAC_TIMEOUT_SECONDS = 300
SOLUTION_UNIQUE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,99}$")
ENVIRONMENT_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class PowerPlatformCliError(ValueError):
    """Raised when a PAC plan or execution request is unsafe or invalid."""


def build_pac_connector_create_plan(
    artifact_dir: object,
    *,
    environment: object,
    solution_unique_name: object | None = None,
) -> dict[str, object]:
    """Build a fixed, reviewable ``pac connector create`` command.

    The plan validates the three files produced by the connector factory and
    records their digests. It never invokes PAC or contacts Dataverse.
    """

    root = _artifact_root(artifact_dir)
    environment_value = _environment(environment)
    solution_value = _solution_name(solution_unique_name)
    files = {
        "api_definition": _artifact_file(root, "apiDefinition.json"),
        "api_properties": _artifact_file(root, "apiProperties.json"),
        "manifest": _artifact_file(root, "manifest.json"),
    }
    definition = _json_object(files["api_definition"], "apiDefinition.json")
    properties = _json_object(files["api_properties"], "apiProperties.json")
    manifest = _json_object(files["manifest"], "manifest.json")
    if definition.get("swagger") != "2.0":
        raise PowerPlatformCliError("apiDefinition.json must contain an OpenAPI 2.0 definition")
    if not isinstance(properties.get("properties"), dict):
        raise PowerPlatformCliError("apiProperties.json must contain a properties object")
    if manifest.get("format") != "wait-local-agent.power-platform-connector":
        raise PowerPlatformCliError("manifest.json is not a WAIT Power Platform connector artifact")
    if manifest.get("format_version") != 1:
        raise PowerPlatformCliError("manifest.json has an unsupported connector artifact version")

    command = [
        "pac",
        "connector",
        "create",
        "--api-definition-file",
        str(files["api_definition"]),
        "--api-properties-file",
        str(files["api_properties"]),
        "--environment",
        environment_value,
    ]
    if solution_value is not None:
        command.extend(["--solution-unique-name", solution_value])
    digests = {
        name: {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}
        for name, path in files.items()
    }
    approval_payload = {
        "operation": "connector.create",
        "environment": environment_value,
        "solution_unique_name": solution_value,
        "artifact_dir": str(root),
        "file_sha256": {name: value["sha256"] for name, value in digests.items()},
    }
    return {
        "format": "wait-local-agent.power-platform-cli-plan",
        "format_version": 1,
        "operation": "connector.create",
        "mutates_external_state": True,
        "requires_approval": True,
        "pac_available": shutil.which("pac") is not None,
        "environment": environment_value,
        "solution_unique_name": solution_value,
        "artifact_dir": str(root),
        "files": digests,
        "command": command,
        "approval_payload": approval_payload,
    }


def run_pac_connector_create(
    plan: dict[str, object],
    *,
    approved: bool,
    timeout_seconds: int = 120,
) -> dict[str, object]:
    """Execute only a previously generated connector-create plan."""

    if not approved:
        raise PowerPlatformCliError("an approved Power Platform PAC request is required")
    if timeout_seconds < 1 or timeout_seconds > MAX_PAC_TIMEOUT_SECONDS:
        raise PowerPlatformCliError(f"PAC timeout must be between 1 and {MAX_PAC_TIMEOUT_SECONDS} seconds")
    command = plan.get("command")
    artifact_dir = plan.get("artifact_dir")
    if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
        raise PowerPlatformCliError("PAC plan command is invalid")
    if not isinstance(artifact_dir, str) or not artifact_dir:
        raise PowerPlatformCliError("PAC plan artifact directory is invalid")
    executable = shutil.which("pac")
    if executable is None:
        return {
            "status": "not_configured",
            "exit_code": None,
            "message": "pac was not found on PATH; install Power Platform CLI before execution",
            "stdout": "",
            "stderr": "",
        }
    safe_command = [executable, *command[1:]]
    try:
        completed = subprocess.run(  # nosec B603 - fixed argv, shell disabled, bounded timeout, sanitized environment.
            safe_command,
            cwd=artifact_dir,
            env=_safe_environment(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timed_out",
            "exit_code": None,
            "message": f"PAC execution exceeded the {timeout_seconds}-second timeout",
            "stdout": _bounded_output(exc.stdout),
            "stderr": _bounded_output(exc.stderr),
        }
    except OSError as exc:
        return {
            "status": "failed",
            "exit_code": None,
            "message": "PAC execution could not be started",
            "stdout": "",
            "stderr": redact_text(str(exc)),
        }
    status: Literal["succeeded", "failed"] = "succeeded" if completed.returncode == 0 else "failed"
    return {
        "status": status,
        "exit_code": completed.returncode,
        "message": "PAC connector create completed" if status == "succeeded" else "PAC connector create failed",
        "stdout": _bounded_output(completed.stdout),
        "stderr": _bounded_output(completed.stderr),
    }


def _artifact_root(value: object) -> Path:
    if not isinstance(value, str | Path):
        raise PowerPlatformCliError("artifact directory must be a local path")
    raw = Path(value)
    if raw.is_symlink():
        raise PowerPlatformCliError("artifact directory symlinks are not allowed")
    try:
        root = raw.resolve(strict=True)
    except OSError as exc:
        raise PowerPlatformCliError("artifact directory does not exist") from exc
    if not root.is_dir():
        raise PowerPlatformCliError("artifact directory must be a directory")
    return root


def _artifact_file(root: Path, filename: str) -> Path:
    path = root / filename
    if path.is_symlink() or not path.is_file():
        raise PowerPlatformCliError(f"artifact directory is missing {filename}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PowerPlatformCliError(f"artifact file {filename} cannot be read") from exc
    if resolved.parent != root:
        raise PowerPlatformCliError(f"artifact file {filename} must remain inside artifact directory")
    if resolved.stat().st_size > MAX_PAC_ARTIFACT_BYTES:
        raise PowerPlatformCliError(f"artifact file {filename} exceeds the {MAX_PAC_ARTIFACT_BYTES}-byte limit")
    return resolved


def _json_object(path: Path, filename: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PowerPlatformCliError(f"artifact file {filename} must contain valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise PowerPlatformCliError(f"artifact file {filename} must contain a JSON object")
    return cast(dict[str, object], payload)


def _environment(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PowerPlatformCliError("a target Power Platform environment is required")
    normalized = value.strip()
    if ENVIRONMENT_ID_PATTERN.fullmatch(normalized):
        return normalized
    if normalized.startswith("https://") and "?" not in normalized and "#" not in normalized:
        return normalized.rstrip("/")
    raise PowerPlatformCliError("environment must be a GUID or an HTTPS environment URL")


def _solution_name(value: object | None) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not SOLUTION_UNIQUE_NAME_PATTERN.fullmatch(value):
        raise PowerPlatformCliError("solution unique name must contain only letters, numbers, and underscores")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_environment() -> dict[str, str]:
    blocked_fragments = ("TOKEN", "SECRET", "PASSWORD", "CLIENT_KEY", "PRIVATE_KEY")
    return {
        key: value
        for key, value in os.environ.items()
        if not any(fragment in key.upper() for fragment in blocked_fragments)
    }


def _bounded_output(value: object) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    elif isinstance(value, str):
        text = value
    else:
        text = ""
    return redact_text(text[:MAX_PAC_OUTPUT_BYTES])
