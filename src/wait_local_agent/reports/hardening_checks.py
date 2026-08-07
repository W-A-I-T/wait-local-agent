from __future__ import annotations

import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from wait_local_agent.config import Settings
    from wait_local_agent.store import Store

CheckStatus = Literal["passed", "failed", "not_applicable", "error"]
HardeningRunStatus = Literal["running", "completed", "partial"]


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    evidence: dict[str, Any] = field(default_factory=dict)
    remediation_hint: str | None = None


@dataclass(frozen=True)
class HardeningContext:
    """Read-only, secret-free inputs made available to hardening checks."""

    config: Mapping[str, object] = field(default_factory=dict)
    store_path: Path | None = None
    data_dir: Path | None = None
    vault_key_path: Path | None = None
    backup_paths: tuple[Path, ...] = ()
    audit_event_count: int = 0
    audit_log_path: Path | None = None
    rbac_roles: tuple[str, ...] = ()
    backup_max_age_days: int = 7
    now: datetime | None = None
    store: Store | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        store: Store | None = None,
        backup_paths: tuple[Path, ...] = (),
        audit_event_count: int = 0,
        now: datetime | None = None,
    ) -> HardeningContext:
        # Only booleans, labels, and public configuration are copied. Secret
        # values in Settings never enter the check context or evidence.
        config = {
            "api_auth_configured": bool(settings.api_token or settings.admin_token),
            "update_channel_url_configured": bool(settings.update_channel_url),
            "update_pubkeys_configured": bool(settings.update_pubkeys),
        }
        roles = tuple(
            role
            for role, configured in (
                ("admin", bool(settings.admin_token or settings.api_token)),
                ("technician", bool(settings.tech_token)),
                ("viewer", bool(settings.viewer_token)),
            )
            if configured
        )
        return cls(
            config=config,
            store_path=settings.data_path,
            data_dir=settings.data_path.parent,
            vault_key_path=settings.vault_path / "vault.key",
            backup_paths=backup_paths,
            audit_event_count=audit_event_count,
            audit_log_path=settings.data_path,
            rbac_roles=roles,
            now=now,
            store=store,
        )


@dataclass(frozen=True)
class HardeningCheck:
    check_id: str
    title: str
    scope: str
    severity: str
    check_fn: Callable[[HardeningContext], CheckResult]


@dataclass(frozen=True)
class HardeningCheckResultRecord:
    id: int | None
    run_id: int
    check_id: str
    title: str
    scope: str
    severity: str
    status: CheckStatus
    evidence: dict[str, Any]
    remediation_hint: str | None


@dataclass(frozen=True)
class HardeningRunRecord:
    id: int | None
    status: HardeningRunStatus
    started_at: str
    completed_at: str
    expected_check_count: int
    result_count: int
    results: list[HardeningCheckResultRecord] = field(default_factory=list)


class HardeningCheckRegistry:
    def __init__(self) -> None:
        self._checks: dict[str, HardeningCheck] = {}

    def register(self, check: HardeningCheck) -> None:
        if check.check_id != check.check_id.lower() or not check.check_id.strip():
            raise ValueError("hardening check id must be lowercase id text")
        if check.check_id in self._checks:
            raise ValueError(f"hardening check {check.check_id} is already registered")
        self._checks[check.check_id] = check

    def clear(self) -> None:
        self._checks.clear()

    def list(self) -> list[HardeningCheck]:
        return [self._checks[key] for key in sorted(self._checks)]

    def get(self, check_id: str) -> HardeningCheck:
        try:
            return self._checks[check_id]
        except KeyError as exc:
            raise KeyError(f"hardening check {check_id} is not registered") from exc


def run_hardening_checks(
    context: HardeningContext,
    *,
    store: Store | None = None,
    registry: HardeningCheckRegistry | None = None,
) -> HardeningRunRecord:
    persistence_store = store or context.store
    if persistence_store is None:
        raise ValueError("hardening checks require a Store for run persistence")
    active_registry = registry or default_registry
    checks = active_registry.list()
    started_at = _now(context).isoformat()
    run = persistence_store.create_hardening_run(
        expected_check_count=len(checks),
        started_at=started_at,
    )
    if run.id is None:
        raise RuntimeError("hardening run was not persisted")

    for check in checks:
        try:
            result = check.check_fn(context)
        except Exception as exc:  # A broken check must remain visible in evidence.
            result = CheckResult(
                status="error",
                evidence={"error_type": type(exc).__name__},
                remediation_hint="Inspect the check error and rerun the hardening checks.",
            )
        persistence_store.add_hardening_check_result(
            run_id=run.id,
            check_id=check.check_id,
            title=check.title,
            scope=check.scope,
            severity=check.severity,
            result=result,
        )

    results = persistence_store.list_hardening_check_results(run.id)
    status: HardeningRunStatus = (
        "partial"
        if len(results) != len(checks) or any(item.status == "error" for item in results)
        else "completed"
    )
    return persistence_store.complete_hardening_run(run.id, status, _now(context).isoformat())


def _config_value(context: HardeningContext, key: str, default: object = None) -> object:
    return context.config.get(key, default)


def _mode(path: Path) -> int | None:
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except OSError:
        return None


