from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import platform
import re
import shutil
import sys
import time
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import wait_local_agent
from wait_local_agent.api.packs.loader import load_pack_registry
from wait_local_agent.config import Settings
from wait_local_agent.connectors import list_connector_statuses
from wait_local_agent.fs_permissions import create_private_directory, write_private_bytes
from wait_local_agent.reports.renderers import REDACTED, redact_text
from wait_local_agent.security import auth_required
from wait_local_agent.store import Store

MAX_FAILED_EXECUTIONS = 20
MAX_AUDIT_EVENTS = 50
MAX_BUNDLE_ENTRIES = 16
MAX_BUNDLE_BYTES = 2 * 1024 * 1024

EXCLUDE = (
    "ticket bodies",
    "email bodies",
    "knowledge documents",
    "prompts and completions",
    "customer names",
    "user names and email addresses",
    "tenant IDs",
    "hostnames",
    "IP addresses",
    "device serial numbers",
    "customer URLs",
    "keys, passwords, tokens, certificates, and private keys",
)

_PROCESS_STARTED_AT = datetime.now(UTC)
_PROCESS_STARTED_MONOTONIC = time.monotonic()
_CORRELATION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,63}\b")
_URL_RE = re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"']+")
_IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
_IPV6_CANDIDATE_RE = re.compile(r"(?<![\w:])[0-9A-Fa-f:]{2,}(?![\w:])")
_HOSTNAME_RE = re.compile(r"(?i)(?<![\w-])(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}(?![\w-])")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b")
_LONG_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{40,}={0,2}(?![A-Za-z0-9_-])")
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z_][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|CERT|PRIVATE_KEY)"
    r"[A-Z0-9_]*)\s*=\s*([^\s,;]+)"
)
_PRIVATE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(tenant(?:_id)?|client(?:_id)?|customer(?:_id)?|user(?:_id)?|hostname|device_serial)"
    r"\s*[=:]\s*([^\s,;]+)"
)


@dataclass(frozen=True)
class DiagnosticsSummary:
    system: dict[str, object]
    configuration: dict[str, object]
    database: dict[str, object]
    connectors: list[dict[str, object]] | dict[str, object]
    packs: list[dict[str, object]] | dict[str, object]
    failed_executions: list[dict[str, object]] | dict[str, object]
    audit_events: list[dict[str, object]] | dict[str, object]
    hardening: dict[str, object]
    update_status: dict[str, object]
    correlation_ids: list[str] | dict[str, object]
    support_upload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "system": self.system,
            "configuration": self.configuration,
            "database": self.database,
            "connectors": self.connectors,
            "packs": self.packs,
            "failed_executions": self.failed_executions,
            "audit_events": self.audit_events,
            "hardening": self.hardening,
            "update_status": self.update_status,
            "correlation_ids": self.correlation_ids,
            "support_upload": self.support_upload,
        }


@dataclass(frozen=True)
class BundlePreview:
    inclusions: tuple[str, ...]
    exclusions: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"inclusions": list(self.inclusions), "exclusions": list(self.exclusions)}


@dataclass(frozen=True)
class BundleResult:
    path: Path
    sha256: str
    size_bytes: int
    entries: tuple[str, ...]


class BundleLimitError(RuntimeError):
    """Raised when a bounded support archive cannot fit within its limits."""


def valid_correlation_id(value: object) -> bool:
    return isinstance(value, str) and _CORRELATION_ID_RE.fullmatch(value) is not None and scrub_text(value) == value


def scrub_text(value: str) -> str:
    """Remove identity, network, location, and credential-shaped text."""

    scrubbed = redact_text(value)
    scrubbed = _URL_RE.sub(REDACTED, scrubbed)
    scrubbed = _EMAIL_RE.sub(REDACTED, scrubbed)
    scrubbed = _BEARER_RE.sub(REDACTED, scrubbed)
    scrubbed = _JWT_RE.sub(REDACTED, scrubbed)
    scrubbed = _AWS_KEY_RE.sub(REDACTED, scrubbed)
    scrubbed = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", scrubbed)
    scrubbed = _PRIVATE_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", scrubbed)
    scrubbed = _IPV4_RE.sub(_scrub_ipv4, scrubbed)
    scrubbed = _IPV6_CANDIDATE_RE.sub(_scrub_ipv6, scrubbed)
    scrubbed = _HOSTNAME_RE.sub(REDACTED, scrubbed)
    return _LONG_TOKEN_RE.sub(REDACTED, scrubbed)


