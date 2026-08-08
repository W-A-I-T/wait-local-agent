from __future__ import annotations

import csv
import json
import logging
from collections.abc import Iterable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Annotated, cast

import typer
import uvicorn
from fastapi import HTTPException

from wait_local_agent.agents import AgentService
from wait_local_agent.api.app import create_app
from wait_local_agent.api.founder import (
    FOUNDER_INSTALL_HINT,
    FounderNotConfiguredError,
    FounderPackContractError,
    FounderPackUnavailableError,
    FounderUploadConflictError,
    build_upload_preview,
    configure_founder,
    invoke_founder,
    json_object,
    open_founder_launch_scan,
    open_founder_preview,
    open_founder_results,
    open_founder_scan,
    open_founder_status,
    open_founder_upload,
    require_founder_pack,
    require_fresh_preview,
    resolve_open_config,
    sanitized_pack_bundle,
    watch_founder_scan,
)
from wait_local_agent.api.founder import (
    render_json as render_founder_json,
)
from wait_local_agent.api.packs.loader import (
    PackInstallError,
    configure_pack_cli,
    install_pack_tarball,
    load_pack_registry,
)
from wait_local_agent.autotask import AutotaskClient, AutotaskReadResponse
from wait_local_agent.backup import BackupEncryptionError, backup_state, restore_state, run_restore_exercise
from wait_local_agent.collectors import (
    CollectorService,
    collector_run_collection_scope,
    collector_run_result_status,
)
from wait_local_agent.config import load_settings
from wait_local_agent.confluence import ConfluenceClient, ConfluenceReadResponse
from wait_local_agent.connectors import (
    draft_connectwise_ticket_action,
    draft_halopsa_ticket_action,
    draft_m365_group_membership,
    draft_m365_license_change,
    draft_m365_mailbox_settings_update,
    draft_m365_managed_device_retirement,
    draft_m365_session_revocation,
    draft_m365_user_creation,
    draft_m365_user_disable,
    execute_connectwise_approval_request,
    execute_halopsa_approval_request,
    execute_m365_approval_request,
    list_connector_statuses,
    list_secret_records,
    update_connectwise_approval_fields,
    update_halopsa_approval_fields,
    validate_connector_credentials,
)
from wait_local_agent.connectwise import ConnectWiseClient, ConnectWiseReadResponse
from wait_local_agent.event_dispatch import EventDispatcher
from wait_local_agent.halopsa import HaloPSAClient, HaloReadResponse
from wait_local_agent.hudu import HuduClient, HuduReadResponse
from wait_local_agent.itglue import ItGlueClient, ItGlueReadResponse
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.m365_graph import (
    M365GraphClient,
    M365GraphGroupReadResponse,
    M365GraphLicenseReadResponse,
    M365GraphMailFolderReadResponse,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadResponse,
)
from wait_local_agent.observability import build_analytics_summary
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.rbac import Role, resolve_auth_context
from wait_local_agent.reports.builders import (
    build_appliance_hardening_report,
    build_restore_evidence_report,
)
from wait_local_agent.reports.hardening_checks import HardeningContext, run_hardening_checks
from wait_local_agent.reports.models import ReportFormat, ReportType
from wait_local_agent.reports.renderers import redact_text, redact_value
from wait_local_agent.reports.renderers import render_json as render_report_json
from wait_local_agent.reports.service import ReportService
from wait_local_agent.security import auth_required
from wait_local_agent.servicenow import ServiceNowClient, ServiceNowReadResponse
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.sharepoint import SharePointClient, SharePointReadResponse
from wait_local_agent.smart_actions import SmartActionService
from wait_local_agent.store import Store
from wait_local_agent.syncro import SyncroClient, SyncroReadResponse
from wait_local_agent.technician_chat import TechnicianChatParseError, parse_technician_message
from wait_local_agent.update_channel import UpdateStatus, check_for_updates
from wait_local_agent.vault import SecretVault, SecretVaultError
from wait_local_agent.vector_search import search_backend_from_settings
from wait_local_agent.workflows import (
    get_workflow_template,
    list_workflow_templates,
    run_workflow_template,
)

app = typer.Typer(help="WAIT Local Agent command line interface.")
tickets_app = typer.Typer(help="Ticket intelligence commands.")
audit_app = typer.Typer(help="Audit log commands.")
knowledge_app = typer.Typer(help="Local knowledge base commands.")
connectors_app = typer.Typer(help="Connector status and safe draft commands.")
workflows_app = typer.Typer(help="Workflow template and run commands.")
approvals_app = typer.Typer(help="Approval queue commands.")
events_app = typer.Typer(help="Event history commands.")
backup_app = typer.Typer(help="SQLite backup and restore commands.")
hardening_app = typer.Typer(help="Appliance hardening check commands.")
secrets_app = typer.Typer(help="Local Fernet secret vault commands.")
update_app = typer.Typer(help="Signed update channel commands.")
packs_app = typer.Typer(help="Installed pack commands.")
founder_app = typer.Typer(help="Founder pack commands.")
reports_app = typer.Typer(help="Stored report list, detail, and export commands.")
collectors_app = typer.Typer(help="Collector module protocol commands.")
collector_bundle_app = typer.Typer(help="Collector evidence bundle commands.")
smart_actions_app = typer.Typer(help="Smart action commands.")
executions_app = typer.Typer(help="Execution observability commands.")
analytics_app = typer.Typer(help="Execution analytics commands.")
agents_app = typer.Typer(help="Bounded agent definition commands.")
app.add_typer(tickets_app, name="tickets")
app.add_typer(audit_app, name="audit")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(connectors_app, name="connectors")
app.add_typer(workflows_app, name="workflows")
app.add_typer(approvals_app, name="approvals")
app.add_typer(events_app, name="events")
app.add_typer(backup_app, name="backup")
app.add_typer(hardening_app, name="hardening")
app.add_typer(secrets_app, name="secrets")
app.add_typer(update_app, name="update")
app.add_typer(packs_app, name="packs")
app.add_typer(founder_app, name="founder")
LOGGER = logging.getLogger(__name__)
_PACK_CLI_NAMES: set[str] = set()
app.add_typer(reports_app, name="reports")
collectors_app.add_typer(collector_bundle_app, name="bundle")
app.add_typer(collectors_app, name="collectors")
app.add_typer(smart_actions_app, name="smart-actions")
app.add_typer(executions_app, name="executions")
app.add_typer(analytics_app, name="analytics")
app.add_typer(agents_app, name="agents")


def _store() -> Store:
    return Store(load_settings().data_path)


def _collector_service() -> CollectorService:
    return CollectorService(_store())


def _halopsa_client() -> HaloPSAClient:
    return HaloPSAClient(load_settings())


def _hudu_client() -> HuduClient:
    return HuduClient(load_settings())


def _connectwise_client() -> ConnectWiseClient:
    return ConnectWiseClient(load_settings())


def _syncro_client() -> SyncroClient:
    return SyncroClient(load_settings())


def _servicenow_client() -> ServiceNowClient:
    return ServiceNowClient(load_settings())


def _autotask_client() -> AutotaskClient:
    return AutotaskClient(load_settings())


def _itglue_client() -> ItGlueClient:
    return ItGlueClient(load_settings())


def _confluence_client() -> ConfluenceClient:
    return ConfluenceClient(load_settings())


def _sharepoint_client() -> SharePointClient:
    return SharePointClient(load_settings())


def _m365_client() -> M365GraphClient:
    return M365GraphClient(load_settings())


def sync_pack_cli(candidate_module_names: Iterable[str] | None = None) -> None:
    app.registered_groups = [
        group for group in app.registered_groups if getattr(group, "name", None) not in _PACK_CLI_NAMES
    ]
    _PACK_CLI_NAMES.clear()
    registry = configure_pack_cli(app, load_settings(), candidate_module_names)
    _PACK_CLI_NAMES.update(status.name for status in registry.statuses if status.mounted_cli)


