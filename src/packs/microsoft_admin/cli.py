"""CLI commands for the Microsoft administrator pack."""

from __future__ import annotations

import json
from typing import cast

import typer

from packs.azure_lighthouse.cli import app as azure_lighthouse_app
from packs.microsoft_admin.core import (
    MicrosoftAdminError,
    MicrosoftAdminGraphClient,
    build_dashboard,
    diagnose_access,
    remediation_catalog,
)
from packs.microsoft_admin.runbooks import (
    RunbookError,
    build_runbook_plan,
    runbook_catalog,
    runbook_runtime_status,
)
from wait_local_agent.config import load_settings
from wait_local_agent.m365_graph import M365GraphClient

app = typer.Typer(help="Microsoft 365, Entra, Intune, Defender, and endpoint administration.")
app.add_typer(azure_lighthouse_app, name="azure-lighthouse")


@app.command("status")
def status() -> None:
    """Check whether the Microsoft administrator Graph read boundary is ready."""

    settings = load_settings()
    result = MicrosoftAdminGraphClient(settings).health()
    _emit({"status": result.status, "message": result.message, "count": result.count})


@app.command("dashboard")
def dashboard() -> None:
    """Build a read-only Microsoft cloud and endpoint posture snapshot."""

    settings = load_settings()
    _emit(build_dashboard(MicrosoftAdminGraphClient(settings), M365GraphClient(settings)))


@app.command("diagnose-access")
def diagnose_access_command(
    user_identity: str = typer.Option(..., "--user", help="User principal name or immutable user ID."),
    device_name: str | None = typer.Option(None, "--device", help="Optional Intune device name."),
) -> None:
    """Correlate identity, sign-in, licensing, service, and endpoint evidence."""

    settings = load_settings()
    try:
        result = diagnose_access(
            MicrosoftAdminGraphClient(settings),
            M365GraphClient(settings),
            user_identity=user_identity,
            device_name=device_name,
        )
    except MicrosoftAdminError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _emit(result.to_dict())


@app.command("remediations")
def remediations() -> None:
    """List core approval-gated actions this pack may recommend."""

    _emit(remediation_catalog())


@app.command("runbooks")
def runbooks() -> None:
    """List fixed, reviewed PowerShell runbook definitions."""

    _emit(runbook_catalog())


@app.command("runbook-status")
def runbook_status() -> None:
    """Check local PowerShell execution prerequisites without running a script."""

    _emit(runbook_runtime_status(load_settings()).to_dict())


@app.command("plan-runbook")
def plan_runbook(
    runbook_id: str = typer.Argument(..., help="Fixed runbook ID from the catalog."),
    client_id: str = typer.Option(..., "--client", help="Explicit tenant/client ID."),
    parameters_json: str = typer.Option(
        "{}",
        "--parameters",
        help="JSON object containing only the runbook's declared parameters.",
    ),
) -> None:
    """Build a canonical approval payload; this command never executes PowerShell."""

    try:
        raw_parameters = json.loads(parameters_json)
        if not isinstance(raw_parameters, dict):
            raise RunbookError("PowerShell runbook parameters must be a JSON object.")
        result = build_runbook_plan(
            runbook_id,
            cast(dict[str, object], raw_parameters),
            client_id=client_id,
        )
    except (json.JSONDecodeError, RunbookError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _emit(result)


def _emit(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
