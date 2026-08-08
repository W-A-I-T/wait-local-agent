from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

import wait_local_agent.cli as cli_module
from wait_local_agent.agents import AgentService
from wait_local_agent.autotask import AutotaskReadResponse
from wait_local_agent.cli import app
from wait_local_agent.collectors import (
    default_registry,
)
from wait_local_agent.config import load_settings
from wait_local_agent.confluence import ConfluencePage, ConfluenceReadResponse
from wait_local_agent.itglue import (
    ItGlueDocument,
    ItGlueFolder,
    ItGlueOrganization,
    ItGlueReadResponse,
)
from wait_local_agent.models import (
    ConnectorReadResult,
    ConnectWiseWriteResult,
    HaloClient,
    HaloReadResult,
    HaloTicket,
    HaloWriteResult,
    HuduArticle,
    HuduCompany,
    HuduFolder,
)
from wait_local_agent.reports.hardening_checks import HardeningRunRecord
from wait_local_agent.servicenow import ServiceNowReadResponse
from wait_local_agent.sharepoint import SharePointDocument, SharePointReadResponse
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroReadResponse


def test_doctor_command_reports_safe_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "provider=deterministic" in result.output
    assert "base_url=http://127.0.0.1:11434/v1" in result.output
    assert "timeout_seconds=20" in result.output
    assert "llm_inference_enabled=False" in result.output
    assert "write_actions_enabled=False" in result.output


def test_technician_chat_command_invokes_existing_action(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    settings = load_settings()
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))

    result = CliRunner().invoke(app, ["technician-chat", "triage TCK-1001"])

    assert result.exit_code == 0
    assert '"action_id": "ticket-triage"' in result.output
    assert '"status": "success"' in result.output


def test_technician_chat_command_persists_bounded_session(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))

    created = CliRunner().invoke(
        app,
        [
            "technician-chat",
            "help",
            "--new-session",
            "--client-id",
            "acme",
        ],
    )
    assert created.exit_code == 0
    session_id = created.output.split("session_id=", 1)[1].splitlines()[0]

    continued = CliRunner().invoke(
        app,
        [
            "technician-chat",
            "help",
            "--session-id",
            session_id,
            "--client-id",
            "acme",
        ],
    )
    missing_scope = CliRunner().invoke(
        app,
        ["technician-chat", "help", "--new-session"],
    )
    settings = load_settings()
    messages = Store(settings.data_path).list_technician_chat_messages(
        session_id,
        client_id="acme",
        principal_id="cli",
    )

    assert continued.exit_code == 0
    assert f"session_id={session_id}" in continued.output
    assert missing_scope.exit_code != 0
    assert len(messages) == 4