@app.command()
def doctor() -> None:
    settings = load_settings()
    sync_pack_cli()
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
    syncro_configured = bool(settings.syncro_base_url and settings.syncro_api_token)
    typer.echo(f"syncro_configured={syncro_configured}")
    servicenow_configured = bool(
        settings.servicenow_base_url
        and settings.servicenow_username
        and settings.servicenow_password
    )
    typer.echo(f"servicenow_configured={servicenow_configured}")
    autotask_configured = bool(
        settings.autotask_base_url
        and settings.autotask_username
        and settings.autotask_secret
        and settings.autotask_integration_code
    )
    typer.echo(f"autotask_configured={autotask_configured}")
    itglue_configured = bool(settings.itglue_base_url and settings.itglue_api_key)
    typer.echo(f"itglue_configured={itglue_configured}")
    confluence_configured = bool(
        settings.confluence_base_url
        and settings.confluence_email
        and settings.confluence_api_token
    )
    typer.echo(f"confluence_configured={confluence_configured}")
    sharepoint_configured = bool(
        settings.sharepoint_base_url and settings.sharepoint_access_token
    )
    typer.echo(f"sharepoint_configured={sharepoint_configured}")
    m365_configured = bool(settings.m365_graph_base_url and settings.m365_access_token)
    typer.echo(f"m365_configured={m365_configured}")
    typer.echo(f"packs_discovered={len(load_pack_registry(settings).statuses)}")
    typer.echo(f"founder_lp_status={_doctor_founder_lp_status()}")


@packs_app.command("list")
def list_packs() -> None:
    sync_pack_cli()
    registry = load_pack_registry(load_settings())
    if not registry.statuses:
        typer.echo("no packs discovered")
        return
    for status in registry.statuses:
        typer.echo(f"{status.name} {status.version} {'locked' if status.locked else 'unlocked'}")


@packs_app.command("status")
def status_packs() -> None:
    sync_pack_cli()
    registry = load_pack_registry(load_settings())
    if not registry.statuses:
        typer.echo("no packs discovered")
        return
    for status in registry.statuses:
        typer.echo(
            f"{status.name} version={status.version} state={'locked' if status.locked else 'unlocked'} "
            f"router={status.router_available} cli={status.cli_available}"
        )


@packs_app.command("install")
def install_pack(
    tarball: Path,
    license_key: Annotated[
        str | None,
        typer.Option("--license", help="Pack license key to store after install."),
    ] = None,
) -> None:
    try:
        result = install_pack_tarball(
            tarball,
            license_key=license_key,
            settings=load_settings(),
        )
    except PackInstallError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"installed={result.pack_name} version={result.version} files={len(result.extracted_files)} "
        f"license_stored_in_vault={result.license_stored_in_vault}"
    )
    if license_key and not result.license_stored_in_vault:
        typer.echo("set WAIT_LICENSE_KEY in the environment to unlock licensed packs")


@founder_app.command("scan")
def founder_scan(path: Path) -> None:
    pack = _founder_pack_or_none()
    if pack is None:
        settings, store, config = _open_cli_config()
        response = open_founder_scan(store, settings, config, path)
    else:
        response = json_object(invoke_founder(pack, "scan", path), operation="scan")
    typer.echo(render_founder_json(response))


