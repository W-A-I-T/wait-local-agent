from __future__ import annotations

import ast
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from wait_local_agent import platform_support
from wait_local_agent.reports.builders import build_appliance_hardening_report
from wait_local_agent.reports.hardening_checks import (
    CheckResult,
    HardeningCheck,
    HardeningCheckRegistry,
    HardeningContext,
    HardeningRunRecord,
    _check_backup_recency,
    _check_data_dir,
    _check_store_permissions,
    _check_vault,
    _mode,
    _path_evidence,
    run_hardening_checks,
)
from wait_local_agent.store import Store


def test_default_hardening_run_persists_all_checks_without_secret_values(settings) -> None:
    settings = replace(settings, vault_path=settings.data_path.parent / "vault")
    store = Store(settings.data_path)
    store.add_audit_event("test", "fixture", "fixture event")
    vault_key = settings.vault_path / "vault.key"
    vault_key.parent.mkdir(parents=True)
    vault_key.write_bytes(b"test-key")
    os.chmod(vault_key, 0o600)
    backup = settings.data_path.parent / "backup.db"
    backup.write_bytes(b"fixture")
    context = HardeningContext.from_settings(
        settings,
        store=store,
        backup_paths=(backup,),
        audit_event_count=1,
        now=datetime.now(UTC),
    )

    run = run_hardening_checks(context)

    assert run.status == "completed"
    assert run.result_count == 8
    assert all(result.status in {"passed", "failed", "not_applicable", "error"} for result in run.results)
    sections, metadata = build_appliance_hardening_report(store, run.id)
    assert metadata["evidence_status"] == "completed"
    assert len(sections[0].findings) == 8
    assert "test-key" not in str(sections)


def test_check_exception_is_persisted_and_report_is_partial(settings) -> None:
    store = Store(settings.data_path)
    registry = HardeningCheckRegistry()

    def broken_check(_: HardeningContext) -> CheckResult:
        raise RuntimeError("fixture failure")

    registry.register(HardeningCheck("broken-check", "Broken check", "api", "high", broken_check))
    run = run_hardening_checks(
        HardeningContext(store=store, now=datetime.now(UTC)),
        registry=registry,
    )

    assert run.status == "partial"
    assert run.results[0].status == "error"
    assert run.results[0].evidence == {"error_type": "RuntimeError"}
    _, metadata = build_appliance_hardening_report(store, run.id)
    assert metadata["evidence_status"] == "partial"


def test_registry_rejects_duplicate_and_non_lowercase_ids() -> None:
    registry = HardeningCheckRegistry()
    check = HardeningCheck("safe-check", "Safe", "api", "low", lambda _: CheckResult("passed"))
    registry.register(check)
    try:
        registry.register(check)
        raise AssertionError("duplicate check ids must be rejected")
    except ValueError as exc:
        assert "already registered" in str(exc)
    try:
        registry.register(HardeningCheck("Unsafe", "Unsafe", "api", "low", lambda _: CheckResult("passed")))
        raise AssertionError("uppercase check ids must be rejected")
    except ValueError as exc:
        assert "lowercase" in str(exc)


def test_registry_clear_and_missing_lookup() -> None:
    registry = HardeningCheckRegistry()
    registry.register(HardeningCheck("safe-check", "Safe", "api", "low", lambda _: CheckResult("passed")))
    registry.clear()
    assert registry.list() == []

    try:
        registry.get("missing-check")
        raise AssertionError("missing check ids must be rejected")
    except KeyError as exc:
        assert "missing-check is not registered" in str(exc)


def test_hardening_checks_require_persistence_store() -> None:
    try:
        run_hardening_checks(HardeningContext())
        raise AssertionError("hardening checks must require persistence")
    except ValueError as exc:
        assert "require a Store" in str(exc)


def test_hardening_checks_reject_unpersisted_run(settings, monkeypatch) -> None:
    store = Store(settings.data_path)
    monkeypatch.setattr(
        store,
        "create_hardening_run",
        lambda **_kwargs: HardeningRunRecord(None, "running", "start", "", 0, 0),
    )

    try:
        run_hardening_checks(HardeningContext(store=store))
        raise AssertionError("unpersisted hardening runs must be rejected")
    except RuntimeError as exc:
        assert "was not persisted" in str(exc)


def test_hardening_path_edge_evidence_and_missing_backup(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    assert _mode(missing) is None
    permission_model = (
        "posix" if platform_support.posix_permissions_supported() else "windows-acl"
    )
    assert _path_evidence(None) == {
        "path": None,
        "exists": False,
        "permission_model": permission_model,
    }
    expected_vault_status = (
        "failed" if platform_support.posix_permissions_supported() else "not_applicable"
    )
    assert _check_vault(HardeningContext()).status == expected_vault_status

    result = _check_backup_recency(HardeningContext(backup_paths=(missing,)))
    assert result.status == "failed"
    assert result.evidence["backups"] == []


def test_permission_checks_are_not_applicable_without_posix_mode_bits(
    settings, monkeypatch
) -> None:
    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)
    context = HardeningContext(
        store_path=settings.data_path,
        data_dir=settings.data_path.parent,
        vault_key_path=settings.vault_path / "vault.key",
    )

    assert _check_vault(context).status == "not_applicable"
    assert _check_store_permissions(context).status == "not_applicable"
    assert _check_data_dir(context).status == "not_applicable"
    assert _check_vault(context).remediation_hint is None
    assert _check_store_permissions(context).remediation_hint is None
    assert _check_data_dir(context).remediation_hint is None


def test_non_posix_hardening_run_remains_completed_with_eight_results(
    settings, monkeypatch
) -> None:
    store = Store(settings.data_path)
    monkeypatch.setattr(platform_support, "posix_permissions_supported", lambda: False)

    run = run_hardening_checks(
        HardeningContext.from_settings(settings, store=store, audit_event_count=1)
    )

    assert run.status == "completed"
    assert run.result_count == 8
    assert {result.status for result in run.results} >= {"not_applicable"}


def test_check_module_does_not_import_or_call_mutation_helpers() -> None:
    source = Path(__file__).parents[1] / "src/wait_local_agent/reports/hardening_checks.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    forbidden = {"subprocess", "shutil", "write_text", "write_bytes", "unlink", "chmod"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not forbidden.intersection(names | attributes)
