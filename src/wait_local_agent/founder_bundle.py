from __future__ import annotations

import hashlib
import json
import math
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
    "values",
    "envvalue",
    "envvalues",
    "content",
    "source",
}
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?key|client[_-]?secret|secret|token|password|passwd|private[_-]?key)"
    r"(\s*[:=]\s*)([\"']?)([^\s,;\"'}]+)\2"
)
_SECRET_LABEL = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?key|token|password|passwd)\s+[A-Za-z0-9._~+/=-]{8,}"
)
_BEARER_SECRET = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_NAMED_SECRET = re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9_-]+\b")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_BASE64ISH = re.compile(r"\b[A-Za-z0-9+/]{32,}={0,2}\b")
_HIGH_ENTROPY_TOKEN = re.compile(r"\b[A-Za-z0-9_~+/=-]{32,}\b")
_DEPENDENCY_CREDENTIALS = re.compile(r"(?<=://)[^/@\s]+@")


def build_founder_bundle(
    project_root: Path,
    *,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    files, hashes = _file_manifest(root)
    dependencies = _dependency_names(root)
    env_keys = _environment_keys(root)
    environment_keys = {".env.example": env_keys} if env_keys else {}
    manifests = [
        {
            "path": item["path"],
            "kind": "lockfile" if _is_lockfile(item["path"]) else "manifest",
            "sha256": item["sha256"],
            "sizeBytes": item["sizeBytes"],
        }
        for item in hashes
        if _is_manifest(item["path"])
    ]
    dependency_evidence = {
        "packageManager": _package_manager(root),
        "productionDependencies": dependencies,
        "developmentDependencies": [],
        "lockfiles": [item["path"] for item in manifests if item["kind"] == "lockfile"],
        "npmAudit": None,
    }
    env_entries = [{"file": file, "keyNames": names} for file, names in environment_keys.items()]
    files_without_hash = [
        {"path": item["path"], "ext": Path(item["path"]).suffix, "sizeBytes": item["sizeBytes"]}
        for item in hashes
    ]
    summary = {
        "fileCount": len(files_without_hash),
        "routeCount": 0,
        "apiRouteCount": 0,
        "envKeyCount": len(env_keys),
        "workflowCount": 0,
        "hashCount": len(hashes),
    }
    secret_values_included = False
    bundle: dict[str, Any] = {
        "schemaVersion": "collector_bundle_v1",
        "metadata": {
            "collectorVersion": "wait-local-agent/1.1.1",
            "collectedAt": datetime.now(UTC).isoformat(),
            "root": "[redacted]",
            "sourceCode": False,
        },
        "privacy": {
            "source_code_included": False,
            "secret_values_included": secret_values_included,
            "upload_requires_confirmation": True,
        },
        "manifest": {
            "framework": None,
            "packageManager": dependency_evidence["packageManager"],
            "fileTree": files_without_hash,
            "manifests": manifests,
            "routes": [],
            "apiRoutes": [],
            "envKeyNames": env_keys,
            "tests": {"jestConfig": [], "vitestConfig": [], "pytestIni": False},
            "ci": {"githubWorkflows": []},
            "dependencies": dependency_evidence,
            "scannerResults": {},
            "runtimeProfileReference": None,
            "gitMetadata": None,
        },
        "summary": summary,
        "signature": {"algorithm": "sha256", "sha256": "", "generatedAt": datetime.now(UTC).isoformat()},
        "files": files_without_hash,
        "manifests": manifests,
        "routes": [],
        "apiRoutes": [],
        "findings": {"items": findings or []},
        "scannerResults": {},
        "environment": {"keys": environment_keys, "entries": env_entries},
        "testing": {"jestConfig": [], "vitestConfig": [], "pytestIni": False},
        "ci": {"githubWorkflows": []},
        "dependencies": dependency_evidence,
        "hashes": hashes,
        "runtimeProfileReference": None,
        "gitMetadata": None,
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
    _validate_paths(copied)
    return _normalize_contract_bundle(copied)


def _file_manifest(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _skip_path(path, root):
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except (OSError, PermissionError):
            continue
        relative = path.relative_to(root).as_posix()
        size_bytes = path.stat().st_size
        files.append({"path": relative, "sha256": digest, "sizeBytes": size_bytes})
    return files, files.copy()


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


def _normalize_contract_bundle(raw: dict[str, Any]) -> dict[str, Any]:
    metadata_raw = raw.get("metadata")
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    source_code = metadata.get("sourceCode", False)
    if source_code is not False:
        raise PrivacyViolation("sourceCode must be false")
    normalized_metadata = {
        "collectorVersion": _string_or(metadata.get("collectorVersion"), "wait-local-agent/1.1.1"),
        "collectedAt": _string_or(metadata.get("collectedAt"), datetime.fromtimestamp(0, UTC).isoformat()),
        "root": "[redacted]",
        "sourceCode": False,
    }

    files = _normalize_files(raw.get("files"))
    hashes = _normalize_hashes(raw.get("hashes"), raw.get("files"))
    manifests = _normalize_manifests(raw.get("manifests"), hashes)
    routes = _normalize_routes(raw.get("routes"))
    api_routes = _normalize_routes(raw.get("apiRoutes"))
    environment = _normalize_environment(raw.get("environment"))
    dependencies = _normalize_dependencies(raw.get("dependencies"))
    findings = raw.get("findings") if isinstance(raw.get("findings"), dict) else {"items": raw.get("findings", [])}
    scanner_results = raw.get("scannerResults") if isinstance(raw.get("scannerResults"), dict) else {}
    testing = _normalize_testing(raw.get("testing"))
    ci = _normalize_ci(raw.get("ci"))
    env_entries = [{"file": file, "keyNames": names} for file, names in environment["keys"].items()]
    manifest = {
        "framework": _manifest_value(raw.get("manifest"), "framework"),
        "packageManager": dependencies["packageManager"],
        "fileTree": files,
        "manifests": manifests,
        "routes": [{"path": path, "kind": "page"} for path in routes],
        "apiRoutes": [{"path": path, "kind": "api"} for path in api_routes],
        "envKeyNames": sorted({name for names in environment["keys"].values() for name in names}),
        "tests": testing,
        "ci": ci,
        "dependencies": dependencies,
        "scannerResults": scanner_results,
        "runtimeProfileReference": None,
        "gitMetadata": None,
    }
    summary = {
        "fileCount": len(files),
        "routeCount": len(routes),
        "apiRouteCount": len(api_routes),
        "envKeyCount": len(manifest["envKeyNames"]),
        "workflowCount": len(ci["githubWorkflows"]),
        "hashCount": len(hashes),
    }
    signature_candidate = raw.get("signature")
    signature_raw: dict[str, Any] = signature_candidate if isinstance(signature_candidate, dict) else {}
    signature = {
        "algorithm": "sha256",
        "sha256": _string_or(signature_raw.get("sha256"), ""),
        "generatedAt": _string_or(signature_raw.get("generatedAt"), str(normalized_metadata["collectedAt"])),
    }
    privacy_candidate = raw.get("privacy")
    privacy_raw: dict[str, Any] = privacy_candidate if isinstance(privacy_candidate, dict) else {}
    if privacy_raw.get("source_code_included") is True or privacy_raw.get("secret_values_included") is True:
        raise PrivacyViolation("privacy flags must not claim source code or secret values")
    if privacy_raw.get("upload_requires_confirmation") is False:
        raise PrivacyViolation("upload_requires_confirmation must default to true")
    secret_values_included = False
    result: dict[str, Any] = {
        "schemaVersion": "collector_bundle_v1",
        "metadata": normalized_metadata,
        "privacy": {
            "source_code_included": False,
        "secret_values_included": secret_values_included,
            "upload_requires_confirmation": privacy_raw.get("upload_requires_confirmation", True) is not False,
        },
        "manifest": manifest,
        "summary": summary,
        "signature": signature,
        "files": files,
        "manifests": manifests,
        "routes": routes,
        "apiRoutes": api_routes,
        "findings": findings,
        "scannerResults": scanner_results,
        "environment": {"keys": environment["keys"], "entries": env_entries},
        "testing": testing,
        "ci": ci,
        "dependencies": dependencies,
        "hashes": hashes,
        "runtimeProfileReference": None,
        "gitMetadata": None,
    }
    return _scrub_value(result)


def _normalize_files(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    files: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            path: str = item
            ext: str = Path(path).suffix
            size: int = 0
        elif isinstance(item, dict) and isinstance(item.get("path"), str):
            path = str(item["path"])
            ext = item["ext"] if isinstance(item.get("ext"), str) else Path(path).suffix
            size = item["sizeBytes"] if isinstance(item.get("sizeBytes"), int) else 0
        else:
            continue
        files.append({"path": path, "ext": ext, "sizeBytes": size})
    return files


def _normalize_hashes(value: Any, files_value: Any) -> list[dict[str, Any]]:
    source = value if isinstance(value, list) else files_value if isinstance(files_value, list) else []
    hashes: list[dict[str, Any]] = []
    for item in source:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        digest = item.get("sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            continue
        size = item.get("sizeBytes") if isinstance(item.get("sizeBytes"), int) else 0
        hashes.append({"path": item["path"], "sha256": digest.lower(), "sizeBytes": size})
    return hashes


def _normalize_manifests(value: Any, hashes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(value, list):
        manifests: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            entry: dict[str, Any] = {
                "path": item["path"],
                "kind": "lockfile" if item.get("kind") == "lockfile" else "manifest",
            }
            if isinstance(item.get("sha256"), str):
                entry["sha256"] = item["sha256"]
            if isinstance(item.get("sizeBytes"), int):
                entry["sizeBytes"] = item["sizeBytes"]
            manifests.append(entry)
        if manifests:
            return manifests
    return [
        {
            "path": item["path"],
            "kind": "lockfile" if _is_lockfile(item["path"]) else "manifest",
            "sha256": item["sha256"],
            "sizeBytes": item["sizeBytes"],
        }
        for item in hashes
        if _is_manifest(item["path"])
    ]


def _normalize_routes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({item for item in value if isinstance(item, str) and item.startswith("/")})


def _normalize_environment(value: Any) -> dict[str, dict[str, list[str]]]:
    environment = value if isinstance(value, dict) else {}
    keys_value = environment.get("keys", {})
    if isinstance(keys_value, list):
        keys_value = {".env.example": keys_value}
    keys: dict[str, list[str]] = {}
    if isinstance(keys_value, dict):
        for file, names in keys_value.items():
            if not isinstance(file, str) or not isinstance(names, list):
                continue
            valid_names = [name for name in names if _valid_env_name(name)]
            if len(valid_names) != len(names):
                raise PrivacyViolation("environment keys must be names only")
            keys[file] = sorted(set(valid_names))
    return {"keys": keys}


def _normalize_dependencies(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        value = {"productionDependencies": value}
    dependencies = value if isinstance(value, dict) else {}
    return {
        "packageManager": (
            dependencies.get("packageManager")
            if isinstance(dependencies.get("packageManager"), str)
            else None
        ),
        "productionDependencies": _dependency_strings(dependencies.get("productionDependencies", [])),
        "developmentDependencies": _dependency_strings(dependencies.get("developmentDependencies", [])),
        "lockfiles": [item for item in dependencies.get("lockfiles", []) if isinstance(item, str)],
        "npmAudit": _scrub_value(dependencies.get("npmAudit")) if "npmAudit" in dependencies else None,
    }


def _dependency_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_scrub_string(_DEPENDENCY_CREDENTIALS.sub("", item)) for item in value if isinstance(item, str)]


def _normalize_testing(value: Any) -> dict[str, Any]:
    testing = value if isinstance(value, dict) else {}
    return {
        "jestConfig": [item for item in testing.get("jestConfig", []) if isinstance(item, str)],
        "vitestConfig": [item for item in testing.get("vitestConfig", []) if isinstance(item, str)],
        "pytestIni": testing.get("pytestIni") is True,
    }


def _normalize_ci(value: Any) -> dict[str, list[str]]:
    ci = value if isinstance(value, dict) else {}
    return {"githubWorkflows": [item for item in ci.get("githubWorkflows", []) if isinstance(item, str)]}


def _manifest_value(value: Any, key: str) -> str | None:
    manifest = value if isinstance(value, dict) else {}
    candidate = manifest.get(key)
    return candidate if isinstance(candidate, str) and candidate else None


def _string_or(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _scrub_value(value: Any, key: str = "", free_text: bool = False) -> Any:
    if isinstance(value, str):
        if key.lower() == "sha256" and re.fullmatch(r"[a-fA-F0-9]{40,64}", value):
            return value
        return _scrub_string(value, free_text=free_text)
    if isinstance(value, list):
        return [_scrub_value(item, key, free_text) for item in value]
    if isinstance(value, dict):
        return {
            str(item_key): _scrub_value(
                item,
                str(item_key),
                free_text or re.sub(r"[^a-z0-9]", "", str(item_key).lower())
                in {"findings", "scannerresults"},
            )
            for item_key, item in value.items()
        }
    return value


def _scrub_string(value: str, *, free_text: bool = False) -> str:
    def replace_assignment(match: re.Match[str]) -> str:
        return f"{match.group(0)[:-len(match.group(3))]}[redacted]"

    scrubbed = _SECRET_ASSIGNMENT.sub(replace_assignment, value)
    scrubbed = _SECRET_LABEL.sub(lambda match: f"{match.group(0).split()[0]} [redacted]", scrubbed)
    scrubbed = _BEARER_SECRET.sub("Bearer [redacted]", scrubbed)
    scrubbed = _NAMED_SECRET.sub("[redacted]", scrubbed)
    scrubbed = _AWS_ACCESS_KEY.sub("[redacted]", scrubbed)
    for match in list(_BASE64ISH.finditer(scrubbed)):
        candidate = match.group(0)
        if re.fullmatch(r"[a-fA-F0-9]{40,64}", candidate):
            continue
        if len(set(candidate)) >= 12 and _shannon_entropy(candidate) >= 4.0:
            scrubbed = scrubbed.replace(candidate, "[redacted]")
    if free_text:
        for match in list(_HIGH_ENTROPY_TOKEN.finditer(scrubbed)):
            candidate = match.group(0)
            if re.fullmatch(r"[a-fA-F0-9]{40,64}", candidate):
                continue
            if len(set(candidate)) >= 12 and _shannon_entropy(candidate) >= 4.0:
                scrubbed = scrubbed.replace(candidate, "[redacted]")
    return scrubbed


def _shannon_entropy(value: str) -> float:
    counts = {character: value.count(character) for character in set(value)}
    length = len(value)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def _is_lockfile(path: str) -> bool:
    return Path(path).name in {"pnpm-lock.yaml", "package-lock.json", "yarn.lock", "bun.lockb"}


def _is_manifest(path: str) -> bool:
    return Path(path).name in {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "requirements-dev.txt",
        "pnpm-lock.yaml",
        "package-lock.json",
        "yarn.lock",
        "bun.lockb",
    }


def _package_manager(root: Path) -> str | None:
    if (root / "package-lock.json").is_file() or (root / "package.json").is_file():
        return "npm"
    if (root / "pyproject.toml").is_file() or any(root.glob("requirements*.txt")):
        return "python"
    return None


def _validate_tree(value: Any, key: str = "", context: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            child_key = str(raw_key)
            normalized = re.sub(r"[^a-z0-9]", "", child_key.lower())
            allowed_free_text = context[-1:] in (("findings",), ("scannerresults",))
            if (normalized in _SECRET_KEYS and not allowed_free_text) or normalized in {"filebody", "sourcecontent"}:
                if context[:1] == ("environment",):
                    raise PrivacyViolation("environment may contain key names only")
                raise PrivacyViolation(f"private value is not allowed at {child_key}")
            if normalized == "sourcecode" and child is not False:
                raise PrivacyViolation("sourceCode must be false")
            _validate_tree(child, child_key, (*context, normalized))
    elif isinstance(value, list):
        for child in value:
            _validate_tree(child, key, context)


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