@founder_app.command("configure")
def founder_configure(
    base_url: Annotated[str, typer.Option("--base-url")],
    project_id: Annotated[str, typer.Option("--project-id")],
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            help="Token for scripting only; visible in shell history/process arguments. Prefer the hidden prompt.",
        ),
    ] = None,
) -> None:
    token_value = token if token is not None else typer.prompt("Launch Passport token", hide_input=True)
    try:
        response = configure_founder(load_settings(), _store(), base_url, project_id, token_value)
    except (ValueError, SecretVaultError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(render_founder_json(response))


@founder_app.command("preview")
def founder_preview(artifact_id: Annotated[str, typer.Argument()]) -> None:
    pack = _founder_pack_or_none()
    if pack is None:
        _, store, _ = _open_cli_config()
        try:
            response = open_founder_preview(store, artifact_id)
        except KeyError as exc:
            raise typer.BadParameter("artifact not found") from exc
        store.mark_founder_artifact_previewed(artifact_id)
    else:
        bundle = sanitized_pack_bundle(pack, artifact_id)
        response = build_upload_preview(artifact_id, bundle)
        _store().mark_founder_artifact_previewed(artifact_id)
    typer.echo(render_founder_json(response))


@founder_app.command("preflight")
def founder_preflight() -> None:
    response = json_object(_invoke_founder_cli("preflight_latest"), operation="preflight_latest")
    typer.echo(render_founder_json(response))


@founder_app.command("handoff")
def founder_handoff(output: Annotated[Path, typer.Option("--output")]) -> None:
    response = _invoke_founder_cli("handoff")
    output.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(response, str):
        output.write_text(response, encoding="utf-8")
    else:
        output.write_text(render_founder_json(response) + "\n", encoding="utf-8")
    typer.echo(f"handoff={output}")


@founder_app.command("export-bundle")
def founder_export_bundle(
    artifact_id: Annotated[str, typer.Option("--artifact-id")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    bundle = json_object(_invoke_founder_cli("export_bundle", artifact_id), operation="export_bundle")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_founder_json(bundle) + "\n", encoding="utf-8")
    typer.echo(f"bundle={output} artifact_id={artifact_id}")


@founder_app.command("upload")
def founder_upload(
    artifact_id: Annotated[str, typer.Option("--artifact-id")],
    yes: Annotated[bool, typer.Option("--yes", help="Confirm the upload after printing the preview.")] = False,
) -> None:
    pack = _founder_pack_or_none()
    if pack is None:
        settings, store, config = _open_cli_config()
        if not yes:
            typer.echo("upload requires a prior preview; run `founder preview ARTIFACT_ID`, then re-run with --yes")
            raise typer.Exit(code=1)
        try:
            require_fresh_preview(store, artifact_id)
        except FounderUploadConflictError as exc:
            raise typer.BadParameter(str(exc)) from exc
        response = open_founder_upload(settings, store, config, artifact_id)
    else:
        bundle = sanitized_pack_bundle(pack, artifact_id)
        typer.echo(render_founder_json(build_upload_preview(artifact_id, bundle)))
        if not yes:
            typer.echo("re-run with --yes after this preview to confirm upload")
            raise typer.Exit(code=1)
        try:
            require_fresh_preview(_store(), artifact_id)
        except FounderUploadConflictError as exc:
            raise typer.BadParameter(str(exc)) from exc
        response = json_object(invoke_founder(pack, "upload", artifact_id, bundle), operation="upload")
    typer.echo(render_founder_json(response))


@founder_app.command("status")
def founder_status() -> None:
    pack = _founder_pack_or_none()
    if pack is not None:
        response = json_object(invoke_founder(pack, "lp_status"), operation="lp_status")
    else:
        settings, _, config = _open_cli_config()
        response = open_founder_status(settings, config)
    typer.echo(render_founder_json(response))


@founder_app.command("results")
def founder_results(
    watch: Annotated[bool, typer.Option("--watch", help="Poll a scan until it reaches a terminal state.")] = False,
    scan_id: Annotated[str | None, typer.Option("--scan-id")] = None,
    artifact_id: Annotated[str | None, typer.Option("--artifact-id")] = None,
    max_duration: Annotated[float, typer.Option("--max-duration", min=1.0)] = 3600.0,
    max_attempts: Annotated[int, typer.Option("--max-attempts", min=1)] = 120,
) -> None:
    pack = _founder_pack_or_none()
    if pack is not None:
        response = json_object(invoke_founder(pack, "results"), operation="results")
    else:
        settings, store, config = _open_cli_config()
        response = open_founder_results(settings, config)
        if watch:
            selected_scan_id = scan_id or _latest_scan_id(response.get("scans"))
            if not selected_scan_id:
                raise typer.BadParameter("no scan id was returned; pass --scan-id")
            response = watch_founder_scan(
                settings,
                store,
                config,
                selected_scan_id,
                artifact_id=artifact_id,
                max_duration=max_duration,
                max_attempts=max_attempts,
            )
    typer.echo(render_founder_json(response))


@founder_app.command("launch-scan")
def founder_launch_scan(
    artifact_id: Annotated[str | None, typer.Option("--artifact-id")] = None,
    watch: Annotated[
        bool, typer.Option("--watch", help="Poll the launched scan until it reaches a terminal state.")
    ] = False,
    max_duration: Annotated[float, typer.Option("--max-duration", min=1.0)] = 3600.0,
    max_attempts: Annotated[int, typer.Option("--max-attempts", min=1)] = 120,
) -> None:
    pack = _founder_pack_or_none()
    if pack is not None:
        response = json_object(invoke_founder(pack, "launch_scan"), operation="launch_scan")
        typer.echo(render_founder_json(response))
        return
    settings, store, config = _open_cli_config()
    response = open_founder_launch_scan(settings, store, config, artifact_id)
    if watch and response.get("status") not in {"not_authorized", "insufficient_credits", "rate_limited"}:
        selected_scan_id = _scan_id_from_response(response)
        if not selected_scan_id:
            raise typer.BadParameter("Launch Passport did not return a scan id")
        response = watch_founder_scan(
            settings,
            store,
            config,
            selected_scan_id,
            artifact_id=artifact_id,
            max_duration=max_duration,
            max_attempts=max_attempts,
        )
    typer.echo(render_founder_json(response))


def _latest_scan_id(scans: object) -> str:
    if not isinstance(scans, list) or not scans:
        return ""
    candidate = scans[0]
    return _scan_id_from_response(candidate) if isinstance(candidate, dict) else ""


def _scan_id_from_response(response: dict[str, object]) -> str:
    nested = response.get("scan")
    if isinstance(nested, dict):
        for key in ("scanId", "scan_id", "id"):
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    for key in ("scanId", "scan_id"):
        value = response.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


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


@app.command("technician-chat")
def technician_chat(
    message: str,
    ticket_id: Annotated[str | None, typer.Option("--ticket-id")] = None,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    try:
        command = parse_technician_message(message, ticket_id=ticket_id)
    except TechnicianChatParseError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if command.action_id is None:
        typer.echo(command.reply)
        return
    settings = load_settings()
    service = SmartActionService(Store(settings.data_path), settings)
    result = service.invoke(command.action_id, command.payload, "cli", client_id=client_id)
    typer.echo(
        json.dumps(
            {
                "status": result.status,
                "message": command.reply,
                "action_id": command.action_id,
                "result": asdict(result),
            },
            sort_keys=True,
        )
    )


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
            f"{approval.action_type} expires={approval.expires_at or '-'} "
            f"{redact_text(approval.comment)}"
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
        if approval.action_type.startswith("connectwise."):
            updated = update_connectwise_approval_fields(store, request_id, fields)
        else:
            updated = update_halopsa_approval_fields(store, request_id, fields)
    except (PermissionError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(f"{updated.id} {updated.status} {updated.action_type} payload_updated=True")


@approvals_app.command("update")
def update_approval_request(
    request_id: int,
    status: str,
    comment: str = "",
    token: Annotated[str | None, typer.Option("--token", envvar="WAIT_CLI_TOKEN")] = None,
) -> None:
    store = _store()
    existing = store.get_approval_request(request_id)
    if existing is None:
        raise typer.BadParameter("approval request not found")
    if existing.action_type.startswith("smart_action:"):
        settings = load_settings()
        context = _cli_access(settings, token, Role.TECHNICIAN)
        service = SmartActionService(
            store,
            settings,
            collector_service=CollectorService(store),
            connectwise_client=_connectwise_client(),
        )
        try:
            approval = service.update_approval(
                request_id,
                status,
                comment,
                approver=context.approver_id or "cli",
                approver_role=context.role,
            )
        except (PermissionError, ValueError) as exc:
            raise typer.BadParameter(str(exc)) from exc
    elif existing.action_type.startswith("m365."):
        context = _cli_access(load_settings(), token, Role.ADMIN)
        approval = store.update_approval_request(
            request_id,
            status,
            comment,
            approver_id=context.approver_id,
        )
    else:
        approval = store.update_approval_request(
            request_id,
            status,
            comment,
            allow_completed=store.get_workflow_run_for_approval(request_id) is not None,
        )
    if status == "approved" and approval.action_type.startswith("halopsa."):
        try:
            approval = execute_halopsa_approval_request(store, _halopsa_client(), request_id)
        except RuntimeError:
            approval = store.get_approval_request(request_id) or approval
    if status == "approved" and approval.action_type.startswith("connectwise."):
        try:
            approval = execute_connectwise_approval_request(
                store, _connectwise_client(), request_id
            )
        except RuntimeError:
            approval = store.get_approval_request(request_id) or approval
    if status == "approved" and approval.action_type.startswith("m365."):
        try:
            approval = execute_m365_approval_request(
                store,
                _m365_client(),
                SecretVault(load_settings().vault_path),
                request_id,
            )
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
def validate_connector(
    connector: Annotated[
        str,
        typer.Argument(
            help=(
                "Connector id: halopsa, hudu, connectwise, syncro, servicenow, "
                "autotask, itglue, or confluence."
                " SharePoint and m365 are also supported for read-only connector reads."
            )
        ),
    ]
) -> None:
    settings = load_settings()
    try:
        result = validate_connector_credentials(
            connector,
            settings,
            halopsa_client=_halopsa_client(),
            hudu_client=_hudu_client(),
            connectwise_client=_connectwise_client(),
            syncro_client=_syncro_client(),
            servicenow_client=_servicenow_client(),
            autotask_client=_autotask_client(),
            itglue_client=_itglue_client(),
            confluence_client=_confluence_client(),
            sharepoint_client=_sharepoint_client(),
            m365_client=_m365_client(),
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


@connectors_app.command("draft-m365-user")
def draft_m365_user(
    user_principal_name: str,
    display_name: str,
    mail_nickname: str,
    temporary_vault_name: str,
    client_id: str | None = None,
    account_enabled: bool = True,
    force_change_password_next_sign_in: bool = True,
) -> None:
    try:
        approval = draft_m365_user_creation(
            _store(),
            user_principal_name=user_principal_name,
            display_name=display_name,
            mail_nickname=mail_nickname,
            temporary_vault_name=temporary_vault_name,
            client_id=client_id,
            account_enabled=account_enabled,
            force_change_password_next_sign_in=force_change_password_next_sign_in,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
    )


@connectors_app.command("draft-m365-user-disable")
def draft_m365_user_disable_command(
    user_identity: str,
    client_id: str | None = None,
) -> None:
    try:
        approval = draft_m365_user_disable(
            _store(),
            user_identity=user_identity,
            client_id=client_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
    )


@connectors_app.command("draft-m365-group-membership")
def draft_m365_group_membership_command(
    group_id: str,
    user_id: str,
    operation: Annotated[str, typer.Option("--operation", help="Membership operation: add or remove.")],
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    try:
        approval = draft_m365_group_membership(
            _store(),
            group_id=group_id,
            user_id=user_id,
            operation=operation,
            client_id=client_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
    )


@connectors_app.command("draft-m365-license-change")
def draft_m365_license_change_command(
    user_id: str,
    sku_ids: Annotated[list[str], typer.Option("--sku-id", help="License SKU GUID; repeat for multiple SKUs.")],
    operation: Annotated[str, typer.Option("--operation", help="License operation: add or remove.")],
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    try:
        approval = draft_m365_license_change(
            _store(),
            user_id=user_id,
            sku_ids=sku_ids,
            operation=operation,
            client_id=client_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
    )


@connectors_app.command("draft-m365-session-revocation")
def draft_m365_session_revocation_command(
    user_id: str,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    try:
        approval = draft_m365_session_revocation(
            _store(),
            user_id=user_id,
            client_id=client_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
    )


@connectors_app.command("draft-m365-managed-device-retirement")
def draft_m365_managed_device_retirement_command(
    device_id: str,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    try:
        approval = draft_m365_managed_device_retirement(
            _store(),
            device_id=device_id,
            client_id=client_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
    )


@connectors_app.command("draft-m365-mailbox-settings")
def draft_m365_mailbox_settings_command(
    user_identity: str,
    settings: Annotated[
        list[str],
        typer.Option("--setting", help="Mailbox setting key=value; repeat for multiple settings."),
    ],
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    parsed: dict[str, str] = {}
    for assignment in settings:
        key, separator, value = assignment.partition("=")
        if not separator or not key.strip():
            raise typer.BadParameter("settings must use key=value")
        parsed[key.strip()] = value
    try:
        approval = draft_m365_mailbox_settings_update(
            _store(),
            user_identity=user_identity,
            settings=parsed,
            client_id=client_id,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={approval.id} subject_id={approval.subject_id} "
        f"action_type={approval.action_type} status={approval.status}"
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


@connectors_app.command("execute-m365-user")
def execute_m365_user(request_id: int) -> None:
    try:
        approval = execute_m365_approval_request(
            _store(),
            _m365_client(),
            SecretVault(load_settings().vault_path),
            request_id,
        )
    except KeyError as exc:
        raise typer.BadParameter("approval request not found") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"{approval.id} {approval.action_type} subject_id={approval.subject_id} "
        f"execution_status={approval.execution_status} "
        f"execution_message={approval.execution_message}"
    )


@connectors_app.command("execute-m365")
def execute_m365(request_id: int) -> None:
    try:
        approval = execute_m365_approval_request(
            _store(),
            _m365_client(),
            SecretVault(load_settings().vault_path),
            request_id,
        )
    except KeyError as exc:
        raise typer.BadParameter("approval request not found") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"{approval.id} {approval.action_type} subject_id={approval.subject_id} "
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


@connectors_app.command("connectwise-health")
def connectwise_health() -> None:
    result = _connectwise_client().health()
    _audit_connectwise_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("connectwise-write-health")
def connectwise_write_health() -> None:
    result = _connectwise_client().write_health()
    _store().add_audit_event("connectwise.write_health", "connectwise", result.status)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("draft-connectwise")
def draft_connectwise(
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
        draft = draft_connectwise_ticket_action(_store(), ticket_id, action_type, fields)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"approval_request_id={draft.approval_request_id} "
        f"ticket_id={draft.ticket_id} action_type={draft.action_type} status={draft.status}"
    )


@connectors_app.command("execute-connectwise")
def execute_connectwise(request_id: int) -> None:
    try:
        approval = execute_connectwise_approval_request(
            _store(), _connectwise_client(), request_id
        )
    except KeyError as exc:
        raise typer.BadParameter("approval request not found") from exc
    except (PermissionError, RuntimeError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(
        f"{approval.id} {approval.action_type} ticket_id={approval.subject_id} "
        f"execution_status={approval.execution_status} "
        f"execution_message={approval.execution_message}"
    )


@connectors_app.command("connectwise-tickets")
def connectwise_tickets(
    page: int = 1,
    page_size: int | None = None,
    conditions: str | None = None,
) -> None:
    _print_connectwise_response(
        "tickets.list",
        _connectwise_client().list_tickets(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().connectwise_page_size
            ),
            conditions=conditions,
        ),
    )


@connectors_app.command("connectwise-ticket")
def connectwise_ticket(ticket_id: str) -> None:
    _print_connectwise_response("tickets.get", _connectwise_client().get_ticket(ticket_id))


@connectors_app.command("connectwise-companies")
def connectwise_companies(
    page: int = 1,
    page_size: int | None = None,
    conditions: str | None = None,
) -> None:
    _print_connectwise_response(
        "companies.list",
        _connectwise_client().list_companies(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().connectwise_page_size
            ),
            conditions=conditions,
        ),
    )


@connectors_app.command("syncro-health")
def syncro_health() -> None:
    result = _syncro_client().health()
    _audit_syncro_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("syncro-tickets")
def syncro_tickets(
    page: int = 1,
    query: str | None = None,
    customer_id: str | None = None,
    status: str | None = None,
    since_updated_at: str | None = None,
) -> None:
    _print_syncro_response(
        "tickets.list",
        _syncro_client().list_tickets(
            page=page,
            query=query,
            customer_id=customer_id,
            status=status,
            since_updated_at=since_updated_at,
        ),
    )


@connectors_app.command("syncro-ticket")
def syncro_ticket(ticket_id: str) -> None:
    _print_syncro_response("tickets.get", _syncro_client().get_ticket(ticket_id))


@connectors_app.command("syncro-customers")
def syncro_customers(
    page: int = 1,
    query: str | None = None,
    business_name: str | None = None,
) -> None:
    _print_syncro_response(
        "customers.list",
        _syncro_client().list_customers(
            page=page,
            query=query,
            business_name=business_name,
        ),
    )


@connectors_app.command("syncro-customer")
def syncro_customer(customer_id: str) -> None:
    _print_syncro_response("customers.get", _syncro_client().get_customer(customer_id))


@connectors_app.command("servicenow-health")
def servicenow_health() -> None:
    result = _servicenow_client().health()
    _audit_servicenow_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("servicenow-incidents")
def servicenow_incidents(
    page: int = 1,
    page_size: int | None = None,
    query: str | None = None,
) -> None:
    _print_servicenow_response(
        "incidents.list",
        _servicenow_client().list_incidents(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().servicenow_page_size
            ),
            query=query,
        ),
    )


@connectors_app.command("servicenow-incident")
def servicenow_incident(sys_id: str) -> None:
    _print_servicenow_response(
        "incidents.get",
        _servicenow_client().get_incident(sys_id),
    )


@connectors_app.command("servicenow-companies")
def servicenow_companies(
    page: int = 1,
    page_size: int | None = None,
    query: str | None = None,
) -> None:
    _print_servicenow_response(
        "companies.list",
        _servicenow_client().list_companies(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().servicenow_page_size
            ),
            query=query,
        ),
    )


@connectors_app.command("servicenow-company")
def servicenow_company(sys_id: str) -> None:
    _print_servicenow_response(
        "companies.get",
        _servicenow_client().get_company(sys_id),
    )


@connectors_app.command("autotask-health")
def autotask_health() -> None:
    result = _autotask_client().health()
    _audit_autotask_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("autotask-tickets")
def autotask_tickets(page: int = 1, page_size: int | None = None) -> None:
    _print_autotask_response(
        "tickets.list",
        _autotask_client().list_tickets(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().autotask_page_size
            ),
        ),
    )


@connectors_app.command("autotask-ticket")
def autotask_ticket(ticket_id: str) -> None:
    _print_autotask_response(
        "tickets.get",
        _autotask_client().get_ticket(ticket_id),
    )


@connectors_app.command("autotask-companies")
def autotask_companies(page: int = 1, page_size: int | None = None) -> None:
    _print_autotask_response(
        "companies.list",
        _autotask_client().list_companies(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().autotask_page_size
            ),
        ),
    )


@connectors_app.command("autotask-company")
def autotask_company(company_id: str) -> None:
    _print_autotask_response(
        "companies.get",
        _autotask_client().get_company(company_id),
    )


@connectors_app.command("itglue-health")
def itglue_health() -> None:
    result = _itglue_client().health()
    _audit_itglue_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("itglue-organizations")
def itglue_organizations(page: int = 1, page_size: int | None = None) -> None:
    _print_itglue_response(
        "organizations.list",
        _itglue_client().list_organizations(
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().itglue_page_size
            ),
        ),
    )


@connectors_app.command("itglue-documents")
def itglue_documents(
    organization_id: str,
    folder_id: str | None = None,
    page: int = 1,
    page_size: int | None = None,
) -> None:
    _print_itglue_response(
        "documents.list",
        _itglue_client().list_documents(
            organization_id,
            folder_id=folder_id,
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().itglue_page_size
            ),
        ),
    )


@connectors_app.command("itglue-document")
def itglue_document(document_id: str) -> None:
    _print_itglue_response(
        "documents.get",
        _itglue_client().get_document(document_id),
    )


@connectors_app.command("itglue-folders")
def itglue_folders(
    organization_id: str,
    page: int = 1,
    page_size: int | None = None,
) -> None:
    _print_itglue_response(
        "folders.list",
        _itglue_client().list_folders(
            organization_id,
            page=page,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().itglue_page_size
            ),
        ),
    )


@connectors_app.command("confluence-health")
def confluence_health() -> None:
    result = _confluence_client().health()
    _audit_confluence_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("confluence-pages")
def confluence_pages(
    space_id: str | None = None,
    title: str | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
) -> None:
    _print_confluence_response(
        "pages.list",
        _confluence_client().list_pages(
            space_id=space_id,
            title=title,
            cursor=cursor,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().confluence_page_size
            ),
        ),
    )


@connectors_app.command("confluence-page")
def confluence_page(page_id: str) -> None:
    _print_confluence_response("pages.get", _confluence_client().get_page(page_id))


@connectors_app.command("sharepoint-health")
def sharepoint_health() -> None:
    result = _sharepoint_client().health()
    _audit_sharepoint_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("sharepoint-sites")
def sharepoint_sites(cursor: str | None = None, page_size: int | None = None) -> None:
    _print_sharepoint_response(
        "sites.list",
        _sharepoint_client().list_sites(
            cursor=cursor,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().sharepoint_page_size
            ),
        ),
    )


