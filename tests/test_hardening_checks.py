from __future__ import annotations

import ast
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from wait_local_agent.reports.builders import build_appliance_hardening_report
from wait_local_agent.reports.hardening_checks import (
    CheckResult,
    HardeningCheck,
    HardeningCheckRegistry,
    HardeningContext,
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


def test_check_module_does_not_import_or_call_mutation_helpers() -> None:
    source = Path(__file__).parents[1] / "src/wait_local_agent/reports/hardening_checks.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    forbidden = {"subprocess", "shutil", "write_text", "write_bytes", "unlink", "chmod"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert not forbidden.intersection(names | attributes)