def _path_evidence(path: Path | None) -> dict[str, object]:
    if path is None:
        return {"path": None, "exists": False}
    mode = _mode(path)
    return {"path": str(path), "exists": mode is not None, "permission_bits": oct(mode) if mode is not None else None}


def _check_api_auth(context: HardeningContext) -> CheckResult:
    configured = bool(_config_value(context, "api_auth_configured", False))
    return CheckResult(
        status="passed" if configured else "failed",
        evidence={"api_auth_configured": configured},
        remediation_hint=None if configured else "Configure an API or admin authentication token.",
    )


def _check_rbac(context: HardeningContext) -> CheckResult:
    configured = {role.lower() for role in context.rbac_roles}
    expected = {"admin", "technician", "viewer"}
    missing = sorted(expected - configured)
    return CheckResult(
        status="passed" if not missing else "failed",
        evidence={"configured_roles": sorted(configured), "missing_roles": missing},
        remediation_hint=None if not missing else "Configure tokens for all appliance RBAC roles.",
    )


def _check_vault(context: HardeningContext) -> CheckResult:
    evidence = _path_evidence(context.vault_key_path)
    permission_bits = _mode(context.vault_key_path) if context.vault_key_path else None
    passed = permission_bits == 0o600
    return CheckResult(
        status="passed" if passed else "failed",
        evidence={**evidence, "required_permission_bits": "0o600"},
        remediation_hint=None if passed else "Initialize the vault and restrict vault.key to owner read/write.",
    )


def _check_store_permissions(context: HardeningContext) -> CheckResult:
    evidence = _path_evidence(context.store_path)
    permission_bits = _mode(context.store_path) if context.store_path else None
    passed = permission_bits is not None and permission_bits & 0o077 == 0
    return CheckResult(
        status="passed" if passed else "failed",
        evidence=evidence,
        remediation_hint=None if passed else "Restrict the SQLite state file to the account running WAIT.",
    )


def _check_backup_recency(context: HardeningContext) -> CheckResult:
    now = _now(context)
    cutoff = now - timedelta(days=max(context.backup_max_age_days, 1))
    candidates: list[dict[str, object]] = []
    for path in context.backup_paths:
        try:
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        candidates.append({"path": str(path), "modified_at": modified.isoformat()})
    recent = [item for item in candidates if datetime.fromisoformat(str(item["modified_at"])) >= cutoff]
    passed = bool(recent)
    return CheckResult(
        status="passed" if passed else "failed",
        evidence={"max_age_days": context.backup_max_age_days, "backups": candidates},
        remediation_hint=None if passed else "Create a backup newer than the configured recency window.",
    )


def _check_update_channel(context: HardeningContext) -> CheckResult:
    url_configured = bool(_config_value(context, "update_channel_url_configured", False))
    keys_configured = bool(_config_value(context, "update_pubkeys_configured", False))
    passed = url_configured and keys_configured
    return CheckResult(
        status="passed" if passed else "failed",
        evidence={"channel_configured": url_configured, "pinned_keys_configured": keys_configured},
        remediation_hint=None if passed else "Configure an update channel with pinned public keys.",
    )


def _check_audit_log(context: HardeningContext) -> CheckResult:
    path_evidence = _path_evidence(context.audit_log_path)
    writable = bool(context.audit_log_path and os.access(context.audit_log_path, os.W_OK))
    passed = context.audit_event_count > 0 and writable
    return CheckResult(
        status="passed" if passed else "failed",
        evidence={**path_evidence, "event_count": context.audit_event_count, "writable": writable},
        remediation_hint=None if passed else "Ensure the audit store is writable and contains audit events.",
    )


def _check_data_dir(context: HardeningContext) -> CheckResult:
    evidence = _path_evidence(context.data_dir)
    mode = _mode(context.data_dir) if context.data_dir else None
    passed = mode is not None and mode & 0o004 == 0
    return CheckResult(
        status="passed" if passed else "failed",
        evidence=evidence,
        remediation_hint=None if passed else "Restrict the data directory from world read access.",
    )


default_registry = HardeningCheckRegistry()
default_registry.register(
    HardeningCheck("api-auth-token", "API authentication token", "api", "high", _check_api_auth)
)
default_registry.register(HardeningCheck("rbac-roles", "RBAC roles present", "api", "high", _check_rbac))
default_registry.register(
    HardeningCheck("vault-permissions", "Vault initialized and protected", "secrets", "high", _check_vault)
)
default_registry.register(
    HardeningCheck("sqlite-permissions", "SQLite file permissions", "storage", "high", _check_store_permissions)
)
default_registry.register(HardeningCheck("backup-recency", "Backup recency", "storage", "high", _check_backup_recency))
default_registry.register(
    HardeningCheck("update-channel-pinned", "Update channel pinned", "updates", "medium", _check_update_channel)
)
default_registry.register(
    HardeningCheck("audit-log", "Audit log writable and non-empty", "storage", "high", _check_audit_log)
)
default_registry.register(
    HardeningCheck(
        "data-directory-permissions",
        "Data directory is not world-readable",
        "storage",
        "high",
        _check_data_dir,
    )
)


def _now(context: HardeningContext) -> datetime:
    current = context.now or datetime.now(UTC)
    return current if current.tzinfo is not None else current.replace(tzinfo=UTC)