@connectors_app.command("sharepoint-site")
def sharepoint_site(site_id: str) -> None:
    _print_sharepoint_response("sites.get", _sharepoint_client().get_site(site_id))


@connectors_app.command("sharepoint-documents")
def sharepoint_documents(
    site_id: str,
    parent_item_id: str | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
) -> None:
    _print_sharepoint_response(
        "documents.list",
        _sharepoint_client().list_documents(
            site_id,
            parent_item_id=parent_item_id,
            cursor=cursor,
            page_size=(
                page_size
                if page_size is not None
                else load_settings().sharepoint_page_size
            ),
        ),
    )


@connectors_app.command("sharepoint-document")
def sharepoint_document(site_id: str, item_id: str) -> None:
    _print_sharepoint_response(
        "documents.get",
        _sharepoint_client().get_document(site_id, item_id),
    )


@connectors_app.command("m365-health")
def m365_health() -> None:
    result = _m365_client().health()
    _audit_m365_cli_read("health", result.status, result.count)
    typer.echo(f"{result.status} count={result.count} {result.message}")


@connectors_app.command("m365-users")
def m365_users(
    identity: str | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
) -> None:
    _print_m365_response(
        "users.list",
        _m365_client().list_users(
            identity=identity,
            cursor=cursor,
            page_size=page_size if page_size is not None else load_settings().m365_page_size,
        ),
    )


