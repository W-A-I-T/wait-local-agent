from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from wait_local_agent.api.app import create_app
from wait_local_agent.backup import backup_state, restore_state
from wait_local_agent.config import load_settings
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_halopsa_approval_request,
    list_connector_statuses,
    list_secret_records,
)
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.knowledge import KnowledgeIngestionService
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store
from wait_local_agent.workflows import list_workflow_templates, run_workflow_template

app = typer.Typer(help="WAIT Local Agent command line interface.")
tickets_app = typer.Typer(help="Ticket intelligence commands.")
audit_app = typer.Typer(help="Audit log commands.")
knowledge_app = typer.Typer(help="Local knowledge base commands.")
connectors_app = typer.Typer(help="Connector status and safe draft commands.")
workflows_app = typer.Typer(help="Workflow template and run commands.")
approvals_app = typer.Typer(help="Approval queue commands.")
events_app = typer.Typer(help="Event history commands.")
backup_app = typer.Typer(help="SQLite backup and restore commands.")
app.add_typer(tickets_app, name="tickets")
app.add_typer(audit_app, name="audit")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(connectors_app, name="connectors")
app.add_typer(workflows_app, name="workflows")
app.add_typer(approvals_app, name="approvals")
app.add_typer(events_app, name="events")
app.add_typer(backup_app, name="backup")


def _store() -> Store:
    return Store(load_settings().data_path)


def _halopsa_client() -> HaloPSAClient:
    return HaloPSAClient(load_settings())


@app.command()
def doctor() -> None:
    settings = load_settings()
    typer.echo("WAIT Local Agent")
    typer.echo(f"data_path={settings.data_path}")
    typer.echo(f"provider={settings.local_model_provider}")
    typer.echo(f"model={settings.local_model_name}")
    typer.echo(f"base_url={settings.local_model_base_url}")
    typer.echo(f"timeout_seconds={settings.local_model_timeout_seconds:g}")
    typer.echo(f"llm_inference_enabled={settings.allow_llm_inference}")
    typer.echo(f"write_actions_enabled={settings.allow_write_actions}")
    typer.echo(f"http_probing_enabled={settings.allow_http_probing}")
    typer.echo(f"cloud_fallback_enabled={settings.allow_cloud_fallback}")
    halopsa_configured = bool(
        settings.halopsa_base_url
        and settings.halopsa_client_id
        and settings.halopsa_client_secret
        and settings.halopsa_tenant
    )
    typer.echo(f"halopsa_configured={halopsa_configured}")


@app.command()
def ingest(path: Path) -> None:
    store = _store()
    ticket_files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    count = 0
    for ticket_file in ticket_files:
        count += store.ingest_ticket_file(ticket_file)
    typer.echo(f"ingested={count}")


@tickets_app.command("summarize")
def summarize_ticket(ticket_id: str) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    service = TicketIntelligenceService(store, settings, provider_from_settings(settings))
    summary = service.summarize(ticket_id)
    typer.echo(f"classification={summary.classification}")
    typer.echo(summary.summary)
    typer.echo(summary.suggested_response)
    for source in summary.sources:
        typer.echo(f"source={source.title} ({source.path})")


@audit_app.command("list")
def list_audit_events() -> None:
    for event in _store().list_audit_events():
        typer.echo(f"{event.id} {event.event_type} {event.subject_id} {event.detail}")


@events_app.command("list")
def list_event_history() -> None:
    for event in _store().list_event_history():
        typer.echo(
            f"{event.id} {event.event_type} {event.subject_id} "
            f"{event.status} {event.message}"
        )


@approvals_app.command("list")
def list_approval_requests() -> None:
    for approval in _store().list_approval_requests():
        typer.echo(
            f"{approval.id} {approval.status} {approval.subject_id} "
            f"{approval.action_type} {approval.comment}"
        )


@approvals_app.command("update")
def update_approval_request(
    request_id: int,
    status: str,
    comment: str = "",
) -> None:
    store = _store()
    approval = store.update_approval_request(request_id, status, comment)
    if status == "approved" and approval.action_type.startswith("halopsa."):
        try:
            approval = execute_halopsa_approval_request(store, _halopsa_client(), request_id)
        except RuntimeError:
            approval = store.get_approval_request(request_id) or approval
    typer.echo(
        f"{approval.id} {approval.status} {approval.subject_id} {approval.action_type} "
        f"execution_status={approval.execution_status} "
        f"execution_message={approval.execution_message}"
    )


@connectors_app.command("list")
def list_connectors() -> None:
    settings = load_settings()
    for connector in list_connector_statuses(settings):
        typer.echo(f"{connector.id} {connector.status} {connector.message}")


@connectors_app.command("secrets")
def list_secrets() -> None:
    settings = load_settings()
    for secret in list_secret_records(settings):
        typer.echo(
            f"{secret.key} configured={secret.configured} "
            f"required_for={secret.required_for}"
        )


