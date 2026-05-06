from __future__ import annotations

from typer.testing import CliRunner

from wait_local_agent.cli import app


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

    assert ingest.exit_code == 0
    assert "documents=3" in ingest.output
    assert listing.exit_code == 0
    assert "Shared Mailbox Runbook" in listing.output
    assert search.exit_code == 0
    assert "Shared Mailbox Runbook" in search.output


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
    run = runner.invoke(app, ["workflows", "run", "assign-technician", "TCK-1001"])
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
    assert run.exit_code == 0
    assert "status=pending_approval" in run.output
    assert draft.exit_code == 0
    assert "approval_request_id=" in draft.output
    assert approvals.exit_code == 0
    assert "pending" in approvals.output
    assert events.exit_code == 0
    assert "workflow.execution" in events.output
    assert backup.exit_code == 0
    assert backup_path.exists()
    assert restore.exit_code == 0