@connectors_app.command("m365-groups")
def m365_groups(
    identity: str | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
) -> None:
    _print_m365_group_response(
        "groups.list",
        _m365_client().list_groups(
            identity=identity,
            cursor=cursor,
            page_size=page_size if page_size is not None else load_settings().m365_page_size,
        ),
    )


@connectors_app.command("m365-licenses")
def m365_licenses(cursor: str | None = None) -> None:
    _print_m365_license_response(
        "licenses.list",
        _m365_client().list_subscribed_skus(cursor=cursor),
    )


@connectors_app.command("m365-mail-folders")
def m365_mail_folders(
    identity: str | None = None,
    cursor: str | None = None,
    page_size: int | None = None,
) -> None:
    _print_m365_mail_folder_response(
        "mail-folders.list",
        _m365_client().list_mail_folders(
            identity=identity,
            cursor=cursor,
            page_size=page_size if page_size is not None else load_settings().m365_page_size,
        ),
    )


@connectors_app.command("m365-managed-devices")
def m365_managed_devices(
    cursor: str | None = None,
    page_size: int | None = None,
) -> None:
    _print_m365_managed_device_response(
        "managed-devices.list",
        _m365_client().list_managed_devices(
            cursor=cursor,
            page_size=page_size if page_size is not None else load_settings().m365_page_size,
        ),
    )


@workflows_app.command("templates")
def list_workflows() -> None:
    for template in list_workflow_templates():
        typer.echo(
            f"{template.id} {template.trigger} approval_required={template.approval_required}"
        )


@workflows_app.command("gallery")
def list_workflow_gallery(client_id: str | None = None) -> None:
    store = Store(load_settings().data_path)
    for entry in store.list_template_gallery_entries(client_id=client_id):
        typer.echo(
            f"{entry.id} source={entry.source_template_id} version={entry.version} "
            f"enabled={entry.enabled} client_id={entry.client_id or '-'} name={entry.name}"
        )