@connectors_app.command("draft-halopsa")
def draft_halopsa(
    ticket_id: str,
    action_type: str,
    field: Annotated[
        list[str] | None,
        typer.Option(
            "--field",
            help="Field assignment as key=value. Repeat for multiple fields.",
        ),
    ] = None,
) -> None:
    fields: dict[str, object] = {}
    for item in field or []:
        key, separator, value = item.partition("=")
        if not separator:
            raise typer.BadParameter("fields must use key=value")
        fields[key] = value
    try:
        draft = draft_halopsa_ticket_action(_store(), ticket_id, action_type, fields)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={draft.approval_request_id} "
        f"ticket_id={draft.ticket_id} action_type={draft.action_type} status={draft.status}"
    )


@connectors_app.command("execute-halopsa")
def execute_halopsa(request_id: int) -> None:
    try:
        approval = execute_halopsa_approval_request(_store(), _halopsa_client(), request_id)
    except KeyError as exc:
        raise typer.BadParameter("approval request not found") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"{approval.id} {approval.action_type} ticket_id={approval.subject_id} "
        f"execution_status={approval.execution_status} "
        f"execution_message={approval.execution_message}"
    )


@connectors_app.command("halopsa-health")
def halopsa_health() -> None:
    result = _halopsa_client().health()
    _audit_halopsa_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("halopsa-write-health")
def halopsa_write_health() -> None:
    result = _halopsa_client().write_health()
    _store().add_audit_event("halopsa.write_health", "halopsa", result.status)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("halopsa-tickets")
def halopsa_tickets(page: int = 1, page_size: int = 50) -> None:
    _print_halopsa_response("tickets.list", _halopsa_client().list_tickets(page, page_size))


@connectors_app.command("halopsa-ticket")
def halopsa_ticket(ticket_id: str) -> None:
    _print_halopsa_response("tickets.get", _halopsa_client().get_ticket(ticket_id))


@connectors_app.command("halopsa-notes")
def halopsa_notes(ticket_id: str) -> None:
    _print_halopsa_response("tickets.notes", _halopsa_client().list_ticket_notes(ticket_id))


@connectors_app.command("halopsa-clients")
def halopsa_clients(page: int = 1, page_size: int = 50) -> None:
    _print_halopsa_response("clients.list", _halopsa_client().list_clients(page, page_size))


@connectors_app.command("halopsa-assets")
def halopsa_assets(client_id: str) -> None:
    _print_halopsa_response("clients.assets", _halopsa_client().list_client_assets(client_id))


@connectors_app.command("halopsa-categories")
def halopsa_categories() -> None:
    _print_halopsa_response("categories.list", _halopsa_client().list_categories())


@workflows_app.command("templates")
def list_workflows() -> None:
    for template in list_workflow_templates():
        typer.echo(
            f"{template.id} {template.trigger} approval_required={template.approval_required}"
        )


@workflows_app.command("run")
def run_workflow(template_id: str, ticket_id: str) -> None:
    run = run_workflow_template(_store(), template_id, ticket_id)
    typer.echo(f"run_id={run.id} status={run.status} ticket_id={run.ticket_id}")


@knowledge_app.command("ingest")
def ingest_knowledge(path: Path) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    service = KnowledgeIngestionService(store, settings.allowed_doc_root)
    documents = service.ingest_path(path)
    typer.echo(f"documents={len(documents)}")
    for document in documents:
        typer.echo(
            f"{document.id} {document.title} chunks={document.chunk_count} path={document.path}"
        )


@knowledge_app.command("list")
def list_knowledge_documents() -> None:
    for document in _store().list_knowledge_documents():
        typer.echo(
            f"{document.id} {document.title} chunks={document.chunk_count} path={document.path}"
        )


@knowledge_app.command("search")
def search_knowledge(query: str, limit: int = 3) -> None:
    for chunk in _store().search_knowledge_chunks(query, limit=limit):
        typer.echo(f"{chunk.id} {chunk.title} ({chunk.path})")
        typer.echo(chunk.excerpt)


@backup_app.command("create")
def create_backup(destination: Path) -> None:
    path = backup_state(_store(), destination)
    typer.echo(f"backup={path}")


@backup_app.command("restore")
def restore_backup(source: Path) -> None:
    path = restore_state(_store(), source)
    typer.echo(f"restored={path}")


def _print_halopsa_response(read_type: str, response: HaloReadResponse) -> None:
    _audit_halopsa_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(f"{response.result.status} count={response.result.count} {response.result.message}")
    for item in response.items:
        typer.echo(asdict(item))


def _audit_halopsa_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("halopsa.read", read_type, f"{status} count={count}")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8788) -> None:
    uvicorn.run(create_app(), host=host, port=port)