def collect_diagnostics(settings: Settings, store: Store) -> DiagnosticsSummary:
    """Collect only explicitly approved, non-content appliance facts."""

    failed_executions = _best_effort("failed_executions", lambda: _collect_failed_executions(store))
    return DiagnosticsSummary(
        system=_best_effort("system", lambda: _collect_system(settings)),
        configuration=_best_effort("configuration", lambda: _collect_configuration(settings)),
        database=_best_effort("database", lambda: _collect_database(settings, store)),
        connectors=_best_effort("connectors", lambda: _collect_connectors(settings)),
        packs=_best_effort("packs", lambda: _collect_packs(settings)),
        failed_executions=failed_executions,
        audit_events=_best_effort("audit_events", lambda: _collect_audit_events(store)),
        hardening=_best_effort("hardening", lambda: _collect_hardening(store)),
        update_status=_best_effort("update_status", lambda: _collect_update_status(settings)),
        correlation_ids=_best_effort(
            "correlation_ids",
            lambda: _collect_correlation_ids(store),
        ),
        support_upload={
            "available": False,
            "reason": "not_available_in_this_edition",
        },
    )


def preview_support_bundle(
    settings: Settings,
    store: Store,
    *,
    case_id: str | None = None,
) -> BundlePreview:
    del settings, store, case_id
    return BundlePreview(inclusions=_section_names(), exclusions=EXCLUDE)


