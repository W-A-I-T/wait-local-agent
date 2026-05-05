from __future__ import annotations

from typer.testing import CliRunner

from wait_local_agent.cli import app


def test_doctor_command_reports_safe_defaults(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()

    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
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
