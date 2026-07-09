from __future__ import annotations

import csv
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from wait_local_agent.api.app import create_app
from wait_local_agent.backup import BackupEncryptionError, backup_state, restore_state
from wait_local_agent.config import load_settings
from wait_local_agent.connectors import (
    draft_halopsa_ticket_action,
    execute_halopsa_approval_request,
    list_connector_statuses,
    list_secret_records,
    update_halopsa_approval_fields,
    validate_connector_credentials,
)
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.hudu import HuduClient, HuduReadResponse
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.security import auth_required
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store
from wait_local_agent.update_channel import UpdateStatus, check_for_updates
from wait_local_agent.vault import SecretVault, SecretVaultError
from wait_local_agent.vector_search import search_backend_from_settings
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
secrets_app = typer.Typer(help="Local Fernet secret vault commands.")
update_app = typer.Typer(help="Signed update channel commands.")
app.add_typer(tickets_app, name="tickets")
app.add_typer(audit_app, name="audit")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(connectors_app, name="connectors")
app.add_typer(workflows_app, name="workflows")
app.add_typer(approvals_app, name="approvals")
app.add_typer(events_app, name="events")
app.add_typer(backup_app, name="backup")
app.add_typer(secrets_app, name="secrets")
app.add_typer(update_app, name="update")


def _store() -> Store:
    return Store(load_settings().data_path)


def _halopsa_client() -> HaloPSAClient:
    return HaloPSAClient(load_settings())


def _hudu_client() -> HuduClient:
    return HuduClient(load_settings())


@app.command()
def doctor() -> None:
    settings = load_settings()
    typer.echo("WAIT Local Agent")
    typer.echo(f"data_path={settings.data_path}")
    typer.echo(f"provider={settings.local_model_provider}")
    typer.echo(f"model={settings.local_model_name}")
    typer.echo(f"base_url={settings.local_model_base_url}")
    typer.echo(f"timeout_seconds={settings.local_model_timeout_seconds:g}")
    typer.echo(f"connector_timeout_seconds={settings.connector_timeout_seconds:g}")
    typer.echo(f"update_channel_url={settings.update_channel_url or '(disabled)'}")
    typer.echo(f"update_pubkeys={len(settings.update_pubkeys)}")
    typer.echo(f"llm_inference_enabled={settings.allow_llm_inference}")
    typer.echo(f"write_actions_enabled={settings.allow_write_actions}")
    typer.echo(f"http_probing_enabled={settings.allow_http_probing}")
    typer.echo(f"cloud_fallback_enabled={settings.allow_cloud_fallback}")
    typer.echo(f"api_auth_required={auth_required(settings)}")
    typer.echo(f"demo_mode={settings.demo_mode}")
    typer.echo(f"secrets_backend={settings.secrets_backend}")
    typer.echo(f"vault_path={settings.vault_path}")
    typer.echo(f"document_parser={settings.document_parser}")
    typer.echo(f"ocr_enabled={settings.allow_ocr}")
    typer.echo(f"vector_backend={settings.vector_backend}")
    halopsa_configured = bool(
        settings.halopsa_base_url
        and settings.halopsa_client_id
        and settings.halopsa_client_secret
        and settings.halopsa_tenant
    )
    typer.echo(f"halopsa_configured={halopsa_configured}")
    hudu_configured = bool(settings.hudu_base_url and settings.hudu_api_key)
    typer.echo(f"hudu_configured={hudu_configured}")


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


