from __future__ import annotations

from typer.testing import CliRunner

import wait_local_agent.cli as cli_module
from wait_local_agent.cli import app
from wait_local_agent.models import (
    HaloClient,
    HaloReadResult,
    HaloTicket,
    HaloWriteResult,
    HuduArticle,
    HuduCompany,
    HuduFolder,
)
from wait_local_agent.store import Store


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
            return _hudu_response([HuduArticle("A-1", "Runbook", "C-1", "F-1", "", "")])

        def get_article(self, article_id: str):
            return _hudu_response([HuduArticle(article_id, "Runbook", "C-1", "F-1", "", "")])

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
    assert article.exit_code == 0
    assert "A-1" in article.output
    assert folders.exit_code == 0
    assert "Ops" in folders.output


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
            "fields": {"note": "Original"},
        },
    )
    runner = CliRunner()

    shown = runner.invoke(app, ["approvals", "show", str(approval.id)])
    edited = runner.invoke(app, ["approvals", "edit-field", str(approval.id), "note=Edited"])
    store.update_approval_request(approval.id or 0, "approved")
    rejected = runner.invoke(app, ["approvals", "edit-field", str(approval.id), "note=Late"])

    assert shown.exit_code == 0
    assert "Original" in shown.output
    assert edited.exit_code == 0
    assert "payload_updated=True" in edited.output
    assert rejected.exit_code != 0
    assert "only be edited while pending" in rejected.output


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


def _read_response(items):
    return cli_module.HaloReadResponse(HaloReadResult("ready", "ok", len(items)), items)


def _hudu_response(items):
    return cli_module.HuduReadResponse(HaloReadResult("ready", "ok", len(items)), items)