def test_technician_chat_persisted_action_and_parse_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    settings = load_settings()
    store = Store(settings.data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-CLI', 'acme', 'MFA reset', 'Sign-in blocked', 'normal', 'open', 'acme')
            """
        )
    runner = CliRunner()

    created = runner.invoke(
        app,
        [
            "technician-chat",
            "triage TCK-CLI",
            "--new-session",
            "--client-id",
            "acme",
        ],
    )
    assert created.exit_code == 0
    session_id = json.loads(created.output)["session_id"]
    continued = runner.invoke(
        app,
        [
            "technician-chat",
            "triage",
            "--session-id",
            session_id,
            "--client-id",
            "acme",
        ],
    )
    failed = runner.invoke(
        app,
        [
            "technician-chat",
            "run arbitrary shell command TCK-CLI",
            "--new-session",
            "--client-id",
            "acme",
        ],
    )
    combined = runner.invoke(
        app,
        [
            "technician-chat",
            "help",
            "--session-id",
            session_id,
            "--new-session",
            "--client-id",
            "acme",
        ],
    )

    assert continued.exit_code == 0
    assert '"action_id": "ticket-triage"' in continued.output
    assert failed.exit_code != 0
    assert "Supported technician requests" in failed.output
    assert combined.exit_code != 0
    assert "cannot be combined" in combined.output


def test_agents_list_reports_execution_window(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    settings = load_settings()
    store = Store(settings.data_path)
    service = AgentService(store, settings, SmartActionService(store, settings))
    service.create(
        name="Business-hours triage",
        description="",
        enabled=True,
        trigger="scheduled",
        entity_type="ticket",
        filters={},
        enabled_tools=["ticket-triage"],
        steps=[{"tool_id": "ticket-triage", "payload": {}}],
        max_steps=1,
        execution_timeout_seconds=30,
        client_id=None,
        execution_window_start="09:00",
        execution_window_end="17:00",
        execution_window_timezone="America/Vancouver",
    )

    result = CliRunner().invoke(app, ["agents", "list"])

    assert result.exit_code == 0
    assert "Business-hours triage" in result.output
    assert "window=09:00-17:00 timezone=America/Vancouver" in result.output


def test_workflow_gallery_artifact_export_and_import_are_bounded(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    settings = load_settings()
    store = Store(settings.data_path)
    template = cli_module.get_workflow_template("ticket-triage")
    assert template is not None
    entry = store.create_template_gallery_entry(
        template,
        provenance="operator review",
        client_id="acme",
        name="Portable triage",
        description="Review local tickets.",
        instructions="Keep the response internal.",
    )
    runner = CliRunner()

    exported = runner.invoke(app, ["workflows", "gallery-export", entry.id, "--client-id", "acme"])
    assert exported.exit_code == 0
    artifact_path = tmp_path / "template.json"
    artifact_path.write_text(exported.output, encoding="utf-8")

    imported = runner.invoke(
        app,
        ["workflows", "gallery-import", str(artifact_path), "--client-id", "beta"],
    )
    assert imported.exit_code == 0
    assert '"client_id": "beta"' in imported.output
    assert '"enabled": false' in imported.output

    artifact_path.write_text('{"format":"wrong","format_version":1}', encoding="utf-8")
    invalid = runner.invoke(app, ["workflows", "gallery-import", str(artifact_path)])
    assert invalid.exit_code != 0

    missing_export = runner.invoke(app, ["workflows", "gallery-export", "missing"])
    missing_file = runner.invoke(app, ["workflows", "gallery-import", str(tmp_path / "missing.json")])
    artifact_path.write_text(
        json.dumps({"format": "wait-local-agent.workflow-template", "format_version": 1}),
        encoding="utf-8",
    )
    missing_fields = runner.invoke(app, ["workflows", "gallery-import", str(artifact_path)])
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * 1_000_001)
    oversized_result = runner.invoke(app, ["workflows", "gallery-import", str(oversized)])
    assert missing_export.exit_code != 0
    assert missing_file.exit_code != 0
    assert missing_fields.exit_code != 0
    assert oversized_result.exit_code != 0


def test_m365_group_command_is_available_and_safe_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["connectors", "m365-groups"])

    assert result.exit_code == 0
    assert '"status": "blocked"' in result.output
    assert "WAIT_ALLOW_HTTP_PROBING=true" in result.output


def test_m365_license_command_is_available_and_safe_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["connectors", "m365-licenses"])

    assert result.exit_code == 0
    assert '"status": "blocked"' in result.output
    assert "WAIT_ALLOW_HTTP_PROBING=true" in result.output


def test_m365_user_license_detail_command_is_available_and_safe_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "m365-user-license-details", "user@example.test"],
    )

    assert result.exit_code == 0
    assert '"status": "blocked"' in result.output
    assert "WAIT_ALLOW_HTTP_PROBING=true" in result.output


def test_m365_mail_folder_command_is_available_and_safe_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "m365-mail-folders", "--identity", "user@example.test"],
    )

    assert result.exit_code == 0
    assert '"status": "blocked"' in result.output
    assert "WAIT_ALLOW_HTTP_PROBING=true" in result.output


def test_m365_mail_message_command_is_available_and_safe_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "m365-mail-messages", "user@example.test", "inbox"],
    )

    assert result.exit_code == 0
    assert '"status": "blocked"' in result.output
    assert "WAIT_ALLOW_HTTP_PROBING=true" in result.output


def test_m365_managed_device_command_is_available_and_safe_by_default(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["connectors", "m365-managed-devices"])

    assert result.exit_code == 0
    assert '"status": "blocked"' in result.output
    assert "WAIT_ALLOW_HTTP_PROBING=true" in result.output


def test_m365_user_draft_command_persists_only_vault_reference(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-user",
            "adele.vance@example.test",
            "Adele Vance",
            "adele.vance",
            "WAIT_M365_TEMP_ADELE",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.users.create" in result.output
    assert shown.exit_code == 0
    assert "WAIT_M365_TEMP_ADELE" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_user_disable_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-user-disable",
            "adele.vance@example.test",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.users.disable" in result.output
    assert shown.exit_code == 0
    assert "adele.vance@example.test" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_group_membership_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-group-membership",
            "group-1",
            "user-1",
            "--operation",
            "add",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.groups.members.add" in result.output
    assert shown.exit_code == 0
    assert "group-1" in shown.output
    assert "user-1" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_license_change_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()
    sku_id = "84a661c4-e949-4bd2-a560-ed7766fcaf2b"

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-license-change",
            "user-1",
            "--sku-id",
            sku_id,
            "--operation",
            "add",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.users.licenses.add" in result.output
    assert shown.exit_code == 0
    assert sku_id in shown.output
    assert "password" not in shown.output.lower()


def test_m365_session_revocation_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "draft-m365-session-revocation", "user-1"],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.users.sessions.revoke" in result.output
    assert shown.exit_code == 0
    assert "user-1" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_managed_device_retirement_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "draft-m365-managed-device-retirement", "device-1"],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.managed-devices.retire" in result.output
    assert shown.exit_code == 0
    assert "device-1" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_managed_device_sync_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "draft-m365-managed-device-sync", "device-1"],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.managed-devices.sync" in result.output
    assert shown.exit_code == 0
    assert "device-1" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_managed_device_reboot_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["connectors", "draft-m365-managed-device-reboot", "device-1"],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.managed-devices.reboot" in result.output
    assert shown.exit_code == 0
    assert "device-1" in shown.output
    assert "password" not in shown.output.lower()


def test_m365_managed_device_remote_lock_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    result = CliRunner().invoke(
        app,
        ["connectors", "draft-m365-managed-device-remote-lock", "device-1"],
    )

    assert result.exit_code == 0
    assert "action_type=m365.managed-devices.remote-lock" in result.output
    assert "status=pending" in result.output


def test_m365_mailbox_settings_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-mailbox-settings",
            "user-1",
            "--setting",
            "locale=en-US",
            "--setting",
            "time_zone=UTC",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.users.mailbox-settings.update" in result.output
    assert shown.exit_code == 0
    assert "en-US" in shown.output


def test_m365_mail_message_move_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-mail-message-move",
            "user-1",
            "inbox",
            "message-1",
            "archive",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.mail-messages.move" in result.output
    assert shown.exit_code == 0
    assert "message-1" in shown.output


def test_m365_mail_message_read_state_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-mail-message-read-state",
            "user-1",
            "inbox",
            "message-1",
            "--unread",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.mail-messages.read-state" in result.output
    assert shown.exit_code == 0
    assert "message-1" in shown.output
    assert '"is_read": false' in shown.output


def test_m365_mail_message_delete_draft_command_is_available(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "connectors",
            "draft-m365-mail-message-delete",
            "user-1",
            "inbox",
            "message-1",
        ],
    )
    shown = runner.invoke(app, ["approvals", "show", "1"])

    assert result.exit_code == 0
    assert "action_type=m365.mail-messages.delete" in result.output
    assert shown.exit_code == 0
    assert "message-1" in shown.output


def test_collectors_list_shows_exactly_fourteen_modules(
    monkeypatch, tmp_path, isolated_default_registry
) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["collectors", "list"])

    module_lines = [line for line in result.output.splitlines() if line.strip()]
    registered_ids = [module.manifest.id for module in default_registry.list()]
    assert result.exit_code == 0
    assert len(module_lines) == len(registered_ids) == 14
    assert [line.split()[0] for line in module_lines] == registered_ids


def test_doctor_requires_all_halopsa_credentials(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_HALOPSA_BASE_URL", "https://halo.example.test")
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_ID", "client-id")
    monkeypatch.delenv("WAIT_HALOPSA_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("WAIT_HALOPSA_TENANT", raising=False)
    runner = CliRunner()

    partial = runner.invoke(app, ["doctor"])
    monkeypatch.setenv("WAIT_HALOPSA_CLIENT_SECRET", "secret")
    monkeypatch.setenv("WAIT_HALOPSA_TENANT", "tenant")
    complete = runner.invoke(app, ["doctor"])

    assert partial.exit_code == 0
    assert "halopsa_configured=False" in partial.output
    assert complete.exit_code == 0
    assert "halopsa_configured=True" in complete.output


def test_ingest_and_summarize_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    ingest = runner.invoke(app, ["ingest", "examples/sample_tickets"])
    summary = runner.invoke(app, ["tickets", "summarize", "TCK-1001"])

    assert ingest.exit_code == 0
    assert "ingested=2" in ingest.output
    assert summary.exit_code == 0
    assert "classification=identity-access" in summary.output


def test_audit_list_command(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    runner.invoke(app, ["ingest", "examples/sample_tickets"])
    result = runner.invoke(app, ["audit", "list"])

    assert result.exit_code == 0
    assert "ticket.ingested" in result.output


def test_knowledge_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOWED_DOC_ROOT", "examples/sample_docs")
    runner = CliRunner()

    ingest = runner.invoke(app, ["knowledge", "ingest", "examples/sample_docs"])
    listing = runner.invoke(app, ["knowledge", "list"])
    search = runner.invoke(app, ["knowledge", "search", "mailbox permissions"])
    search_with_backend = runner.invoke(
        app,
        ["knowledge", "search", "mailbox permissions", "--backend", "sqlite"],
    )

    assert ingest.exit_code == 0
    assert "documents=3" in ingest.output
    assert listing.exit_code == 0
    assert "Shared Mailbox Runbook" in listing.output
    assert search.exit_code == 0
    assert "Shared Mailbox Runbook" in search.output
    assert search_with_backend.exit_code == 0
    assert "Shared Mailbox Runbook" in search_with_backend.output


def test_knowledge_search_without_results_exits_cleanly(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["knowledge", "search", "nothing"])

    assert result.exit_code == 0
    assert result.output == ""


def test_connector_workflow_approval_event_and_backup_commands(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    backup_path = tmp_path / "backup.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    runner = CliRunner()

    runner.invoke(app, ["ingest", "examples/sample_tickets"])
    connectors = runner.invoke(app, ["connectors", "list"])
    secrets = runner.invoke(app, ["connectors", "secrets"])
    templates = runner.invoke(app, ["workflows", "templates"])
    gallery_add = runner.invoke(
        app,
        [
            "workflows",
            "gallery-add",
            "ticket-triage",
            "cli review",
            "--display-name",
            "CLI triage",
            "--instructions",
            "Use local policy",
        ],
    )
    gallery_id = gallery_add.output.split("id=", 1)[1].split()[0] if gallery_add.exit_code == 0 else ""
    gallery_update = runner.invoke(
        app,
        ["workflows", "gallery-update", gallery_id, "--display-name", "CLI triage updated"],
    )
    gallery = runner.invoke(app, ["workflows", "gallery"])
    gallery_revisions = runner.invoke(app, ["workflows", "gallery-revisions", gallery_id])
    gallery_diff = runner.invoke(app, ["workflows", "gallery-diff", gallery_id, "1", "2"])
    missing_gallery_diff = runner.invoke(
        app, ["workflows", "gallery-diff", "missing-gallery", "1", "2"]
    )
    missing_gallery_diff_revision = runner.invoke(
        app, ["workflows", "gallery-diff", gallery_id, "1", "999"]
    )
    gallery_disable = runner.invoke(app, ["workflows", "gallery-disable", gallery_id])
    gallery_enable = runner.invoke(app, ["workflows", "gallery-enable", gallery_id])
    gallery_restore = runner.invoke(app, ["workflows", "gallery-restore", gallery_id, "1"])
    missing_gallery_update = runner.invoke(
        app, ["workflows", "gallery-update", "missing-gallery", "--display-name", "Missing"]
    )
    missing_gallery_revisions = runner.invoke(
        app, ["workflows", "gallery-revisions", "missing-gallery"]
    )
    missing_gallery_restore = runner.invoke(
        app, ["workflows", "gallery-restore", gallery_id, "999"]
    )
    run = runner.invoke(app, ["workflows", "run", "assign-technician", "TCK-1001"])
    completed = runner.invoke(app, ["workflows", "run", "ticket-triage", "TCK-1001"])
    quality = runner.invoke(app, ["workflows", "run", "ticket-quality-review", "TCK-1001"])
    gallery_run = runner.invoke(app, ["workflows", "gallery-run", gallery_id, "TCK-1001"])
    stored_runs = Store(data_path).list_workflow_runs()
    run_comparison = runner.invoke(
        app,
        ["workflows", "compare-runs", str(stored_runs[-1].id), str(stored_runs[0].id)],
    )
    missing_run_comparison = runner.invoke(app, ["workflows", "compare-runs", "99999", "100000"])
    draft = runner.invoke(
        app,
        [
            "connectors",
            "draft-halopsa",
            "TCK-1001",
            "add_note",
            "--field",
            "note=Draft ready",
        ],
    )
    approvals = runner.invoke(app, ["approvals", "list"])
    events = runner.invoke(app, ["events", "list"])
    backup = runner.invoke(app, ["backup", "create", str(backup_path)])
    restore = runner.invoke(app, ["backup", "restore", str(backup_path)])

    assert connectors.exit_code == 0
    assert "halopsa not_configured" in connectors.output
    assert secrets.exit_code == 0
    assert "WAIT_HALOPSA_BASE_URL configured=False" in secrets.output
    assert templates.exit_code == 0
    assert "assign-technician" in templates.output
    assert gallery_add.exit_code == 0
    assert gallery_update.exit_code == 0
    assert gallery.exit_code == 0 and "CLI triage updated" in gallery.output
    assert gallery_revisions.exit_code == 0 and "version=2" in gallery_revisions.output
    assert gallery_diff.exit_code == 0 and '"field": "name"' in gallery_diff.output
    assert missing_gallery_diff.exit_code != 0
    assert missing_gallery_diff_revision.exit_code != 0
    assert cli_module._safe_revision_definition("not-json") == {}  # noqa: SLF001
    assert cli_module._safe_revision_definition("[]") == {}  # noqa: SLF001
    assert gallery_disable.exit_code == 0 and "enabled=False" in gallery_disable.output
    assert gallery_enable.exit_code == 0 and "enabled=True" in gallery_enable.output
    assert gallery_restore.exit_code == 0 and "version=5" in gallery_restore.output
    assert missing_gallery_update.exit_code != 0
    assert missing_gallery_revisions.exit_code != 0
    assert missing_gallery_restore.exit_code != 0
    assert run.exit_code == 0
    assert "status=pending_approval" in run.output
    assert completed.exit_code == 0
    assert "status=completed" in completed.output
    assert quality.exit_code == 0
    assert "status=completed" in quality.output
    assert gallery_run.exit_code == 0
    assert "template_version=5" in gallery_run.output
    assert run_comparison.exit_code == 0
    assert '"from_run"' in run_comparison.output
    assert missing_run_comparison.exit_code != 0
    assert draft.exit_code == 0
    assert "approval_request_id=" in draft.output
    assert approvals.exit_code == 0
    assert "pending" in approvals.output
    assert events.exit_code == 0
    assert "workflow.execution" in events.output
    assert "workflow.completed" in events.output
    assert backup.exit_code == 0
    assert backup_path.exists()
    assert restore.exit_code == 0


def test_hardening_and_restore_commands_report_success(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    backup_path = tmp_path / "backup.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    runner = CliRunner()

    backup = runner.invoke(app, ["backup", "create", str(backup_path)])
    hardening = runner.invoke(app, ["hardening", "run"])
    listed_hardening = runner.invoke(app, ["hardening", "list"])
    exercise = runner.invoke(app, ["backup", "restore-exercise", str(backup_path)])

    assert backup.exit_code == 0
    assert hardening.exit_code == 0
    assert '"run"' in hardening.output
    assert listed_hardening.exit_code == 0
    assert "count=1" in listed_hardening.output
    assert exercise.exit_code == 0
    assert '"exercise"' in exercise.output


def test_hardening_and_restore_cli_error_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    monkeypatch.setattr(
        cli_module,
        "run_hardening_checks",
        lambda *args, **kwargs: HardeningRunRecord(None, "completed", "start", "", 0, 0),
    )
    hardening = runner.invoke(app, ["hardening", "run"])
    assert hardening.exit_code != 0
    assert "hardening run was not persisted" in hardening.output

    monkeypatch.setattr(
        cli_module,
        "run_restore_exercise",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cannot start")),
    )
    exercise = runner.invoke(app, ["backup", "restore-exercise", "missing.db"])
    assert exercise.exit_code != 0
    assert "restore exercise could not be started" in exercise.output


def test_secret_and_update_cli_error_paths(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_VAULT_PATH", str(tmp_path / "vault"))
    runner = CliRunner()

    invalid_set = runner.invoke(app, ["secrets", "set", "", "value"])
    invalid_get = runner.invoke(app, ["secrets", "get", ""])
    monkeypatch.setattr(
        cli_module,
        "check_for_updates",
        lambda _settings: (_ for _ in ()).throw(RuntimeError("network failed")),
    )
    update = runner.invoke(app, ["update", "check"])

    assert invalid_set.exit_code != 0
    assert "secret key must not be empty" in invalid_set.output
    assert invalid_get.exit_code != 0
    assert "secret key must not be empty" in invalid_get.output
    assert update.exit_code == 1
    assert "status=error detail=internal_error message=network failed" in update.output


def test_halopsa_cli_read_commands_block_without_http_flag(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "false")
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "halopsa-health"])
    tickets = runner.invoke(app, ["connectors", "halopsa-tickets"])

    assert health.exit_code == 0
    assert "blocked count=0" in health.output
    assert tickets.exit_code == 0
    assert "blocked count=0" in tickets.output


def test_halopsa_cli_read_commands_print_mocked_results(monkeypatch, tmp_path) -> None:
    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return HaloReadResult("ready", "ok", 0)

        def write_health(self):
            return HaloReadResult("ready", "write ok", 0)

        def list_tickets(self, page: int = 1, page_size: int = 50):
            assert page == 2
            assert page_size == 5
            return _read_response(
                [HaloTicket("TCK-1", "Printer", "Open", "High", "C-1", "Contoso")]
            )

        def get_ticket(self, ticket_id: str):
            return _read_response([HaloTicket(ticket_id, "One", "Open", "Low", "C-1", "Contoso")])

        def list_ticket_notes(self, ticket_id: str):
            return _read_response([])

        def list_clients(self, page: int = 1, page_size: int = 50):
            return _read_response([HaloClient("C-1", "Contoso", "Active")])

        def list_client_assets(self, client_id: str):
            return _read_response([])

        def list_categories(self):
            return _read_response([])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "HaloPSAClient", FakeHaloClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "halopsa-health"])
    tickets = runner.invoke(
        app,
        ["connectors", "halopsa-tickets", "--page", "2", "--page-size", "5"],
    )
    ticket = runner.invoke(app, ["connectors", "halopsa-ticket", "TCK-1"])
    notes = runner.invoke(app, ["connectors", "halopsa-notes", "TCK-1"])
    clients = runner.invoke(app, ["connectors", "halopsa-clients"])
    assets = runner.invoke(app, ["connectors", "halopsa-assets", "C-1"])
    categories = runner.invoke(app, ["connectors", "halopsa-categories"])
    write_health = runner.invoke(app, ["connectors", "halopsa-write-health"])

    assert health.exit_code == 0
    assert "ready count=0 ok" in health.output
    assert tickets.exit_code == 0
    assert "TCK-1" in tickets.output
    assert ticket.exit_code == 0
    assert "One" in ticket.output
    assert notes.exit_code == 0
    assert clients.exit_code == 0
    assert "Contoso" in clients.output
    assert assets.exit_code == 0
    assert categories.exit_code == 0
    assert write_health.exit_code == 0
    assert "write ok" in write_health.output


def test_hudu_cli_commands_print_mocked_results(monkeypatch, tmp_path) -> None:
    class FakeHuduClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return HaloReadResult("ready", "ok", 0)

        def list_companies(self, page: int = 1, page_size: int | None = None):
            return _hudu_response([HuduCompany("C-1", "Contoso", False)])

        def list_articles(
            self,
            company_id: str | None = None,
            page: int = 1,
            page_size: int | None = None,
        ):
            return _hudu_response([
                HuduArticle("A-1", "Runbook", "C-1", "F-1", "", "", "token=secret"),
            ])

        def get_article(self, article_id: str):
            return _hudu_response([
                HuduArticle(article_id, "Runbook", "C-1", "F-1", "", "", "token=secret"),
            ])

        def list_folders(
            self,
            company_id: str | None = None,
            page: int = 1,
            page_size: int | None = None,
        ):
            return _hudu_response([HuduFolder("F-1", "Ops", "C-1", "")])

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "HuduClient", FakeHuduClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "hudu-health"])
    companies = runner.invoke(app, ["connectors", "hudu-companies"])
    articles = runner.invoke(app, ["connectors", "hudu-articles"])
    article = runner.invoke(app, ["connectors", "hudu-article", "A-1"])
    folders = runner.invoke(app, ["connectors", "hudu-folders"])

    assert health.exit_code == 0
    assert "ready count=0 ok" in health.output
    assert companies.exit_code == 0
    assert "Contoso" in companies.output
    assert articles.exit_code == 0
    assert "Runbook" in articles.output
    assert "token=[redacted]" in articles.output
    assert article.exit_code == 0
    assert "A-1" in article.output
    assert folders.exit_code == 0
    assert "Ops" in folders.output


def test_syncro_cli_commands_print_mocked_results(monkeypatch, tmp_path) -> None:
    class FakeSyncroClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ok", 0)

        def list_tickets(self, **kwargs):
            return SyncroReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "42", "subject": "Printer offline"}],
            )

        def get_ticket(self, ticket_id):
            return SyncroReadResponse(
                ConnectorReadResult("ready", "ok", 1), [{"id": ticket_id}]
            )

        def list_customers(self, **kwargs):
            return SyncroReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1), [{"id": "7", "name": "Contoso"}]
            )

        def get_customer(self, customer_id):
            return SyncroReadResponse(
                ConnectorReadResult("ready", "ok", 1), [{"id": customer_id}]
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "SyncroClient", FakeSyncroClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "syncro-health"])
    tickets = runner.invoke(app, ["connectors", "syncro-tickets", "--query", "printer"])
    ticket = runner.invoke(app, ["connectors", "syncro-ticket", "42"])
    customers = runner.invoke(app, ["connectors", "syncro-customers"])
    customer = runner.invoke(app, ["connectors", "syncro-customer", "7"])

    assert health.exit_code == 0
    assert "ready count=0 ok" in health.output
    assert tickets.exit_code == 0 and "Printer offline" in tickets.output
    assert ticket.exit_code == 0 and "42" in ticket.output
    assert customers.exit_code == 0 and "Contoso" in customers.output
    assert customer.exit_code == 0 and "7" in customer.output


def test_servicenow_cli_commands_print_mocked_results(monkeypatch, tmp_path) -> None:
    class FakeServiceNowClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ok", 0)

        def list_incidents(self, **kwargs):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"sys_id": "abc123", "number": "INC001"}],
            )

        def get_incident(self, sys_id):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", "ok", 1), [{"sys_id": sys_id}]
            )

        def list_companies(self, **kwargs):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1), [{"sys_id": "co-1", "name": "Contoso"}]
            )

        def get_company(self, sys_id):
            return ServiceNowReadResponse(
                ConnectorReadResult("ready", "ok", 1), [{"sys_id": sys_id}]
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "ServiceNowClient", FakeServiceNowClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "servicenow-health"])
    incidents = runner.invoke(app, ["connectors", "servicenow-incidents", "--query", "active=true"])
    incident = runner.invoke(app, ["connectors", "servicenow-incident", "abc123"])
    companies = runner.invoke(app, ["connectors", "servicenow-companies"])
    company = runner.invoke(app, ["connectors", "servicenow-company", "co-1"])

    assert health.exit_code == 0
    assert "ready count=0 ok" in health.output
    assert incidents.exit_code == 0 and "INC001" in incidents.output
    assert incident.exit_code == 0 and "abc123" in incident.output
    assert companies.exit_code == 0 and "Contoso" in companies.output
    assert company.exit_code == 0 and "co-1" in company.output


def test_autotask_cli_commands_print_mocked_results(monkeypatch, tmp_path) -> None:
    class FakeAutotaskClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ok", 0)

        def list_tickets(self, **kwargs):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [{"id": "7", "ticket_number": "T-7"}],
            )

        def get_ticket(self, ticket_id):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", "ok", 1), [{"id": ticket_id}]
            )

        def list_companies(self, **kwargs):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1), [{"id": "3", "name": "Contoso"}]
            )

        def get_company(self, company_id):
            return AutotaskReadResponse(
                ConnectorReadResult("ready", "ok", 1), [{"id": company_id}]
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "AutotaskClient", FakeAutotaskClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "autotask-health"])
    tickets = runner.invoke(app, ["connectors", "autotask-tickets"])
    ticket = runner.invoke(app, ["connectors", "autotask-ticket", "7"])
    companies = runner.invoke(app, ["connectors", "autotask-companies"])
    company = runner.invoke(app, ["connectors", "autotask-company", "3"])

    assert health.exit_code == 0
    assert "ready count=0 ok" in health.output
    assert tickets.exit_code == 0 and "T-7" in tickets.output
    assert ticket.exit_code == 0 and "7" in ticket.output
    assert companies.exit_code == 0 and "Contoso" in companies.output
    assert company.exit_code == 0 and "3" in company.output


def test_itglue_cli_commands_print_mocked_results(monkeypatch, tmp_path) -> None:
    class FakeItGlueClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "ok", 0)

        def list_organizations(self, **kwargs):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ItGlueOrganization("1", "Contoso", "active")],
            )

        def list_documents(self, organization_id, **kwargs):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ItGlueDocument("9", "Runbook", organization_id, "7", "today", "", "token=secret")],
            )

        def get_document(self, document_id):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [ItGlueDocument(document_id, "Runbook", "1", "7", "today", "", "token=secret")],
            )

        def list_folders(self, organization_id, **kwargs):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ItGlueFolder("7", "Ops", organization_id, "0")],
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "ItGlueClient", FakeItGlueClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "itglue-health"])
    organizations = runner.invoke(app, ["connectors", "itglue-organizations"])
    documents = runner.invoke(app, ["connectors", "itglue-documents", "1"])
    document = runner.invoke(app, ["connectors", "itglue-document", "9"])
    folders = runner.invoke(app, ["connectors", "itglue-folders", "1"])

    assert health.exit_code == 0
    assert "ready count=0 ok" in health.output
    assert organizations.exit_code == 0 and "Contoso" in organizations.output
    assert documents.exit_code == 0 and "Runbook" in documents.output
    assert "token=[redacted]" in documents.output
    assert document.exit_code == 0 and "Runbook" in document.output
    assert folders.exit_code == 0 and "Ops" in folders.output


def test_confluence_cli_commands_redact_page_content(monkeypatch, tmp_path) -> None:
    class FakeConfluenceClient:
        def __init__(self, _settings) -> None:
            pass

        def list_pages(self, **kwargs):
            return ConfluenceReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ConfluencePage("9", "Runbook", "42", "current", "3", "today", "/page/9", "token=secret")],
            )

        def get_page(self, page_id):
            return ConfluenceReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [ConfluencePage(page_id, "Runbook", "42", "current", "3", "today", "/page/9", "token=secret")],
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "ConfluenceClient", FakeConfluenceClient)
    runner = CliRunner()

    pages = runner.invoke(app, ["connectors", "confluence-pages", "--space-id", "42"])
    page = runner.invoke(app, ["connectors", "confluence-page", "9"])

    assert pages.exit_code == 0
    assert "token=secret" not in pages.output
    assert "token=[redacted]" in pages.output
    assert page.exit_code == 0
    assert "token=[redacted]" in page.output


def test_sharepoint_cli_document_content_is_bounded_and_redacted(monkeypatch, tmp_path) -> None:
    class FakeSharePointClient:
        def __init__(self, _settings) -> None:
            pass

        def get_document(self, site_id, item_id):
            return SharePointReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [SharePointDocument(item_id, "Runbook.txt", site_id, "root", 10, "today", "/runbook", False, True)],
            )

        def get_document_content(self, site_id, item_id):
            return SharePointReadResponse(
                ConnectorReadResult("ready", "ok", 1),
                [SharePointDocument(
                    item_id, "Runbook.txt", site_id, "root", 10, "today", "/runbook", False, True,
                    "token=secret",
                )],
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "SharePointClient", FakeSharePointClient)
    result = CliRunner().invoke(app, ["connectors", "sharepoint-document-content", "site-1", "file-1"])

    assert result.exit_code == 0
    assert "token=secret" not in result.output
    assert "token=[redacted]" in result.output


def test_halopsa_cli_approval_auto_executes_and_manual_execute(monkeypatch, tmp_path) -> None:
    class FakeHaloClient:
        def __init__(self, _settings) -> None:
            pass

        def execute_write(self, request):
            return HaloWriteResult(
                "succeeded",
                "posted",
                request.action_type,
                request.ticket_id,
                endpoint="Actions",
                status_code=200,
                remote_id="A-1",
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "HaloPSAClient", FakeHaloClient)
    runner = CliRunner()

    draft = runner.invoke(
        app,
        [
            "connectors",
            "draft-halopsa",
            "HALO-42",
            "add_note",
            "--field",
            "note=Remote note",
        ],
    )
    request_id = draft.output.split("approval_request_id=")[1].split()[0]
    approved = runner.invoke(app, ["approvals", "update", request_id, "approved"])

    assert draft.exit_code == 0
    assert approved.exit_code == 0
    assert "execution_status=succeeded" in approved.output


def test_connectwise_cli_approval_auto_executes_and_reports_write_health(monkeypatch, tmp_path) -> None:
    class FakeConnectWiseClient:
        def __init__(self, _settings) -> None:
            pass

        def write_health(self):
            return ConnectorReadResult("ready", "ConnectWise writes ready", 0)

        def execute_write(self, request):
            return ConnectWiseWriteResult(
                "succeeded", "updated", request.action_type, request.ticket_id,
                endpoint="service/tickets/42", status_code=200, remote_id="42"
            )

    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_ALLOW_HTTP_PROBING", "true")
    monkeypatch.setenv("WAIT_ALLOW_WRITE_ACTIONS", "true")
    monkeypatch.setattr(cli_module, "ConnectWiseClient", FakeConnectWiseClient)
    runner = CliRunner()

    health = runner.invoke(app, ["connectors", "connectwise-write-health"])
    draft = runner.invoke(
        app,
        [
            "connectors",
            "draft-connectwise",
            "CW-42",
            "update_status",
            "--field",
            "status_id=7",
        ],
    )
    request_id = draft.output.split("approval_request_id=")[1].split()[0]
    edited = runner.invoke(app, ["approvals", "edit-field", request_id, "status_id=8"])
    approved = runner.invoke(app, ["approvals", "update", request_id, "approved"])
    manual_draft = runner.invoke(
        app,
        ["connectors", "draft-connectwise", "CW-43", "update_status", "--field", "status_id=9"],
    )
    manual_id = int(manual_draft.output.split("approval_request_id=")[1].split()[0])
    Store(tmp_path / "state.db").update_approval_request(manual_id, "approved")
    manual_execute = runner.invoke(app, ["connectors", "execute-connectwise", str(manual_id)])

    assert health.exit_code == 0
    assert "ready count=0 ConnectWise writes ready" in health.output
    assert draft.exit_code == 0
    assert edited.exit_code == 0
    assert approved.exit_code == 0
    assert "execution_status=succeeded" in approved.output
    assert manual_draft.exit_code == 0
    assert manual_execute.exit_code == 0
    assert "execution_status=succeeded" in manual_execute.output


def test_halopsa_cli_execute_reports_blocked_and_rejects_pending(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    store = Store(tmp_path / "state.db")
    approval = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {"connector": "halopsa", "ticket_id": "HALO-1", "action_type": "add_note", "fields": {}},
    )
    runner = CliRunner()

    pending = runner.invoke(app, ["connectors", "execute-halopsa", str(approval.id)])
    store.update_approval_request(approval.id or 0, "approved")
    blocked = runner.invoke(app, ["connectors", "execute-halopsa", str(approval.id)])

    assert pending.exit_code != 0
    assert "approved approval requests" in pending.output
    assert blocked.exit_code == 0
    assert "execution_status=blocked" in blocked.output


def test_approval_show_and_edit_field_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    store = Store(tmp_path / "state.db")
    approval = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "HALO-1",
        "action_type": "add_note",
            "fields": {"note": "Original", "api_key": "raw-secret"},
        },
    )
    runner = CliRunner()

    shown = runner.invoke(app, ["approvals", "show", str(approval.id)])
    edited = runner.invoke(app, ["approvals", "edit-field", str(approval.id), "note=Edited"])
    store.update_approval_request(approval.id or 0, "approved")
    rejected = runner.invoke(app, ["approvals", "edit-field", str(approval.id), "note=Late"])

    assert shown.exit_code == 0
    assert "Original" in shown.output
    assert "raw-secret" not in shown.output
    assert "[redacted]" in shown.output
    assert edited.exit_code == 0
    assert "payload_updated=True" in edited.output
    assert rejected.exit_code != 0
    assert "only be edited while pending" in rejected.output


def test_legacy_workflow_cli_approval_allows_terminal_state_update(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    store = Store(data_path)
    approval = store.create_approval_request("TCK-WORKFLOW", "workflow.assign", {})
    store.create_workflow_run(
        "documentation-assisted-response",
        "TCK-WORKFLOW",
        "pending_approval",
        "waiting",
        approval.id,
    )

    result = CliRunner().invoke(app, ["approvals", "update", str(approval.id), "approved"])

    assert result.exit_code == 0
    assert "approved" in result.output


def test_cli_error_edges_for_new_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    store = Store(tmp_path / "state.db")
    approval = store.create_approval_request(
        "HALO-1",
        "halopsa.add_note",
        {
            "connector": "halopsa",
            "ticket_id": "HALO-1",
            "action_type": "add_note",
            "fields": {"note": "Original"},
        },
    )
    runner = CliRunner()

    missing_show = runner.invoke(app, ["approvals", "show", "999"])
    bad_assignment = runner.invoke(app, ["approvals", "edit-field", str(approval.id), "bad"])
    bad_draft_field = runner.invoke(
        app,
        ["connectors", "draft-halopsa", "HALO-1", "add_note", "--field", "bad"],
    )
    bad_draft_action = runner.invoke(
        app,
        ["connectors", "draft-halopsa", "HALO-1", "bad_action"],
    )
    missing_execute = runner.invoke(app, ["connectors", "execute-halopsa", "999"])
    bad_connectwise_field = runner.invoke(
        app,
        ["connectors", "draft-connectwise", "CW-1", "update_status", "--field", "bad"],
    )
    bad_connectwise_action = runner.invoke(
        app,
        ["connectors", "draft-connectwise", "CW-1", "bad_action", "--field", "status_id=1"],
    )
    missing_connectwise_execute = runner.invoke(
        app, ["connectors", "execute-connectwise", "999"]
    )
    pending_connectwise_execute = runner.invoke(
        app, ["connectors", "execute-connectwise", str(approval.id)]
    )

    assert missing_show.exit_code != 0
    assert "approval request not found" in missing_show.output
    assert bad_assignment.exit_code != 0
    assert "key=value" in bad_assignment.output
    assert bad_draft_field.exit_code != 0
    assert "key=value" in bad_draft_field.output
    assert bad_draft_action.exit_code != 0
    assert "unsupported HaloPSA" in bad_draft_action.output
    assert missing_execute.exit_code != 0
    assert "approval request not found" in missing_execute.output
    assert bad_connectwise_field.exit_code != 0
    assert "key=value" in bad_connectwise_field.output
    assert bad_connectwise_action.exit_code != 0
    assert "unsupported ConnectWise" in bad_connectwise_action.output
    assert missing_connectwise_execute.exit_code != 0
    assert "approval request not found" in missing_connectwise_execute.output
    assert pending_connectwise_execute.exit_code != 0
    assert "not a ConnectWise" in pending_connectwise_execute.output


def test_smart_action_cli_requires_rbac_for_invoke_and_approval(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    monkeypatch.setenv("WAIT_DEMO_MODE", "false")
    monkeypatch.setenv("WAIT_TECH_TOKEN", "tech-token")
    store = Store(data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            """
            insert into tickets (id, client, subject, body, priority, status, client_id)
            values ('TCK-CLI', 'Acme', 'MFA reset', 'Sign-in blocked', 'High', 'Open', 'acme')
            """
        )
    runner = CliRunner()

    denied_invoke = runner.invoke(
        app,
        ["smart-actions", "invoke", "ticket-triage", "--payload", '{"ticket_id":"TCK-CLI"}'],
    )
    pending = SmartActionService(store, load_settings()).invoke(
        "dispatch-suggestion", {"ticket_id": "TCK-CLI", "technicians": []}, "requester"
    )
    denied_approval = runner.invoke(app, ["approvals", "update", str(pending.approval_id), "approved"])
    approved = runner.invoke(
        app,
        [
            "approvals",
            "update",
            str(pending.approval_id),
            "approved",
            "--token",
            "tech-token",
        ],
    )

    assert denied_invoke.exit_code != 0
    assert denied_approval.exit_code != 0
    assert approved.exit_code == 0
    assert store.get_smart_action_run(pending.run_id or 0).status == "success"  # type: ignore[union-attr]


def test_smart_action_cli_commands_success_and_errors(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    store = Store(data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status) values (?, ?, ?, ?, ?, ?)",
            ("TCK-CMD", "Acme", "MFA reset", "Sign-in blocked", "High", "Open"),
        )
    runner = CliRunner()

    listed = runner.invoke(app, ["smart-actions", "list"])
    described = runner.invoke(app, ["smart-actions", "describe", "ticket-triage"])
    invoked = runner.invoke(
        app,
        ["smart-actions", "invoke", "ticket-triage", "--payload", '{"ticket_id":"TCK-CMD"}'],
    )
    script = runner.invoke(
        app,
        [
            "technician-chat",
            "run approved script script-1 on device device-1",
            "--client-id",
            "acme",
        ],
    )
    collector_preview = runner.invoke(
        app,
        ["smart-actions", "invoke", "collector-preview", "--payload", '{"module_id":"host-runtime"}'],
    )
    runs = runner.invoke(app, ["smart-actions", "runs"])
    missing = runner.invoke(app, ["smart-actions", "describe", "missing"])
    bad_payload = runner.invoke(app, ["smart-actions", "invoke", "ticket-triage", "--payload", "not-json"])

    assert listed.exit_code == 0 and "ticket-triage" in listed.output
    assert "syncro-ticket-lookup" in listed.output
    assert "servicenow-incident-lookup" in listed.output
    assert "autotask-ticket-lookup" in listed.output
    assert "itglue-documentation-search" in listed.output
    assert "confluence-documentation-search" in listed.output
    assert "sharepoint-documentation-search" in listed.output
    assert "m365-live-context" in listed.output
    assert described.exit_code == 0 and '"action_id": "ticket-triage"' in described.output
    assert invoked.exit_code == 0 and json.loads(invoked.output)["status"] == "success"
    assert script.exit_code == 0 and json.loads(script.output)["action_id"] == "rmm-script-execute"
    assert collector_preview.exit_code == 0 and json.loads(collector_preview.output)["status"] == "success"
    assert runs.exit_code == 0 and "ticket-triage success" in runs.output
    assert missing.exit_code != 0 and "smart action not found" in missing.output
    assert bad_payload.exit_code != 0 and "payload must be a JSON object" in bad_payload.output


def test_smart_action_cli_tenant_scope_and_approval_view_guards(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    monkeypatch.setenv("WAIT_DEMO_MODE", "false")
    monkeypatch.setenv("WAIT_TECH_TOKEN", "tech-token")
    monkeypatch.setenv("WAIT_CLIENT_ID", "acme")
    store = Store(data_path)
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status, client_id) values (?, ?, ?, ?, ?, ?, ?)",
            ("TCK-ACME", "Acme", "MFA reset", "Sign-in blocked", "High", "Open", "acme"),
        )
        connection.execute(
            "insert into tickets (id, client, subject, body, priority, status, client_id) values (?, ?, ?, ?, ?, ?, ?)",
            ("TCK-BETA", "Beta", "MFA reset", "Sign-in blocked", "High", "Open", "beta"),
        )
    runner = CliRunner()
    ok = runner.invoke(
        app,
        ["smart-actions", "invoke", "ticket-triage", "--token", "tech-token", "--payload", '{"ticket_id":"TCK-ACME"}'],
    )
    forbidden_data = runner.invoke(
        app,
        ["smart-actions", "invoke", "ticket-triage", "--token", "tech-token", "--payload", '{"ticket_id":"TCK-BETA"}'],
    )
    no_token = runner.invoke(app, ["smart-actions", "invoke", "ticket-triage", "--payload", '{"ticket_id":"TCK-ACME"}'])

    assert ok.exit_code == 0 and json.loads(ok.output)["status"] == "success"
    assert forbidden_data.exit_code == 0 and json.loads(forbidden_data.output)["status"] == "failed"
    assert no_token.exit_code != 0 and "missing bearer token" in no_token.output

    approval = store.create_approval_request("TCK-1", "ticket.assign", {"secret": "password=raw"})
    with store._connect() as connection:  # noqa: SLF001
        connection.execute(
            "update approval_requests set payload_json = ?, execution_result_json = ? where id = ?",
            ("not-json", "not-json", approval.id),
        )
    view = cli_module._approval_cli_view(store.get_approval_request(approval.id or 0))  # noqa: SLF001
    assert view["payload"] == {} and view["output"] == {}


def _read_response(items):
    return cli_module.HaloReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def test_executions_cli_lists_and_shows_runs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    store = Store(tmp_path / "state.db")
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    from wait_local_agent.workflows import run_workflow_template

    run_workflow_template(store, "ticket-triage", "TCK-1001", actor="cli", trigger_source="cli")
    runner = CliRunner()

    listed = runner.invoke(app, ["executions", "list"])
    by_kind = runner.invoke(app, ["executions", "list", "--kind", "smart_action"])
    shown = runner.invoke(app, ["executions", "show", "1"])
    missing = runner.invoke(app, ["executions", "show", "999"])

    assert listed.exit_code == 0
    assert "workflow completed actor=cli" in listed.output
    assert by_kind.exit_code == 0
    assert "workflow" not in by_kind.output
    assert shown.exit_code == 0
    payload = json.loads(shown.output)
    assert payload["run_kind"] == "workflow"
    assert [step["ordinal"] for step in payload["steps"]] == [0]
    assert payload["steps"][0]["input"]["ticket_id"] == "TCK-1001"
    assert "storage_path" not in json.dumps(payload["artifacts"])
    assert missing.exit_code != 0


def test_analytics_cli_summary_mirrors_api(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    settings = load_settings()
    store = Store(settings.data_path)
    store.ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    service = SmartActionService(store, settings)
    service.invoke("ticket-triage", {"ticket_id": "TCK-1001"}, "tech")
    service.invoke("ticket-triage", {"ticket_id": "NOPE"}, "tech")
    runner = CliRunner()

    result = runner.invoke(app, ["analytics", "summary"])

    assert result.exit_code == 0
    summary = json.loads(result.output)
    assert summary["success_rate"] == {"total": 2, "succeeded": 1, "rate": 0.5}
    assert summary["failures_by_status"] == [{"status": "failed", "count": 1}]
    assert summary["estimated_minutes_saved"]["estimate"] is True
    assert summary["estimated_minutes_saved"]["minutes"] == 4


def test_executions_cli_requires_tenant_for_non_admin(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setenv("WAIT_DEMO_MODE", "false")
    monkeypatch.setenv("WAIT_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("WAIT_TECH_TOKEN", "tech-token")
    store = Store(tmp_path / "state.db")
    store.create_execution_run(
        "workflow", 1, "a", "completed", "2026-08-01T09:00:00+00:00",
        "2026-08-01T09:01:00+00:00", "test", client_id="acme",
    )
    runner = CliRunner()

    no_tenant = runner.invoke(app, ["executions", "list", "--token", "tech-token"])
    admin = runner.invoke(app, ["executions", "list", "--token", "admin-token"])

    assert no_tenant.exit_code != 0
    assert "no tenant" in no_tenant.output
    assert admin.exit_code == 0
    assert "workflow" in admin.output


def _hudu_response(items):
    return cli_module.HuduReadResponse(HaloReadResult("ready", "ok", len(items)), items)
