from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from wait_local_agent.api.app import create_app
from wait_local_agent.config import load_settings
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store

app = typer.Typer(help="WAIT Local Agent command line interface.")
tickets_app = typer.Typer(help="Ticket intelligence commands.")
audit_app = typer.Typer(help="Audit log commands.")
app.add_typer(tickets_app, name="tickets")
app.add_typer(audit_app, name="audit")


def _store() -> Store:
    return Store(load_settings().data_path)


@app.command()
def doctor() -> None:
    settings = load_settings()
    typer.echo("WAIT Local Agent")
    typer.echo(f"data_path={settings.data_path}")
    typer.echo(f"provider={settings.local_model_provider}")
    typer.echo(f"model={settings.local_model_name}")
    typer.echo(f"write_actions_enabled={settings.allow_write_actions}")
    typer.echo(f"http_probing_enabled={settings.allow_http_probing}")
    typer.echo(f"cloud_fallback_enabled={settings.allow_cloud_fallback}")


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


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8788) -> None:
    uvicorn.run(create_app(), host=host, port=port)

