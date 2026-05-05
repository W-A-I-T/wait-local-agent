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