@workflows_app.command("gallery-add")
def add_workflow_gallery(
    source_template_id: str,
    provenance: str,
    display_name: str | None = None,
    instructions: str = "",
    client_id: str | None = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    template = get_workflow_template(source_template_id)
    if template is None:
        raise typer.BadParameter("workflow template not found", param_hint="source_template_id")
    entry = store.create_template_gallery_entry(
        template,
        provenance=provenance,
        name=display_name,
        instructions=instructions,
        client_id=client_id,
    )
    typer.echo(
        f"id={entry.id} source={entry.source_template_id} version={entry.version} "
        f"enabled={entry.enabled} client_id={entry.client_id or '-'}"
    )


@workflows_app.command("gallery-export")
def export_workflow_gallery(entry_id: str, client_id: str | None = None) -> None:
    entry = _store().get_template_gallery_entry(entry_id, client_id)
    if entry is None:
        raise typer.BadParameter("template gallery entry not found", param_hint="entry_id")
    typer.echo(json.dumps(_gallery_export_payload(entry), sort_keys=True, indent=2))


@workflows_app.command("gallery-import")
def import_workflow_gallery(
    artifact_path: Path,
    client_id: str | None = None,
) -> None:
    try:
        if artifact_path.stat().st_size > 1_000_000:
            raise ValueError("template artifact is too large")
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise typer.BadParameter(f"invalid template artifact: {exc}", param_hint="artifact_path") from exc
    if (
        not isinstance(artifact, dict)
        or artifact.get("format") != "wait-local-agent.workflow-template"
        or artifact.get("format_version") != 1
    ):
        raise typer.BadParameter("unsupported template artifact", param_hint="artifact_path")
    source_template_id = artifact.get("source_template_id")
    if not isinstance(source_template_id, str) or get_workflow_template(source_template_id) is None:
        raise typer.BadParameter("workflow template source is unavailable", param_hint="artifact_path")
    name = artifact.get("name")
    description = artifact.get("description")
    provenance = artifact.get("provenance")
    instructions = artifact.get("instructions")
    if not all(isinstance(value, str) for value in (name, description, provenance, instructions)):
        raise typer.BadParameter("template artifact is missing editable fields", param_hint="artifact_path")
    name = cast(str, name)
    description = cast(str, description)
    provenance = cast(str, provenance)
    instructions = cast(str, instructions)
    entry = _store().create_template_gallery_entry(
        get_workflow_template(source_template_id),  # type: ignore[arg-type]
        provenance=provenance,
        client_id=client_id,
        name=name,
        description=description,
        instructions=instructions,
        enabled=False,
    )
    result = _gallery_export_payload(entry) | {"id": entry.id, "client_id": entry.client_id}
    typer.echo(json.dumps(result, sort_keys=True, indent=2))


def _gallery_export_payload(entry) -> dict[str, object]:
    return {
        "format": "wait-local-agent.workflow-template",
        "format_version": 1,
        "source_template_id": entry.source_template_id,
        "name": redact_text(entry.name),
        "description": redact_text(entry.description),
        "provenance": redact_text(entry.provenance),
        "instructions": redact_text(entry.instructions),
        "enabled": entry.enabled,
    }


@workflows_app.command("gallery-update")
def update_workflow_gallery(
    entry_id: str,
    display_name: str | None = None,
    description: str | None = None,
    instructions: str | None = None,
    client_id: str | None = None,
) -> None:
    store = Store(load_settings().data_path)
    try:
        entry = store.update_template_gallery_entry(
            entry_id,
            name=display_name,
            description=description,
            instructions=instructions,
            client_id=client_id,
        )
    except KeyError as exc:
        raise typer.BadParameter("template gallery entry not found", param_hint="entry_id") from exc
    typer.echo(f"id={entry.id} version={entry.version} enabled={entry.enabled} name={entry.name}")


@workflows_app.command("gallery-enable")
def enable_workflow_gallery(entry_id: str, client_id: str | None = None) -> None:
    _set_workflow_gallery_enabled(entry_id, True, client_id)


@workflows_app.command("gallery-disable")
def disable_workflow_gallery(entry_id: str, client_id: str | None = None) -> None:
    _set_workflow_gallery_enabled(entry_id, False, client_id)


def _set_workflow_gallery_enabled(entry_id: str, enabled: bool, client_id: str | None) -> None:
    store = Store(load_settings().data_path)
    try:
        entry = store.update_template_gallery_entry(entry_id, enabled=enabled, client_id=client_id)
    except KeyError as exc:
        raise typer.BadParameter("template gallery entry not found", param_hint="entry_id") from exc
    typer.echo(f"id={entry.id} version={entry.version} enabled={entry.enabled}")


@workflows_app.command("gallery-revisions")
def list_workflow_gallery_revisions(entry_id: str, client_id: str | None = None) -> None:
    store = Store(load_settings().data_path)
    revisions = store.list_template_gallery_revisions(entry_id, client_id)
    if not revisions:
        raise typer.BadParameter("template gallery entry not found", param_hint="entry_id")
    for revision in revisions:
        typer.echo(f"version={revision.version} created_at={revision.created_at}")


@workflows_app.command("gallery-diff")
def diff_workflow_gallery(
    entry_id: str,
    from_version: int,
    to_version: int,
    client_id: str | None = None,
) -> None:
    store = Store(load_settings().data_path)
    entry = store.get_template_gallery_entry(entry_id, client_id)
    if entry is None:
        raise typer.BadParameter("template gallery entry not found", param_hint="entry_id")
    left = store.get_template_gallery_revision(entry_id, from_version, entry.client_id)
    right = store.get_template_gallery_revision(entry_id, to_version, entry.client_id)
    if left is None or right is None:
        raise typer.BadParameter("template gallery revision not found")
    left_definition = _safe_revision_definition(left.definition_json)
    right_definition = _safe_revision_definition(right.definition_json)
    changes = [
        {
            "field": field,
            "before": left_definition.get(field),
            "after": right_definition.get(field),
        }
        for field in sorted(set(left_definition) | set(right_definition))
        if left_definition.get(field) != right_definition.get(field)
    ]
    typer.echo(
        json.dumps(
            {
                "gallery_id": entry_id,
                "from_version": left.version,
                "to_version": right.version,
                "changed": bool(changes),
                "changes": changes,
                "client_id": entry.client_id,
            },
            sort_keys=True,
        )
    )


def _safe_revision_definition(definition_json: str) -> dict[str, object]:
    try:
        value = json.loads(definition_json)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return redact_value(value)


@workflows_app.command("gallery-restore")
def restore_workflow_gallery_revision(
    entry_id: str,
    version: int,
    client_id: str | None = None,
) -> None:
    store = Store(load_settings().data_path)
    try:
        entry = store.restore_template_gallery_revision(entry_id, version, client_id)
    except KeyError as exc:
        raise typer.BadParameter("template gallery revision not found") from exc
    typer.echo(f"id={entry.id} version={entry.version} enabled={entry.enabled} name={entry.name}")


@workflows_app.command("gallery-run")
def run_workflow_gallery(entry_id: str, ticket_id: str) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    entry = store.get_template_gallery_entry(entry_id)
    if entry is None:
        raise typer.BadParameter("template gallery entry not found", param_hint="entry_id")
    if not entry.enabled:
        raise typer.BadParameter("template gallery entry is disabled", param_hint="entry_id")
    source_template = get_workflow_template(entry.source_template_id)
    if source_template is None:
        raise typer.BadParameter("source workflow template is unavailable", param_hint="entry_id")
    run = run_workflow_template(
        store,
        entry.source_template_id,
        ticket_id,
        client_id=entry.client_id,
        actor="cli",
        trigger_source="cli_gallery",
        tool_executor=SmartActionService(store, settings),
        template_override=replace(source_template, name=entry.name, description=entry.description),
        operator_instructions=entry.instructions,
        template_version=entry.version,
    )
    _dispatch_cli_workflow_completion(store, settings, run)
    typer.echo(
        f"run_id={run.id} status={run.status} ticket_id={run.ticket_id} "
        f"template_version={run.template_version}"
    )


@workflows_app.command("run")
def run_workflow(template_id: str, ticket_id: str) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    smart_action_service = SmartActionService(store, settings)
    run = run_workflow_template(
        store,
        template_id,
        ticket_id,
        actor="cli",
        trigger_source="cli",
        tool_executor=smart_action_service,
    )
    _dispatch_cli_workflow_completion(store, settings, run)
    typer.echo(f"run_id={run.id} status={run.status} ticket_id={run.ticket_id}")


@workflows_app.command("compare-runs")
def compare_workflow_runs(
    from_run_id: int,
    to_run_id: int,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
    token: Annotated[str | None, typer.Option("--token", envvar="WAIT_CLI_TOKEN")] = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    scoped_client_id = _cli_execution_scope(settings, token, client_id)
    left = store.get_workflow_run(from_run_id, client_id=scoped_client_id)
    right = store.get_workflow_run(to_run_id, client_id=scoped_client_id)
    if left is None or right is None:
        raise typer.BadParameter("workflow run not found")
    typer.echo(json.dumps(_workflow_run_comparison_payload(left, right), sort_keys=True, indent=2))


def _workflow_run_comparison_payload(left, right) -> dict[str, object]:
    fields = (
        "template_id",
        "ticket_id",
        "status",
        "message",
        "approval_request_id",
        "template_version",
        "client_id",
    )
    left_view = asdict(left)
    right_view = asdict(right)
    left_view["message"] = redact_text(left.message)
    right_view["message"] = redact_text(right.message)
    changes = [
        {"field": field, "before": left_view[field], "after": right_view[field]}
        for field in fields
        if left_view[field] != right_view[field]
    ]
    return {
        "from_run": left_view,
        "to_run": right_view,
        "changed": bool(changes),
        "changes": changes,
    }


def _dispatch_cli_workflow_completion(store: Store, settings, run) -> None:
    if run.status != "completed" or run.id is None or not run.ticket_id.strip():
        return
    agent_service = AgentService(store, settings, SmartActionService(store, settings))
    dispatcher = EventDispatcher(store, agent_service)
    payload: dict[str, object] = {
        "workflow_run_id": str(run.id),
        "workflow_template_id": run.template_id,
        "status": run.status,
    }
    try:
        dispatcher.dispatch(
            event_type="workflow.completed",
            entity_type="ticket",
            entity_id=run.ticket_id,
            payload=payload,
            idempotency_key=f"workflow-completed:{run.id}",
            client_id=run.client_id,
            actor="cli",
        )
        store.add_audit_event(
            "workflow.completion_dispatched",
            str(run.id),
            "workflow.completed event dispatched",
            client_id=run.client_id,
        )
    except Exception as exc:  # noqa: BLE001 - completion must not be undone
        store.add_audit_event(
            "workflow.completion_dispatch_failed",
            str(run.id),
            redact_text(f"workflow.completed dispatch failed: {exc}"),
            client_id=run.client_id,
        )


@agents_app.command("list")
def list_agents() -> None:
    settings = load_settings()
    store = _store()
    service = AgentService(store, settings, SmartActionService(store, settings))
    for definition in service.list_definitions(client_id=settings.client_id):
        window = (
            f" window={definition.execution_window_start}-{definition.execution_window_end}"
            f" timezone={definition.execution_window_timezone}"
            if definition.execution_window_start and definition.execution_window_end
            else " window=always"
        )
        typer.echo(
            f"{definition.id} {definition.name} trigger={definition.trigger} "
            f"enabled={definition.enabled} version={definition.version}{window} "
            f"context={','.join(definition.context_sources) or '-'} "
            f"approval_expiry={definition.approval_expiry_seconds or 'tool-default'}"
        )


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


@smart_actions_app.command("list")
def list_smart_actions() -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    service = SmartActionService(store, settings, collector_service=CollectorService(store))
    for manifest in service.list():
        typer.echo(
            f"{manifest.action_id} kind={manifest.kind} "
            f"approval_required={manifest.requires_approval} "
            f"estimate={manifest.estimated_minutes_saved}"
        )


@smart_actions_app.command("describe")
def describe_smart_action(action_id: str) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    service = SmartActionService(store, settings, collector_service=CollectorService(store))
    try:
        manifest = service.describe(action_id)
    except KeyError as exc:
        raise typer.BadParameter("smart action not found") from exc
    typer.echo(json.dumps(asdict(manifest), sort_keys=True, indent=2))


@smart_actions_app.command("invoke")
def invoke_smart_action(
    action_id: str,
    payload: Annotated[
        str | None,
        typer.Option("--payload", help="JSON object or path to a JSON object."),
    ] = None,
    confirm: Annotated[bool, typer.Option("--confirm")] = False,
    token: Annotated[str | None, typer.Option("--token", envvar="WAIT_CLI_TOKEN")] = None,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    service = SmartActionService(
        store,
        settings,
        collector_service=CollectorService(store),
        connectwise_client=_connectwise_client(),
    )
    context = _cli_access(settings, token, Role.TECHNICIAN)
    if context.role < Role.ADMIN and not context.client_id:
        raise typer.BadParameter("authenticated principal has no tenant")
    scoped_client_id = client_id if context.role >= Role.ADMIN else context.client_id
    try:
        result = service.invoke(
            action_id,
            _load_smart_action_payload(payload),
            context.approver_id or "cli",
            confirm=confirm,
            client_id=scoped_client_id,
        )
    except (KeyError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(asdict(result), sort_keys=True, indent=2))


@smart_actions_app.command("runs")
def list_smart_action_runs(
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    for run in store.list_smart_action_runs(client_id=client_id):
        typer.echo(
            f"{run.id} {run.action_id} {run.status} actor={run.actor} "
            f"approval_id={run.approval_id}"
        )


def _cli_execution_scope(settings, token: str | None, client_id: str | None) -> str | None:
    context = _cli_access(settings, token, Role.VIEWER)
    scoped_client_id = client_id if context.role >= Role.ADMIN else context.client_id
    if context.role < Role.ADMIN and not scoped_client_id:
        raise typer.BadParameter("authenticated principal has no tenant")
    return scoped_client_id


@executions_app.command("list")
def list_executions(
    run_kind: Annotated[str | None, typer.Option("--kind")] = None,
    status: Annotated[str | None, typer.Option("--status")] = None,
    started_from: Annotated[str | None, typer.Option("--from")] = None,
    started_to: Annotated[str | None, typer.Option("--to")] = None,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
    token: Annotated[str | None, typer.Option("--token", envvar="WAIT_CLI_TOKEN")] = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    scoped_client_id = _cli_execution_scope(settings, token, client_id)
    for run in store.list_execution_runs(
        client_id=scoped_client_id,
        run_kind=run_kind,
        status=status,
        started_from=started_from,
        started_to=started_to,
    ):
        typer.echo(
            f"{run.id} {run.run_kind} {run.status} actor={run.actor} "
            f"source_run_id={run.source_run_id} trigger={run.trigger_source}"
        )


@executions_app.command("show")
def show_execution(
    execution_id: int,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
    token: Annotated[str | None, typer.Option("--token", envvar="WAIT_CLI_TOKEN")] = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    scoped_client_id = _cli_execution_scope(settings, token, client_id)
    run = store.get_execution_run(execution_id, client_id=scoped_client_id)
    if run is None or run.id is None:
        raise typer.BadParameter("execution not found")
    payload = {
        **asdict(run),
        "steps": [
            _execution_cli_step_view(step) for step in store.list_execution_steps(run.id)
        ],
        "artifacts": [
            {
                "id": artifact.id,
                "step_ordinal": artifact.step_ordinal,
                "name": artifact.name,
                "media_type": artifact.media_type,
                "byte_size": artifact.byte_size,
                "sha256": artifact.sha256,
            }
            for artifact in store.list_execution_artifacts(run.id)
        ],
    }
    payload.pop("metadata_json", None)
    payload["metadata"] = _execution_cli_metadata_view(run)
    typer.echo(json.dumps(payload, sort_keys=True, indent=2))


@analytics_app.command("summary")
def analytics_summary_command(
    started_from: Annotated[str | None, typer.Option("--from")] = None,
    started_to: Annotated[str | None, typer.Option("--to")] = None,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
    token: Annotated[str | None, typer.Option("--token", envvar="WAIT_CLI_TOKEN")] = None,
) -> None:
    settings = load_settings()
    store = Store(settings.data_path)
    scoped_client_id = _cli_execution_scope(settings, token, client_id)
    service = SmartActionService(store, settings, collector_service=CollectorService(store))
    estimates = {
        manifest.action_id: manifest.estimated_minutes_saved for manifest in service.list()
    }
    summary = build_analytics_summary(
        store,
        estimates,
        started_from=started_from,
        started_to=started_to,
        client_id=scoped_client_id,
    )
    typer.echo(json.dumps(summary, sort_keys=True, indent=2))


def _execution_cli_step_view(step) -> dict[str, object]:
    try:
        step_input = json.loads(step.input_json)
    except json.JSONDecodeError:
        step_input = None
    try:
        step_output = json.loads(step.output_json)
    except json.JSONDecodeError:
        step_output = None
    return {
        "id": step.id,
        "ordinal": step.ordinal,
        "kind": step.kind,
        "name": step.name,
        "status": step.status,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "input_digest": step.input_digest,
        "output_digest": step.output_digest,
        "input": redact_value(step_input),
        "output": redact_value(step_output),
        "error_detail": redact_text(step.error_detail),
    }


def _execution_cli_metadata_view(run) -> dict[str, object]:
    try:
        metadata = json.loads(run.metadata_json)
    except json.JSONDecodeError:
        metadata = {}
    return cast(dict[str, object], redact_value(metadata)) if isinstance(metadata, dict) else {}


@collectors_app.command("list")
def list_collectors() -> None:
    modules = _collector_service().list_modules()
    if not modules:
        typer.echo("no collector modules registered")
        return
    for manifest in modules:
        typer.echo(
            f"{manifest.id} version={manifest.version} "
            f"capabilities={','.join(manifest.capabilities) or '-'}"
        )


@collectors_app.command("validate")
def validate_collector(
    module_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="JSON config file.")] = None,
) -> None:
    try:
        result = _collector_service().validate(module_id, _load_json_config(config))
    except KeyError as exc:
        raise typer.BadParameter("collector module not found") from exc
    typer.echo(json.dumps(asdict(result), sort_keys=True, indent=2))
    if not result.passed:
        raise typer.Exit(code=1)


@collectors_app.command("preview")
def preview_collector(
    module_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="JSON config file.")] = None,
) -> None:
    try:
        preview = _collector_service().preview(module_id, _load_json_config(config))
    except KeyError as exc:
        raise typer.BadParameter("collector module not found") from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    typer.echo(json.dumps(asdict(preview), sort_keys=True, indent=2))


@collectors_app.command("run")
def run_collector(
    module_id: str,
    config: Annotated[Path | None, typer.Option("--config", help="JSON config file.")] = None,
    confirm: Annotated[
        bool,
        typer.Option("--confirm", help="Confirm this previewed collector run."),
    ] = False,
    client_id: Annotated[str | None, typer.Option("--client-id")] = None,
) -> None:
    try:
        run = _collector_service().run(
            module_id,
            _load_json_config(config),
            confirm=confirm,
            client_id=client_id,
        )
    except KeyError as exc:
        raise typer.BadParameter("collector module not found") from exc
    except (PermissionError, ValueError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    result_status = collector_run_result_status(run) or "unknown"
    collection_scope = collector_run_collection_scope(run) or "unknown"
    typer.echo(
        f"run_id={run.id} status={run.status} result_status={result_status} "
        f"collection_scope={collection_scope} module={run.module_id}"
    )


@collectors_app.command("export")
def export_collector_report(
    run_id: int,
    report_type: Annotated[
        str,
        typer.Option(help="collector_bundle, appliance_hardening, or restore_evidence."),
    ] = ReportType.COLLECTOR_BUNDLE.value,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    export_format: Annotated[str, typer.Option("--format", help="json or markdown.")] = "json",
) -> None:
    _export_collector_report(run_id, report_type, output, export_format)


@collector_bundle_app.command("export")
def export_collector_bundle(
    run_id: int,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    export_format: Annotated[str, typer.Option("--format", help="json or markdown.")] = "json",
) -> None:
    _export_collector_report(run_id, ReportType.COLLECTOR_BUNDLE.value, output, export_format)


@reports_app.command("list")
def list_reports(
    report_type: Annotated[str, typer.Option(help="Filter by report type value.")] = "",
    client_id: Annotated[str, typer.Option(help="Filter by client id.")] = "",
    project_id: Annotated[str, typer.Option(help="Filter by project id.")] = "",
) -> None:
    service = ReportService(_store())
    try:
        type_filter = ReportType(report_type) if report_type else None
    except ValueError as exc:
        typer.echo(f"unknown report type: {report_type}")
        raise typer.Exit(code=1) from exc
    stored = service.list_reports(
        report_type=type_filter, client_id=client_id, project_id=project_id
    )
    for report in stored:
        typer.echo(
            f"{report.id} type={report.report_type.value} title={report.title} "
            f"created_at={report.created_at}"
        )
    typer.echo(f"count={len(stored)}")


@reports_app.command("show")
def show_report(report_id: str) -> None:
    service = ReportService(_store())
    report = service.get_report(report_id)
    if report is None:
        typer.echo(f"report {report_id} not found")
        raise typer.Exit(code=1)
    typer.echo(render_report_json(report))


@reports_app.command("export")
def export_report(
    report_id: str,
    export_format: Annotated[str, typer.Option(help="json or markdown.")] = "json",
    output: Annotated[Path | None, typer.Option(help="Write to this file path.")] = None,
) -> None:
    service = ReportService(_store())
    try:
        rendered = service.export_report(report_id, ReportFormat(export_format))
    except ValueError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1) from exc
    except KeyError as exc:
        typer.echo(f"report {report_id} not found")
        raise typer.Exit(code=1) from exc
    if output is None:
        typer.echo(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"exported={output}")


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


@hardening_app.command("run")
def run_hardening() -> None:
    settings = load_settings()
    store = _store()
    store.add_audit_event("hardening.run_requested", "hardening", "operator requested hardening checks")
    context = HardeningContext.from_settings(
        settings,
        store=store,
        backup_paths=tuple(
            path
            for path in settings.data_path.parent.glob("*")
            if path.is_file() and path != settings.data_path
        ),
        audit_event_count=len(store.list_audit_events()),
    )
    run = run_hardening_checks(context, store=store)
    if run.id is None:
        raise typer.BadParameter("hardening run was not persisted")
    sections, metadata = build_appliance_hardening_report(store, run.id)
    report = ReportService(store).create_report(
        ReportType.APPLIANCE_HARDENING,
        f"Appliance Hardening Evidence {run.id}",
        sections,
        metadata=metadata,
    )
    store.add_audit_event("hardening.run_completed", str(run.id), run.status)
    typer.echo(json.dumps({"run": asdict(run), "report": asdict(report)}, sort_keys=True, indent=2))


@hardening_app.command("list")
def list_hardening_runs() -> None:
    runs = _store().list_hardening_runs()
    for run in runs:
        typer.echo(
            f"{run.id} status={run.status} results={run.result_count}/{run.expected_check_count} "
            f"started_at={run.started_at}"
        )
    typer.echo(f"count={len(runs)}")


@backup_app.command("restore-exercise")
def restore_exercise(
    backup_id: str,
    encrypted: Annotated[
        bool,
        typer.Option("--encrypted", help="The backup artifact is Fernet encrypted."),
    ] = False,
) -> None:
    settings = load_settings()
    store = _store()
    store.add_audit_event(
        "backup.restore_exercise_requested",
        backup_id,
        "operator requested restore exercise",
    )
    try:
        result = run_restore_exercise(
            backup_id,
            store=store,
            settings=settings,
            encrypted=encrypted,
        )
    except OSError as exc:
        raise typer.BadParameter("restore exercise could not be started") from exc
    sections, metadata = build_restore_evidence_report(store)
    report = ReportService(store).create_report(
        ReportType.RESTORE_EVIDENCE,
        "Restore Evidence",
        sections,
        metadata=metadata,
    )
    typer.echo(json.dumps({"exercise": asdict(result), "report": asdict(report)}, sort_keys=True, indent=2))


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


def _doctor_founder_lp_status() -> str:
    pack = _founder_pack_or_none()
    if pack is None:
        try:
            settings = load_settings()
            store = _store()
            payload = open_founder_status(settings, resolve_open_config(settings, store))
        except FounderNotConfiguredError:
            return "not_configured"
    else:
        try:
            payload = json_object(invoke_founder(pack, "lp_status"), operation="lp_status")
        except FounderPackContractError:
            return "contract_error"
    status = payload.get("status")
    if isinstance(status, str):
        return status
    return json.dumps(payload, sort_keys=True)


def _founder_pack_or_none():
    try:
        return require_founder_pack()
    except FounderPackUnavailableError:
        return None


def _open_cli_config():
    settings = load_settings()
    store = _store()
    try:
        config = resolve_open_config(settings, store)
    except FounderNotConfiguredError as exc:
        typer.echo("launch passport not configured")
        raise typer.Exit(code=1) from exc
    return settings, store, config


def _invoke_founder_cli(operation: str, *args: object) -> object:
    try:
        pack = require_founder_pack()
        return invoke_founder(pack, operation, *args)
    except FounderPackUnavailableError:
        typer.echo(FOUNDER_INSTALL_HINT)
        raise typer.Exit(code=1) from None
    except FounderPackContractError as exc:
        raise typer.BadParameter(str(exc)) from exc


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


def _print_connectwise_response(read_type: str, response: ConnectWiseReadResponse) -> None:
    _audit_connectwise_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(f"{response.result.status} count={response.result.count} {response.result.message}")
    for item in response.items:
        typer.echo(item)


def _print_syncro_response(read_type: str, response: SyncroReadResponse) -> None:
    _audit_syncro_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(f"{response.result.status} count={response.result.count} {response.result.message}")
    for item in response.items:
        typer.echo(item)


def _audit_halopsa_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("halopsa.read", read_type, f"{status} count={count}")


def _audit_hudu_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("hudu.read", read_type, f"{status} count={count}")


def _audit_connectwise_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("connectwise.read", read_type, f"{status} count={count}")


def _audit_syncro_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("syncro.read", read_type, f"{status} count={count}")


def _print_servicenow_response(read_type: str, response: ServiceNowReadResponse) -> None:
    _audit_servicenow_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {"result": asdict(response.result), "items": response.items},
            sort_keys=True,
            indent=2,
        )
    )


