from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import zipfile
from collections.abc import Iterator
from dataclasses import fields, replace
from pathlib import Path
from types import SimpleNamespace

import anyio.to_thread
import pytest
from httpx import ASGITransport, AsyncClient
from typer.testing import CliRunner

import wait_local_agent
import wait_local_agent.api.server_entry as server_entry
import wait_local_agent.cli as cli_module
import wait_local_agent.diagnostics as diagnostics_module
from tests.support import ensure_test_client
from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app as cli_app
from wait_local_agent.config import Settings, load_settings
from wait_local_agent.diagnostics import (
    BundleLimitError,
    build_support_bundle,
    collect_diagnostics,
    preview_support_bundle,
    scrub_text,
)
from wait_local_agent.models import Ticket
from wait_local_agent.observability import ExecutionRecorder
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store, latest_declared_schema_version
from wait_local_agent.structured_logging import (
    PrivateRotatingFileHandler,
    ScrubbedJsonFormatter,
    configure_structured_logging,
)
from wait_local_agent.workflows import run_workflow_template

# Assembled at runtime so the AWS-style literal never appears in source, where
# secret scanners (gitleaks aws-access-token) would flag it as a real key.
FAKE_AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _archive_entries(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _secure_settings(settings: Settings) -> Settings:
    return replace(
        settings,
        demo_mode=False,
        admin_token="bootstrap-admin-token",
        tech_token="bootstrap-technician-token",
        viewer_token="bootstrap-viewer-token",
        scheduler_enabled=False,
        client_id="appliance-client",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def cleanup_structured_logging_handlers() -> Iterator[None]:
    root = logging.getLogger()
    original_handlers = tuple(root.handlers)
    yield
    for handler in tuple(root.handlers):
        if isinstance(handler, PrivateRotatingFileHandler) and all(
            handler is not original for original in original_handlers
        ):
            root.removeHandler(handler)
            handler.close()


def _inline_threadpool(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run_sync_inline(function, *args, **kwargs):
        del kwargs
        return function(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", run_sync_inline)


def test_summary_uses_explicit_safe_shape_and_authoritative_version(settings: Settings) -> None:
    settings = replace(settings, log_dir=settings.data_path.parent / "private-logs")
    store = Store(settings.data_path)
    summary = collect_diagnostics(settings, store).to_dict()

    system = summary["system"]
    configuration = summary["configuration"]
    assert isinstance(system, dict)
    assert isinstance(configuration, dict)
    assert system["version"] == wait_local_agent.__version__
    assert summary["database"] == {
        "schema_version": latest_declared_schema_version(store),
        "integrity_check": "ok",
    }
    assert set(configuration) == {
        "write_actions_enabled",
        "http_probing_enabled",
        "cloud_fallback_enabled",
        "offline_mode",
        "llm_inference_enabled",
        "api_auth_required",
        "demo_mode",
        "scheduler_enabled",
        "secrets_backend",
        "halopsa_configured",
        "hudu_configured",
        "syncro_configured",
        "servicenow_configured",
        "autotask_configured",
        "itglue_configured",
        "confluence_configured",
        "notion_configured",
        "sharepoint_configured",
        "m365_configured",
        "paths",
    }
    path_facts = configuration["paths"]
    assert isinstance(path_facts, dict)
    assert all(set(facts) == {"exists", "writable"} for facts in path_facts.values())
    rendered = json.dumps(summary, sort_keys=True)
    assert str(settings.data_path) not in rendered
    assert str(settings.log_dir) not in rendered


def test_application_version_matches_package_version(settings: Settings) -> None:
    assert create_app(settings).version == wait_local_agent.__version__


@pytest.mark.parametrize(
    "value, literal",
    [
        ("mail operator@example.invalid", "operator@example.invalid"),
        ("source 192.0.2.44", "192.0.2.44"),
        ("source 2001:db8::44", "2001:db8::44"),
        ("open https://name:pass@host.example.invalid/private", "host.example.invalid"),
        ("Authorization Bearer abcdefghijklmnopqrstuvwxyz", "abcdefghijklmnopqrstuvwxyz"),
        ("API_KEY=sensitive-value", "sensitive-value"),
        ("tenant_id=tenant-private", "tenant-private"),
        (FAKE_AWS_KEY, FAKE_AWS_KEY),
        ("gAAAAABmVeryLongFernetStyleTokenPayload_012345678901", "gAAAAABmVeryLongFernetStyleTokenPayload"),
    ],
)
def test_scrubber_removes_sensitive_literals(value: str, literal: str) -> None:
    assert literal not in scrub_text(value)


def test_bundle_manifest_hashes_entries_and_is_deterministic(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(settings.data_path)
    monotonic_values = iter((100.1, 101.1))
    monkeypatch.setattr(diagnostics_module, "_PROCESS_STARTED_MONOTONIC", 100.0)
    monkeypatch.setattr(diagnostics_module.time, "monotonic", lambda: next(monotonic_values))

    first = build_support_bundle(settings, store, case_id="case-private-44")
    first_bytes = first.path.read_bytes()
    first_archive_entries = _archive_entries(first.path)
    first_entries = dict(first_archive_entries)
    first_manifest = json.loads(first_entries.pop("manifest.json"))
    second = build_support_bundle(settings, store, case_id="case-private-44")
    second_archive_entries = _archive_entries(second.path)
    entries = dict(second_archive_entries)
    manifest = json.loads(entries.pop("manifest.json"))

    assert set(first_archive_entries) == set(second_archive_entries)
    first_system = json.loads(first_entries["system.json"])
    second_system = json.loads(entries["system.json"])
    assert "uptime_seconds" in first_system
    assert "uptime_seconds" in second_system
    assert first_system["uptime_seconds"] == 0
    assert second_system["uptime_seconds"] == 1
    # uptime_seconds is excluded because it advances between collections;
    # process_started_at is captured once at process start, and free_disk_bytes
    # is rounded to MiB, so both remain part of the stable system subset.
    stable_first_system = {key: value for key, value in first_system.items() if key != "uptime_seconds"}
    stable_second_system = {key: value for key, value in second_system.items() if key != "uptime_seconds"}
    assert stable_first_system == stable_second_system

    assert {
        name: hashlib.sha256(content).hexdigest()
        for name, content in first_entries.items()
        if name != "system.json"
    } == {
        name: hashlib.sha256(content).hexdigest()
        for name, content in entries.items()
        if name != "system.json"
    }
    assert first_manifest["overall_sha256"] != manifest["overall_sha256"]
    assert first.sha256 == hashlib.sha256(first_bytes).hexdigest()
    assert second.entries == tuple(sorted((*entries, "manifest.json")))

    first_expected = []
    for name, content in sorted(first_entries.items()):
        first_expected.append(
            {"name": name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
        )
    assert first_manifest["entries"] == first_expected
    first_digest_input = "".join(
        f"{item['name']}\0{item['sha256']}\n" for item in first_expected
    ).encode("ascii")
    assert first_manifest["overall_sha256"] == hashlib.sha256(first_digest_input).hexdigest()

    second_expected = []
    for name, content in sorted(entries.items()):
        second_expected.append(
            {"name": name, "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}
        )
    assert manifest["entries"] == second_expected
    digest_input = "".join(
        f"{item['name']}\0{item['sha256']}\n" for item in second_expected
    ).encode("ascii")
    assert manifest["overall_sha256"] == hashlib.sha256(digest_input).hexdigest()
    assert manifest["case_reference_sha256"] == hashlib.sha256(b"case-private-44").hexdigest()
    assert "case-private-44" not in json.dumps(manifest)


def test_preview_writes_nothing_and_lists_inclusions_and_exclusions(settings: Settings) -> None:
    store = Store(settings.data_path)
    before = set(settings.data_path.parent.iterdir())
    preview = preview_support_bundle(settings, store, case_id="case-1").to_dict()

    assert set(preview) == {"inclusions", "exclusions"}
    inclusions = preview["inclusions"]
    exclusions = preview["exclusions"]
    assert isinstance(inclusions, list)
    assert isinstance(exclusions, list)
    assert "system" in inclusions
    assert "ticket bodies" in exclusions
    assert set(settings.data_path.parent.iterdir()) == before


def test_bundle_records_degraded_section_when_collector_fails(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_: Settings) -> list[dict[str, object]]:
        raise OSError("collector unavailable")

    monkeypatch.setattr(diagnostics_module, "_collect_connectors", fail)
    result = build_support_bundle(settings, Store(settings.data_path))
    payload = json.loads(_archive_entries(result.path)["connectors.json"])
    assert payload == {"section": "connectors", "status": "degraded"}


def test_bundle_enforces_entry_and_size_caps(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store(settings.data_path)
    monkeypatch.setattr(diagnostics_module, "MAX_BUNDLE_ENTRIES", 1)
    with pytest.raises(BundleLimitError, match="entry count"):
        build_support_bundle(settings, store)

    monkeypatch.setattr(diagnostics_module, "MAX_BUNDLE_ENTRIES", 16)
    monkeypatch.setattr(diagnostics_module, "MAX_BUNDLE_BYTES", 1)
    with pytest.raises(BundleLimitError, match="size"):
        build_support_bundle(settings, store)

    monkeypatch.setattr(diagnostics_module, "MAX_BUNDLE_BYTES", 100)
    monkeypatch.setattr(diagnostics_module, "_json_bytes", lambda _: b"")
    with pytest.raises(BundleLimitError, match="archive size"):
        build_support_bundle(settings, store)


def test_bundle_never_contains_seeded_content_or_secret_config_values(settings: Settings) -> None:
    secret_updates: dict[str, object] = {}
    secret_markers = ("token", "secret", "password", "api_key", "private_key", "license_key", "credential")
    for field in fields(settings):
        if (
            field.name != "secrets_backend"
            and isinstance(getattr(settings, field.name), str)
            and any(marker in field.name for marker in secret_markers)
        ):
            secret_updates[field.name] = f"LEAK_{field.name.upper()}_VALUE"
    tenant_id = "tenant-private-9921"
    email = "private.person@example.invalid"
    hostname = "device77.customer.example.invalid"
    api_key = FAKE_AWS_KEY
    fernet_token = "gAAAAABmVeryLongFernetStyleTokenPayload_012345678901"
    settings = replace(settings, **secret_updates)  # type: ignore[arg-type]
    store = Store(settings.data_path)
    ensure_test_client(store, tenant_id)
    ticket_body = f"{email} {hostname} {tenant_id} {api_key} {fernet_token}"
    store.ingest_tickets(
        [Ticket("T-PRIVATE", "Private Customer", "Private subject", ticket_body, "high", "open")],
        client_id=tenant_id,
    )
    run = store.create_execution_run(
        "workflow",
        None,
        "private-user",
        "failed",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:01:00+00:00",
        f"https://name:pass@{hostname}/run",
        client_id=tenant_id,
        metadata={"correlation_id": "safe-correlation-1", "private": ticket_body},
    )
    store.add_execution_step(
        run.id or 0,
        1,
        "tool",
        "safe step",
        "failed",
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:01:00+00:00",
        "",
        "",
        "{}",
        "{}",
        f"email={email} hostname={hostname} tenant_id={tenant_id} API_KEY={api_key} token={fernet_token}",
    )
    store.add_audit_event("private.event", tenant_id, ticket_body, client_id=tenant_id)

    result = build_support_bundle(settings, store)
    combined = b"\n".join(_archive_entries(result.path).values()).decode("utf-8")
    forbidden = [ticket_body, email, hostname, tenant_id, api_key, fernet_token, "Private Customer", "private-user"]
    forbidden.extend(str(value) for value in secret_updates.values())
    assert [literal for literal in forbidden if literal in combined] == []
    assert "safe-correlation-1" in combined
    assert "private.event" in combined


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/diagnostics/summary", None),
        ("post", "/diagnostics/bundle/preview", {}),
        ("post", "/diagnostics/bundle", {}),
    ],
)
@pytest.mark.anyio
async def test_diagnostics_routes_enforce_appliance_admin_scope(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    payload: dict[str, object] | None,
) -> None:
    _inline_threadpool(monkeypatch)
    secure = _secure_settings(settings)
    store = Store(secure.data_path)
    ensure_test_client(store, "bound-client")
    store.create_principal("bound-admin", kind="staff")
    store.add_principal_credential("bound-admin", "bound-admin-token")
    store.add_principal_client_role("bound-admin", "bound-client", "admin")
    async with AsyncClient(transport=ASGITransport(app=create_app(secure)), base_url="http://testserver") as client:
        assert (await client.request(method, path, json=payload)).status_code == 401
        assert (await client.request(method, path, headers=_auth("invalid-token"), json=payload)).status_code == 401
        assert (
            await client.request(method, path, headers=_auth("bootstrap-viewer-token"), json=payload)
        ).status_code == 403
        assert (
            await client.request(method, path, headers=_auth("bootstrap-technician-token"), json=payload)
        ).status_code == 403
        assert (
            await client.request(method, path, headers=_auth("bound-admin-token"), json=payload)
        ).status_code == 403
        response = await client.request(method, path, headers=_auth("bootstrap-admin-token"), json=payload)
        assert response.status_code == 200
        if path == "/diagnostics/bundle":
            assert response.headers["content-type"] == "application/zip"
            assert len(response.headers["x-support-bundle-sha256"]) == 64


@pytest.mark.anyio
async def test_upload_route_refuses_unconfigured_sender_and_audits(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inline_threadpool(monkeypatch)
    secure = _secure_settings(settings)
    application = create_app(secure)
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://testserver") as client:
        response = await client.post(
            "/diagnostics/bundle/upload",
            headers=_auth("bootstrap-admin-token"),
            json={"consent": True},
        )
    assert response.status_code == 409
    assert response.json()["detail"] == "support upload is not configured"
    assert application.state.store.list_audit_events()[-1].event_type == "support.upload_refused"


def test_upload_refusal_reasons_are_fail_closed(settings: Settings) -> None:
    refusal = diagnostics_module.support_upload_refusal
    assert refusal(settings, consent=False) == "explicit consent is required"
    assert "offline mode" in refusal(replace(settings, offline_mode=True), consent=True)
    assert "demo mode" in refusal(replace(settings, demo_mode=True), consent=True)
    assert refusal(replace(settings, demo_mode=False), consent=True) == "support upload is not configured"
    configured = replace(settings, demo_mode=False, support_upload_endpoint="https://support.invalid/upload")
    assert "not available" in refusal(configured, consent=True)


@pytest.mark.anyio
async def test_correlation_header_is_validated_and_returned(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    _inline_threadpool(monkeypatch)
    async with AsyncClient(transport=ASGITransport(app=create_app(settings)), base_url="http://testserver") as client:
        accepted = await client.get("/health", headers={"X-Correlation-ID": "case_44:step-2"})
        rejected = await client.get("/health", headers={"X-Correlation-ID": "bad\tvalue"})

    assert accepted.headers["X-Correlation-ID"] == "case_44:step-2"
    replacement = rejected.headers["X-Correlation-ID"]
    assert replacement != "bad\tvalue"
    assert diagnostics_module.valid_correlation_id(replacement)
    assert not diagnostics_module.valid_correlation_id("device.customer.example.invalid")
    assert not diagnostics_module.valid_correlation_id("192.0.2.44")


def test_structured_log_is_private_rotating_and_scrubbed(settings: Settings) -> None:
    configured = replace(settings, log_dir=settings.data_path.parent / "logs", log_max_bytes=256, log_backup_count=2)
    log_path = configure_structured_logging(configured)
    logger = logging.getLogger("diagnostics-test")
    logger.warning("contact operator@example.invalid at 192.0.2.88 API_KEY=hidden-value")
    for _ in range(12):
        logger.warning("bounded message %s", "x" * 80)
    for handler in logging.getLogger().handlers:
        handler.flush()

    rendered = "\n".join(path.read_text(encoding="utf-8") for path in log_path.parent.glob(f"{log_path.name}*"))
    assert "operator@example.invalid" not in rendered
    assert "192.0.2.88" not in rendered
    assert "hidden-value" not in rendered
    assert len(list(log_path.parent.glob(f"{log_path.name}*"))) <= 3
    if os.name != "nt":
        assert log_path.stat().st_mode & 0o777 == 0o600
        assert log_path.parent.stat().st_mode & 0o777 == 0o700


def test_log_formatter_handles_correlation_exception_and_duplicate_setup(settings: Settings) -> None:
    formatter = ScrubbedJsonFormatter()
    try:
        raise RuntimeError("contact private.person@example.invalid")
    except RuntimeError:
        record = logging.LogRecord("safe", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    record.correlation_id = "case-44"
    payload = json.loads(formatter.format(record))
    assert payload["correlation_id"] == "case-44"
    assert "private.person@example.invalid" not in payload["exception"]

    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.NOTSET)
    configured = replace(settings, log_dir=settings.data_path.parent / "duplicate-logs")
    first = configure_structured_logging(configured)
    assert configure_structured_logging(configured) == first
    root.setLevel(previous_level)


def test_logging_and_upload_configuration_from_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_LOG_DIR", str(tmp_path / "bounded-logs"))
    monkeypatch.setenv("WAIT_LOG_MAX_BYTES", "4096")
    monkeypatch.setenv("WAIT_LOG_BACKUP_COUNT", "2")
    monkeypatch.setenv("WAIT_SUPPORT_UPLOAD_ENDPOINT", "https://support.invalid/upload")
    loaded = load_settings()
    assert loaded.log_dir == tmp_path / "bounded-logs"
    assert loaded.log_max_bytes == 4096
    assert loaded.log_backup_count == 2
    assert loaded.support_upload_endpoint == "https://support.invalid/upload"


def test_default_log_directory_is_not_repo_relative(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    from wait_local_agent.structured_logging import configured_log_directory

    state_env = "LOCALAPPDATA" if os.name == "nt" else "XDG_STATE_HOME"
    monkeypatch.setenv(state_env, str(settings.data_path.parent / "state-home"))
    relative = replace(settings, data_path=Path(".wait-local-agent/state.db"), log_dir=None)
    log_dir = configured_log_directory(relative)
    assert log_dir.is_absolute()
    assert log_dir.is_relative_to(settings.data_path.parent / "state-home")
    assert diagnostics_module._log_directory(relative).is_relative_to(settings.data_path.parent / "state-home")

    monkeypatch.delenv(state_env)
    fallback = configured_log_directory(relative)
    assert fallback.is_absolute()
    assert "wait-local-agent" in fallback.parts
    assert configured_log_directory(replace(settings, log_dir=Path("relative-logs"))).is_absolute()
    assert configured_log_directory(replace(settings, log_dir=None)) == settings.data_path.parent / "logs"


def test_update_hardening_and_correlation_collectors_cover_safe_states(settings: Settings) -> None:
    assert diagnostics_module._collect_update_status(replace(settings, offline_mode=True))["detail"] == "offline"
    assert diagnostics_module._collect_update_status(settings)["detail"] == "disabled"
    configured = replace(settings, update_channel_url="https://updates.invalid/channel")
    assert diagnostics_module._collect_update_status(configured)["detail"] == "verification_not_configured"
    assert diagnostics_module._collect_update_status(replace(configured, update_pubkeys=("key",)))["detail"] == "ready"

    hardening_store = SimpleNamespace(
        list_hardening_runs=lambda: [
            SimpleNamespace(
                status="completed",
                expected_check_count=1,
                result_count=1,
                results=(SimpleNamespace(check_id="db.integrity", status="passed"),),
            )
        ]
    )
    assert diagnostics_module._collect_hardening(hardening_store)["checks"] == [  # type: ignore[arg-type]
        {"id": "db.integrity", "status": "passed"}
    ]

    runs = [
        SimpleNamespace(metadata_json="not-json"),
        SimpleNamespace(metadata_json="[]"),
        SimpleNamespace(metadata_json='{"correlation_id":"device.example.invalid"}'),
        SimpleNamespace(metadata_json='{"correlation_id":"case-1"}'),
        SimpleNamespace(metadata_json='{"correlation_id":"case-1"}'),
    ]
    correlation_store = SimpleNamespace(list_execution_runs=lambda: runs)
    assert diagnostics_module._collect_correlation_ids(correlation_store) == ["case-1"]  # type: ignore[arg-type]


def test_correlation_is_copied_before_execution_worker_starts(settings: Settings) -> None:
    store = Store(settings.data_path)
    run_id = ExecutionRecorder(store).record_execution(
        run_kind="workflow",
        source_run_id=None,
        actor="operator",
        status="completed",
        trigger_source="test",
        correlation_id="case-worker-1",
    )
    assert run_id is not None
    assert json.loads(store.get_execution_run(run_id).metadata_json)["correlation_id"] == "case-worker-1"  # type: ignore[union-attr]

    ensure_test_client(store)
    store.ingest_tickets(
        [Ticket("T-CORR", "Client", "Printer issue", "Printer is offline", "normal", "open")],
        client_id="acme",
    )
    workflow = run_workflow_template(store, "ticket-triage", "T-CORR", correlation_id="case-workflow-1")
    execution = store.find_execution_run("workflow", workflow.id or 0)
    assert execution is not None
    assert json.loads(execution.metadata_json)["correlation_id"] == "case-workflow-1"

    action = SmartActionService(store, settings).invoke(
        "ticket-triage",
        {"ticket_id": "T-CORR"},
        "operator",
        client_id="acme",
        correlation_id="case-action-1",
    )
    action_execution = store.find_execution_run("smart_action", action.run_id or 0)
    assert action_execution is not None
    assert json.loads(action_execution.metadata_json)["correlation_id"] == "case-action-1"


def test_install_mode_build_commit_and_ip_edge_helpers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    original_exists = Path.exists
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert diagnostics_module._install_mode() == "desktop"
    monkeypatch.delattr(sys, "frozen")
    monkeypatch.setattr(Path, "exists", lambda self: False)
    assert diagnostics_module._install_mode() == "cli"
    monkeypatch.setattr(Path, "exists", lambda self: self == Path("/.dockerenv"))
    assert diagnostics_module._install_mode() == "docker"
    monkeypatch.setattr(Path, "exists", original_exists)

    source = tmp_path / "repo" / "src" / "wait_local_agent" / "diagnostics.py"
    source.parent.mkdir(parents=True)
    source.touch()
    git_dir = source.parents[2] / ".git"
    git_dir.mkdir()
    commit = "a" * 40
    (git_dir / "HEAD").write_text(commit, encoding="ascii")
    monkeypatch.setattr(diagnostics_module, "__file__", str(source))
    assert diagnostics_module._build_commit() == commit
    (git_dir / "HEAD").write_text("detached-invalid", encoding="ascii")
    assert diagnostics_module._build_commit() is None

    invalid_source = tmp_path / "invalid-repo" / "src" / "wait_local_agent" / "diagnostics.py"
    invalid_source.parent.mkdir(parents=True)
    invalid_source.touch()
    (invalid_source.parents[2] / ".git").write_text("invalid marker", encoding="utf-8")
    monkeypatch.setattr(diagnostics_module, "__file__", str(invalid_source))
    assert diagnostics_module._build_commit() is None

    no_repo_source = tmp_path / "plain" / "diagnostics.py"
    no_repo_source.parent.mkdir()
    no_repo_source.touch()
    monkeypatch.setattr(diagnostics_module, "__file__", str(no_repo_source))
    assert diagnostics_module._build_commit() is None

    invalid_v4 = diagnostics_module._IPV4_RE.search("999.999.999.999")
    invalid_v6 = diagnostics_module._IPV6_CANDIDATE_RE.search("abcd:xyz")
    no_colon = diagnostics_module._IPV6_CANDIDATE_RE.search("abcd")
    assert invalid_v4 is not None and diagnostics_module._scrub_ipv4(invalid_v4) == "999.999.999.999"
    assert invalid_v6 is None
    assert no_colon is not None and diagnostics_module._scrub_ipv6(no_colon) == "abcd"
    invalid_v6_match = re.match(r".+", "abcd:")
    assert invalid_v6_match is not None and diagnostics_module._scrub_ipv6(invalid_v6_match) == "abcd:"


def test_server_entry_configures_logging_and_validates_port(
    monkeypatch: pytest.MonkeyPatch, settings: Settings
) -> None:
    calls: dict[str, object] = {}
    monkeypatch.setenv("WAIT_HOST", "127.0.0.2")
    monkeypatch.setenv("WAIT_PORT", "9999")
    monkeypatch.setattr(server_entry, "load_settings", lambda: settings)
    monkeypatch.setattr(server_entry, "configure_structured_logging", lambda value: calls.setdefault("logged", value))
    monkeypatch.setattr(server_entry, "create_app", lambda value: calls.setdefault("app_settings", value) or object())
    monkeypatch.setattr(
        server_entry.uvicorn,
        "run",
        lambda application, *, host, port: calls.update(application=application, host=host, port=port),
    )
    server_entry.main()
    assert calls["logged"] is settings
    assert calls["app_settings"] is settings
    assert calls["host"] == "127.0.0.2"
    assert calls["port"] == 9999
    assert server_entry._port_from_env(None) == server_entry.DEFAULT_PORT
    assert server_entry._port_from_env("bad") == server_entry.DEFAULT_PORT
    assert server_entry._port_from_env("0") == server_entry.DEFAULT_PORT

    calls.clear()
    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "configure_structured_logging", lambda value: calls.setdefault("logged", value))
    monkeypatch.setattr(cli_module, "create_app", lambda value: calls.setdefault("app_settings", value) or object())
    monkeypatch.setattr(
        cli_module.uvicorn,
        "run",
        lambda application, *, host, port: calls.update(application=application, host=host, port=port),
    )
    cli_module.serve(host="127.0.0.3", port=9898)
    assert calls["logged"] is settings
    assert calls["app_settings"] is settings
    assert calls["host"] == "127.0.0.3"
    assert calls["port"] == 9898


def test_support_cli_commands(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    data_path = tmp_path / "state.db"
    output = tmp_path / "operator-selected" / "bundle.zip"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    runner = CliRunner()

    doctor = runner.invoke(cli_app, ["support", "doctor"])
    preview = runner.invoke(cli_app, ["support", "bundle", "--preview"])
    bundle = runner.invoke(cli_app, ["support", "bundle", "--output", str(output)])
    upload = runner.invoke(cli_app, ["support", "upload", "--consent"])

    assert doctor.exit_code == 0, doctor.output
    assert wait_local_agent.__version__ in doctor.output
    assert preview.exit_code == 0, preview.output
    assert "ticket bodies" in preview.output
    assert bundle.exit_code == 0, bundle.output
    assert zipfile.is_zipfile(output)
    assert upload.exit_code == 1
    assert "demo mode" in upload.output
    assert Store(data_path).list_audit_events()[-1].event_type == "support.upload_refused"