@audit_app.command("export")
def export_audit_events(
    destination: Path,
    export_format: Annotated[
        str,
        typer.Option("--format", help="Audit export format: json or csv."),
    ] = "json",
) -> None:
    events = [asdict(event) for event in _store().list_audit_events()]
    if export_format == "json":
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(events, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    elif export_format == "csv":
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("w", encoding="utf-8", newline="") as handle:
            fieldnames = ["id", "event_type", "subject_id", "detail", "created_at", "client_id", "approver_id"]
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(events)
    else:
        raise typer.BadParameter("format must be json or csv")
    typer.echo(f"audit_export={destination} format={export_format} events={len(events)}")


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


@approvals_app.command("show")
def show_approval_request(request_id: int) -> None:
    approval = _store().get_approval_request(request_id)
    if approval is None:
        raise typer.BadParameter("approval request not found")
    typer.echo(json.dumps(_approval_cli_view(approval), sort_keys=True, indent=2))


@approvals_app.command("edit-field")
def edit_approval_field(request_id: int, assignment: str) -> None:
    key, separator, value = assignment.partition("=")
    if not separator or not key.strip():
        raise typer.BadParameter("field edits must use key=value")
    store = _store()
    approval = store.get_approval_request(request_id)
    if approval is None:
        raise typer.BadParameter("approval request not found")
    payload = json.loads(approval.payload_json)
    if not isinstance(payload, dict):
        raise typer.BadParameter("approval payload is malformed")
    fields = payload.get("fields")
    if not isinstance(fields, dict):
        fields = {}
    fields[key.strip()] = value
    try:
        updated = update_halopsa_approval_fields(store, request_id, fields)
    except (PermissionError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"{updated.id} {updated.status} {updated.action_type} payload_updated=True")


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


@connectors_app.command("validate")
def validate_connector(connector: Annotated[str, typer.Argument(help="Connector id: halopsa or hudu.")]) -> None:
    settings = load_settings()
    try:
        result = validate_connector_credentials(
            connector,
            settings,
            halopsa_client=_halopsa_client(),
            hudu_client=_hudu_client(),
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    status = "PASS" if result.passed else "FAIL"
    typer.echo(f"{status} connector={result.connector} layer={result.layer} {result.message}")
    if not result.passed:
        raise typer.Exit(code=1)


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


@connectors_app.command("hudu-health")
def hudu_health() -> None:
    result = _hudu_client().health()
    _audit_hudu_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("hudu-companies")
def hudu_companies(page: int = 1, page_size: int | None = None) -> None:
    _print_hudu_response(
        "companies.list",
        _hudu_client().list_companies(page=page, page_size=page_size),
    )


@connectors_app.command("hudu-articles")
def hudu_articles(
    company_id: str | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> None:
    _print_hudu_response(
        "articles.list",
        _hudu_client().list_articles(company_id=company_id, page=page, page_size=page_size),
    )


@connectors_app.command("hudu-article")
def hudu_article(article_id: str) -> None:
    _print_hudu_response("articles.get", _hudu_client().get_article(article_id))


@connectors_app.command("hudu-folders")
def hudu_folders(
    company_id: str | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> None:
    _print_hudu_response(
        "folders.list",
        _hudu_client().list_folders(company_id=company_id, page=page, page_size=page_size),
    )


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
def ingest_knowledge(
    path: Path,
    parser: str | None = None,
    ocr: bool | None = None,
) -> None:
    loaded_settings = load_settings()
    settings = replace(
        loaded_settings,
        document_parser=parser or loaded_settings.document_parser,
        allow_ocr=loaded_settings.allow_ocr if ocr is None else ocr,
    )
    store = Store(settings.data_path)
    service = ingestion_service_from_settings(store, settings)
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
def search_knowledge(query: str, limit: int = 3, backend: str | None = None) -> None:
    loaded_settings = load_settings()
    settings = replace(loaded_settings, vector_backend=backend or loaded_settings.vector_backend)
    store = Store(settings.data_path)
    for chunk in search_backend_from_settings(settings, store).search(query, limit=limit):
        typer.echo(f"{chunk.id} {chunk.title} ({chunk.path})")
        typer.echo(chunk.excerpt)


@backup_app.command("create")
def create_backup(
    destination: Path,
    encrypt: Annotated[
        bool,
        typer.Option(
            "--encrypt",
            help="Encrypt the backup using the local Fernet vault key.",
        ),
    ] = False,
) -> None:
    settings = load_settings()
    try:
        path = backup_state(_store(), destination, encrypt=encrypt, settings=settings)
    except BackupEncryptionError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"backup={path}")


@backup_app.command("restore")
def restore_backup(
    source: Path,
    encrypted: Annotated[
        bool,
        typer.Option(
            "--encrypted",
            help="Restore from an encrypted backup created with --encrypt.",
        ),
    ] = False,
) -> None:
    settings = load_settings()
    try:
        path = restore_state(_store(), source, encrypted=encrypted, settings=settings)
    except BackupEncryptionError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"restored={path}")


@secrets_app.command("init")
def init_secret_vault() -> None:
    settings = load_settings()
    vault = SecretVault.initialize(settings.vault_path)
    typer.echo(f"vault_initialized={vault.vault_path}")


@secrets_app.command("set")
def set_secret(key: str, value: str) -> None:
    settings = load_settings()
    vault = SecretVault.initialize(settings.vault_path)
    try:
        vault.set(key, value)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"secret_stored={key}")


@secrets_app.command("list")
def list_vault_secrets() -> None:
    settings = load_settings()
    try:
        keys = SecretVault(settings.vault_path).list_keys()
    except SecretVaultError as exc:
        raise typer.BadParameter(str(exc)) from exc
    for key in keys:
        typer.echo(key)


@secrets_app.command("get")
def get_secret(key: str) -> None:
    settings = load_settings()
    try:
        value = SecretVault(settings.vault_path).get(key)
    except (SecretVaultError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    if value is None:
        raise typer.BadParameter("secret not found")
    typer.echo(value)


@update_app.command("check")
def update_check() -> None:
    try:
        status = check_for_updates(load_settings())
    except Exception as exc:
        typer.echo(f"status=error detail=internal_error message={exc}")
        raise typer.Exit(code=1) from exc
    typer.echo(_format_update_status(status))


def _print_halopsa_response(read_type: str, response: HaloReadResponse) -> None:
    _audit_halopsa_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(f"{response.result.status} count={response.result.count} {response.result.message}")
    for item in response.items:
        typer.echo(asdict(item))


def _print_hudu_response(read_type: str, response: HuduReadResponse) -> None:
    _audit_hudu_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(f"{response.result.status} count={response.result.count} {response.result.message}")
    for item in response.items:
        typer.echo(asdict(item))


def _audit_halopsa_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("halopsa.read", read_type, f"{status} count={count}")


def _audit_hudu_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("hudu.read", read_type, f"{status} count={count}")


def _approval_cli_view(approval) -> dict[str, object]:
    payload = json.loads(approval.payload_json)
    return {
        **asdict(approval),
        "payload": payload if isinstance(payload, dict) else {},
    }


def _format_update_status(status: UpdateStatus) -> str:
    if status.status == "update_available":
        return (
            "status=update_available "
            f"current_version={status.current_version} "
            f"remote_version={status.remote_version} "
            f"notes_url={status.notes_url}"
        )
    if status.status == "up_to_date":
        return (
            "status=up_to_date "
            f"current_version={status.current_version} "
            f"remote_version={status.remote_version}"
        )
    if status.status == "invalid_signature":
        return "status=invalid_signature warning=update_metadata_signature_invalid"
    return f"status=unknown detail={status.detail}"


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8788) -> None:
    uvicorn.run(create_app(), host=host, port=port)