def _audit_servicenow_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("servicenow.read", read_type, f"{status} count={count}")


def _print_autotask_response(read_type: str, response: AutotaskReadResponse) -> None:
    _audit_autotask_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {"result": asdict(response.result), "items": response.items},
            sort_keys=True,
            indent=2,
        )
    )


def _audit_autotask_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("autotask.read", read_type, f"{status} count={count}")


def _print_itglue_response(read_type: str, response: ItGlueReadResponse) -> None:
    _audit_itglue_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
            },
            sort_keys=True,
            indent=2,
        )
    )


def _audit_itglue_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("itglue.read", read_type, f"{status} count={count}")


def _print_confluence_response(read_type: str, response: ConfluenceReadResponse) -> None:
    _audit_confluence_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _audit_confluence_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("confluence.read", read_type, f"{status} count={count}")


def _print_sharepoint_response(read_type: str, response: SharePointReadResponse) -> None:
    _audit_sharepoint_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _audit_sharepoint_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("sharepoint.read", read_type, f"{status} count={count}")


def _print_m365_response(read_type: str, response: M365GraphReadResponse) -> None:
    _audit_m365_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _audit_m365_cli_read(read_type: str, status: str, count: int) -> None:
    _store().add_audit_event("m365.read", read_type, f"{status} count={count}")