def build_support_bundle(
    settings: Settings,
    store: Store,
    *,
    case_id: str | None = None,
) -> BundleResult:
    summary = collect_diagnostics(settings, store)
    sections = summary.to_dict()
    entry_names = tuple(f"{name}.json" for name in sorted(sections))
    if len(entry_names) + 1 > MAX_BUNDLE_ENTRIES:
        raise BundleLimitError("support bundle entry count limit exceeded")

    entries: dict[str, bytes] = {}
    total_size = 0
    for name in entry_names:
        section_name = name.removesuffix(".json")
        content = _json_bytes(sections[section_name])
        total_size += len(content)
        if total_size > MAX_BUNDLE_BYTES:
            raise BundleLimitError("support bundle uncompressed size limit exceeded")
        entries[name] = content

    entry_manifest = [
        {"name": name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
        for name, content in sorted(entries.items())
    ]
    digest_input = "".join(f"{item['name']}\0{item['sha256']}\n" for item in entry_manifest).encode("ascii")
    overall_digest = hashlib.sha256(digest_input).hexdigest()
    manifest: dict[str, object] = {
        "format_version": 1,
        "entries": entry_manifest,
        "overall_sha256": overall_digest,
        "exclusions": list(EXCLUDE),
    }
    if case_id:
        manifest["case_reference_sha256"] = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    entries["manifest.json"] = _json_bytes(manifest)

    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, content in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            info.create_system = 3
            bundle.writestr(info, content, compresslevel=9)
    archive_bytes = archive.getvalue()
    if len(archive_bytes) > MAX_BUNDLE_BYTES:
        raise BundleLimitError("support bundle archive size limit exceeded")

    destination_dir = settings.data_path.parent.absolute() / "support-bundles"
    create_private_directory(destination_dir)
    destination = destination_dir / f"wait-support-bundle-{overall_digest[:12]}.zip"
    write_private_bytes(destination, archive_bytes, replace_existing=True)
    return BundleResult(
        path=destination,
        sha256=hashlib.sha256(archive_bytes).hexdigest(),
        size_bytes=len(archive_bytes),
        entries=tuple(sorted(entries)),
    )


def support_upload_refusal(settings: Settings, *, consent: bool) -> str:
    if not consent:
        return "explicit consent is required; support upload is not available in this edition"
    del settings
    return "support upload is not available in this edition"


def _best_effort(section: str, collector: Callable[[], Any]) -> Any:
    try:
        return collector()
    except Exception:  # noqa: BLE001 - diagnostics must report degraded sections
        return {"status": "degraded", "section": section}


def _collect_system(settings: Settings) -> dict[str, object]:
    free_disk = shutil.disk_usage(_existing_parent(settings.data_path)).free
    free_disk_mib = free_disk // (1024 * 1024)
    return {
        "version": wait_local_agent.__version__,
        "build_commit": _build_commit(),
        "update_channel_configured": bool(settings.update_channel_url),
        "os_name": platform.system() or "unknown",
        "install_mode": _install_mode(),
        "surface_mode": "api_and_cli",
        "free_disk_bytes": free_disk_mib * 1024 * 1024,
        "process_started_at": _PROCESS_STARTED_AT.isoformat(),
        "uptime_seconds": int(max(0.0, time.monotonic() - _PROCESS_STARTED_MONOTONIC)),
    }


def _collect_configuration(settings: Settings) -> dict[str, object]:
    return {
        "write_actions_enabled": settings.allow_write_actions,
        "http_probing_enabled": settings.allow_http_probing,
        "cloud_fallback_enabled": settings.allow_cloud_fallback,
        "offline_mode": settings.offline_mode,
        "llm_inference_enabled": settings.allow_llm_inference,
        "api_auth_required": auth_required(settings),
        "demo_mode": settings.demo_mode,
        "scheduler_enabled": settings.scheduler_enabled,
        "secrets_backend": settings.secrets_backend,
        "halopsa_configured": bool(
            settings.halopsa_base_url
            and settings.halopsa_client_id
            and settings.halopsa_client_secret
            and settings.halopsa_tenant
        ),
        "hudu_configured": bool(settings.hudu_base_url and settings.hudu_api_key),
        "syncro_configured": bool(settings.syncro_base_url and settings.syncro_api_token),
        "servicenow_configured": bool(
            settings.servicenow_base_url and settings.servicenow_username and settings.servicenow_password
        ),
        "autotask_configured": bool(
            settings.autotask_base_url
            and settings.autotask_username
            and settings.autotask_secret
            and settings.autotask_integration_code
        ),
        "itglue_configured": bool(settings.itglue_base_url and settings.itglue_api_key),
        "confluence_configured": bool(
            settings.confluence_base_url and settings.confluence_email and settings.confluence_api_token
        ),
        "notion_configured": bool(settings.notion_api_token and settings.notion_client_page_map_json),
        "sharepoint_configured": bool(settings.sharepoint_base_url and settings.sharepoint_access_token),
        "m365_configured": bool(settings.m365_graph_base_url and settings.m365_access_token),
        "paths": {
            "data_file": _path_status(settings.data_path),
            "document_root": _path_status(settings.allowed_doc_root),
            "vault_directory": _path_status(settings.vault_path),
            "log_directory": _path_status(_log_directory(settings)),
        },
    }


def _collect_database(settings: Settings, store: Store) -> dict[str, object]:
    del settings
    with store._connect() as connection:  # noqa: SLF001 - bounded read-only diagnostics
        row = connection.execute("select max(version) from schema_migrations").fetchone()
        integrity_row = connection.execute("pragma integrity_check").fetchone()
    return {
        "schema_version": int(row[0]) if row and row[0] is not None else None,
        "integrity_check": str(integrity_row[0]) if integrity_row else "unknown",
    }


def _collect_connectors(settings: Settings) -> list[dict[str, object]]:
    return [{"id": connector.id, "readiness": connector.status} for connector in list_connector_statuses(settings)]


def _collect_packs(settings: Settings) -> list[dict[str, object]]:
    return [
        {
            "id": status.name,
            "version": status.version,
            "signature_status": "not_recorded",
        }
        for status in load_pack_registry(settings).statuses
    ]


def _collect_failed_executions(store: Store) -> list[dict[str, object]]:
    failed = store.list_execution_runs(status="failed")[:MAX_FAILED_EXECUTIONS]
    output: list[dict[str, object]] = []
    for run in failed:
        steps = store.list_execution_steps(run.id or 0)
        output.append(
            {
                "run_kind": run.run_kind,
                "status": run.status,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "trigger_source": scrub_text(run.trigger_source),
                "steps": [
                    {
                        "kind": scrub_text(step.kind),
                        "name": scrub_text(step.name),
                        "status": step.status,
                        "error": scrub_text(step.error_detail),
                    }
                    for step in steps
                    if step.status == "failed" or step.error_detail
                ],
            }
        )
    return output


def _collect_audit_events(store: Store) -> list[dict[str, object]]:
    return [
        {"type": event.event_type, "status": event.status} for event in store.list_event_history()[:MAX_AUDIT_EVENTS]
    ]


def _collect_hardening(store: Store) -> dict[str, object]:
    runs = store.list_hardening_runs()
    if not runs:
        return {"status": "not_run"}
    run = runs[0]
    return {
        "status": run.status,
        "expected_check_count": run.expected_check_count,
        "result_count": run.result_count,
        "checks": [{"id": result.check_id, "status": result.status} for result in run.results],
    }


def _collect_update_status(settings: Settings) -> dict[str, object]:
    if settings.offline_mode:
        return {"status": "not_checked", "detail": "offline", "configured": bool(settings.update_channel_url)}
    if not settings.update_channel_url:
        return {"status": "not_checked", "detail": "disabled", "configured": False}
    if not settings.update_pubkeys:
        return {"status": "not_checked", "detail": "verification_not_configured", "configured": True}
    return {"status": "not_checked", "detail": "ready", "configured": True}


def _collect_correlation_ids(store: Store) -> list[str]:
    correlation_ids: list[str] = []
    for run in store.list_execution_runs()[:MAX_FAILED_EXECUTIONS]:
        try:
            metadata = json.loads(run.metadata_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        candidate = metadata.get("correlation_id")
        if valid_correlation_id(candidate) and candidate not in correlation_ids:
            correlation_ids.append(str(candidate))
    return correlation_ids


def _path_status(path: Path) -> dict[str, bool]:
    exists = path.exists()
    writable_target = path if exists else _existing_parent(path)
    return {"exists": exists, "writable": os.access(writable_target, os.W_OK)}


def _existing_parent(path: Path) -> Path:
    candidate = path if path.is_dir() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _log_directory(settings: Settings) -> Path:
    configured = settings.log_dir
    if configured is None:
        if settings.data_path.is_absolute():
            return settings.data_path.parent / "logs"
        configured_root = os.getenv("LOCALAPPDATA") if os.name == "nt" else os.getenv("XDG_STATE_HOME")
        if configured_root:
            state_root = Path(configured_root)
        elif os.name == "nt":
            state_root = Path.home() / "AppData" / "Local"
        else:
            state_root = Path.home() / ".local" / "state"
        data_identity = hashlib.sha256(str(settings.data_path).encode("utf-8")).hexdigest()[:12]
        return state_root / "wait-local-agent" / data_identity / "logs"
    return configured.absolute() if configured.is_absolute() else (settings.data_path.parent / configured).absolute()


def _install_mode() -> str:
    if getattr(sys, "frozen", False):
        return "desktop"
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return "docker"
    return "cli"


def _build_commit() -> str | None:
    current = Path(__file__).resolve()
    for parent in tuple(current.parents)[:7]:
        marker = parent / ".git"
        if not marker.exists():
            continue
        try:
            git_dir = marker
            if marker.is_file():
                text = marker.read_text(encoding="utf-8", errors="replace").strip()
                if not text.startswith("gitdir: "):
                    return None
                git_dir = (parent / text.removeprefix("gitdir: ")).resolve()
            head = (git_dir / "HEAD").read_text(encoding="ascii", errors="replace").strip()
            if re.fullmatch(r"[0-9a-f]{40,64}", head):
                return head
            if not head.startswith("ref: "):
                return None
            ref_name = head.removeprefix("ref: ")
            ref_path = git_dir / ref_name
            if not ref_path.exists() and (git_dir / "commondir").exists():
                common = (git_dir / (git_dir / "commondir").read_text(encoding="utf-8").strip()).resolve()
                ref_path = common / ref_name
            if ref_path.exists():
                commit = ref_path.read_text(encoding="ascii", errors="replace").strip()
                return commit if re.fullmatch(r"[0-9a-f]{40,64}", commit) else None
            return None
        except OSError:
            return None
    return None


def _section_names() -> tuple[str, ...]:
    return tuple(sorted(DiagnosticsSummary.__dataclass_fields__))


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _scrub_ipv4(match: re.Match[str]) -> str:
    try:
        ipaddress.ip_address(match.group(0))
    except ValueError:
        return match.group(0)
    return REDACTED


def _scrub_ipv6(match: re.Match[str]) -> str:
    candidate = match.group(0)
    if ":" not in candidate:
        return candidate
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return candidate
    return REDACTED
