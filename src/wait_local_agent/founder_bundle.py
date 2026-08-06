from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class PrivacyViolation(ValueError):
    """Raised when a bundle contains data outside the public evidence contract."""


_SKIP_DIRECTORIES = {".git", ".venv", "node_modules", "__pycache__", ".wait-local-agent"}
_SKIP_NAMES = {".env", ".env.local", ".env.production", ".env.development"}
_SECRET_KEYS = {
    "apikey",
    "authorization",
    "clientsecret",
    "connectionstring",
    "credential",
    "credentials",
    "connectorcredentials",
    "password",
    "secret",
    "secretvalue",
    "token",
    "value",
    "envvalue",
    "envvalues",
    "content",
    "source",
}
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def build_founder_bundle(
    project_root: Path,
    *,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    files = _file_manifest(root)
    dependencies = _dependency_names(root)
    env_keys = _environment_keys(root)
    bundle = {
        "schema": "collector_bundle_v1",
        "metadata": {
            "collectorVersion": "wait-local-agent/1.1.1",
            "collectedAt": datetime.now(UTC).isoformat(),
            "root": "[redacted]",
            "sourceCode": False,
        },
        "files": files,
        "dependencies": dependencies,
        "environment": {"keys": env_keys},
        "findings": findings or [],
    }
    return sanitize_bundle(bundle)


assemble_bundle = build_founder_bundle


def bundle_hash(bundle: dict[str, Any]) -> str:
    sanitized = sanitize_bundle(bundle)
    serialized = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sanitize_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        raise PrivacyViolation("bundle must be an object")
    copied = json.loads(json.dumps(bundle))
    _validate_tree(copied)
    metadata = copied.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        raise PrivacyViolation("bundle metadata must be an object")
    source_code = metadata.get("sourceCode", False)
    if source_code is not False:
        raise PrivacyViolation("sourceCode must be false")
    metadata["sourceCode"] = False
    metadata["root"] = "[redacted]"
    for key in ("files", "dependencies", "findings"):
        if key in copied and not isinstance(copied[key], list):
            raise PrivacyViolation(f"bundle {key} must be a list")
    environment = copied.get("environment")
    if environment is not None:
        if not isinstance(environment, dict) or set(environment) - {"keys"}:
            raise PrivacyViolation("environment may contain key names only")
        keys = environment.get("keys", [])
        if not isinstance(keys, list) or not all(_valid_env_name(item) for item in keys):
            raise PrivacyViolation("environment keys must be names only")
    env_keys = copied.get("env_keys")
    if env_keys is not None and (not isinstance(env_keys, list) or not all(_valid_env_name(item) for item in env_keys)):
        raise PrivacyViolation("env_keys must contain names only")
    _validate_paths(copied)
    return copied


def _file_manifest(root: Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _skip_path(path, root):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
        files.append({"path": path.relative_to(root).as_posix(), "sha256": digest})
    return files


def _dependency_names(root: Path) -> list[str]:
    names: set[str] = set()
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            for field in ("dependencies", "devDependencies", "peerDependencies"):
                values = payload.get(field, {})
                if isinstance(values, dict):
                    names.update(str(name) for name in values)
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        project = payload.get("project", {})
        if isinstance(project, dict):
            values = project.get("dependencies", [])
            if isinstance(values, list):
                names.update(_package_name(str(value)) for value in values)
    for path in sorted(root.glob("requirements*.txt")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        names.update(_package_name(line) for line in lines if line.strip() and not line.startswith("#"))
    return sorted(name for name in names if name)


def _environment_keys(root: Path) -> list[str]:
    path = root / ".env.example"
    if not path.is_file():
        return []
    keys: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        candidate = line.strip().split("=", 1)[0].strip()
        if candidate and not candidate.startswith("#") and _valid_env_name(candidate):
            keys.append(candidate)
    return sorted(set(keys))


def _validate_tree(value: Any, key: str = "") -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            child_key = str(raw_key)
            normalized = re.sub(r"[^a-z0-9]", "", child_key.lower())
            if normalized in _SECRET_KEYS or normalized in {"filebody", "sourcecontent"}:
                raise PrivacyViolation(f"private value is not allowed at {child_key}")
            if normalized == "sourcecode" and child is not False:
                raise PrivacyViolation("sourceCode must be false")
            _validate_tree(child, child_key)
    elif isinstance(value, list):
        for child in value:
            _validate_tree(child, key)


def _validate_paths(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"path", "root", "source_path"} and isinstance(child, str):
                if os.path.isabs(child) or ".." in Path(child).parts:
                    raise PrivacyViolation("bundle paths must be relative")
            _validate_paths(child)
    elif isinstance(value, list):
        for child in value:
            _validate_paths(child)


def _skip_path(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if any(part in _SKIP_DIRECTORIES for part in relative.parts):
        return True
    return path.name in _SKIP_NAMES or path.suffix in {".pem", ".key", ".enc"}


def _valid_env_name(value: object) -> bool:
    return isinstance(value, str) and bool(_ENV_NAME.fullmatch(value))


def _package_name(value: str) -> str:
    return re.split(r"[<>=!~;\s\[]", value.strip(), maxsplit=1)[0].strip()