def _print_m365_group_response(read_type: str, response: M365GraphGroupReadResponse) -> None:
    _audit_m365_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _print_m365_license_response(read_type: str, response: M365GraphLicenseReadResponse) -> None:
    _audit_m365_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _print_m365_mail_folder_response(
    read_type: str,
    response: M365GraphMailFolderReadResponse,
) -> None:
    _audit_m365_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _print_m365_managed_device_response(
    read_type: str,
    response: M365GraphManagedDeviceReadResponse,
) -> None:
    _audit_m365_cli_read(read_type, response.result.status, response.result.count)
    typer.echo(
        json.dumps(
            {
                "result": asdict(response.result),
                "items": [asdict(item) for item in response.items],
                "next_cursor": response.next_cursor,
            },
            sort_keys=True,
            indent=2,
        )
    )


def _approval_cli_view(approval) -> dict[str, object]:
    try:
        payload = json.loads(approval.payload_json)
    except json.JSONDecodeError:
        payload = {}
    try:
        output = json.loads(approval.execution_result_json)
    except json.JSONDecodeError:
        output = {}
    return {
        **asdict(approval),
        "payload_json": json.dumps(redact_value(payload), sort_keys=True, separators=(",", ":")),
        "execution_result_json": json.dumps(redact_value(output), sort_keys=True, separators=(",", ":")),
        "comment": redact_text(approval.comment),
        "payload": redact_value(payload) if isinstance(payload, dict) else {},
        "output": redact_value(output) if isinstance(output, dict) else {},
    }


def _cli_access(settings, token: str | None, minimum: Role):
    authorization = f"Bearer {token}" if token else None
    try:
        context = resolve_auth_context(settings, authorization)
    except HTTPException as exc:
        raise typer.BadParameter(str(exc.detail)) from exc
    if context.role < minimum:
        raise typer.BadParameter("insufficient role")
    return context


def _load_json_config(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise typer.BadParameter("collector config must be a JSON object")
    return payload


def _load_smart_action_payload(value: str | None) -> dict[str, object]:
    if value is None:
        return {}
    candidate = Path(value)
    raw = candidate.read_text(encoding="utf-8") if candidate.is_file() else value
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise typer.BadParameter("payload must be a JSON object or JSON file") from exc
    if not isinstance(payload, dict):
        raise typer.BadParameter("payload must be a JSON object")
    return payload


def _export_collector_report(
    run_id: int,
    report_type: str,
    output: Path | None,
    export_format: str,
) -> None:
    service = _collector_service()
    try:
        created = service.export_report(run_id, ReportType(report_type))
        rendered = ReportService(_store()).export_report(created.id, ReportFormat(export_format))
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except KeyError as exc:
        raise typer.BadParameter("collector run not found") from exc
    if output is None:
        typer.echo(rendered)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    typer.echo(f"exported={output} report_id={created.id} run_id={run_id}")


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


def _sync_pack_cli_on_startup() -> None:
    try:
        sync_pack_cli()
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("Pack CLI discovery failed during startup: %s", exc)


_sync_pack_cli_on_startup()
