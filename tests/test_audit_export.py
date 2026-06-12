from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.store import Store


def test_audit_export_api_json_and_csv(settings) -> None:
    Store(settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(settings))

    json_export = client.get("/audit/export")
    csv_export = client.get("/audit/export", params={"export_format": "csv"})

    assert json_export.status_code == 200
    assert json_export.headers["content-type"].startswith("application/json")
    assert "ticket.ingested" in json_export.text
    assert csv_export.status_code == 200
    assert csv_export.headers["content-type"].startswith("text/csv")
    assert "event_type" in csv_export.text
    assert "ticket.ingested" in csv_export.text


def test_audit_export_cli_json_and_csv(monkeypatch, tmp_path) -> None:
    data_path = tmp_path / "state.db"
    json_path = tmp_path / "audit.json"
    csv_path = tmp_path / "audit.csv"
    monkeypatch.setenv("WAIT_DATA_PATH", str(data_path))
    runner = CliRunner()

    runner.invoke(app, ["ingest", "examples/sample_tickets"])
    json_export = runner.invoke(app, ["audit", "export", str(json_path)])
    csv_export = runner.invoke(app, ["audit", "export", str(csv_path), "--format", "csv"])

    assert json_export.exit_code == 0
    assert csv_export.exit_code == 0
    assert "ticket.ingested" in json_path.read_text(encoding="utf-8")
    assert "event_type" in csv_path.read_text(encoding="utf-8")
    assert "ticket.ingested" in csv_path.read_text(encoding="utf-8")


def test_secret_vault_cli_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_VAULT_PATH", str(tmp_path / "vault"))
    runner = CliRunner()

    initialized = runner.invoke(app, ["secrets", "init"])
    stored = runner.invoke(app, ["secrets", "set", "WAIT_HUDU_API_KEY", "stored-secret"])
    listed = runner.invoke(app, ["secrets", "list"])
    revealed = runner.invoke(app, ["secrets", "get", "WAIT_HUDU_API_KEY"])
    missing = runner.invoke(app, ["secrets", "get", "WAIT_HALOPSA_CLIENT_SECRET"])

    assert initialized.exit_code == 0
    assert stored.exit_code == 0
    assert listed.exit_code == 0
    assert "WAIT_HUDU_API_KEY" in listed.output
    assert "stored-secret" not in listed.output
    assert revealed.exit_code == 0
    assert "stored-secret" in revealed.output
    assert missing.exit_code != 0
    assert "secret not found" in missing.output
