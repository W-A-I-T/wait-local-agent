"""CLI commands for Azure Lighthouse delegated-resource administration."""

from __future__ import annotations

import json

import typer

from wait_local_agent.config import load_settings

from .client import AzureLighthouseClient
from .credentials import credential_from_vault
from .models import AzureLighthouseError
from .onboarding import build_onboarding_bundle, validate_onboarding_bundle

app = typer.Typer(
    help="Read-only Azure Lighthouse discovery, inventory, and onboarding artifacts."
)


@app.command("status")
def status() -> None:
    """Show the local policy state for Azure Lighthouse live reads."""

    settings = load_settings()
    _emit(
        {
            "status": "ready" if settings.allow_http_probing else "blocked",
            "read_only": True,
            "customer_onboarding_deployed_by_wait": False,
        }
    )


@app.command("discover")
def discover(
    credential_ref: str = typer.Option(..., "--credential-ref"),
    managing_tenant_id: str = typer.Option(..., "--managing-tenant"),
    customer_tenant_id: str = typer.Option(..., "--customer-tenant"),
    client_id: str = typer.Option(..., "--client"),
) -> None:
    """Discover delegated subscriptions for one explicitly mapped WAIT client."""

    settings = load_settings()
    try:
        credential = credential_from_vault(settings, credential_ref, managing_tenant_id)
        result = AzureLighthouseClient(settings, credential).discover(
            client_id=client_id,
            managing_tenant_id=managing_tenant_id,
            expected_customer_tenant_id=customer_tenant_id,
        )
    except AzureLighthouseError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _emit(result.to_dict())


@app.command("inventory")
def inventory(
    credential_ref: str = typer.Option(..., "--credential-ref"),
    managing_tenant_id: str = typer.Option(..., "--managing-tenant"),
    customer_tenant_id: str = typer.Option(..., "--customer-tenant"),
    subscription_id: str = typer.Option(..., "--subscription"),
    client_id: str = typer.Option(..., "--client"),
    resource_group: str | None = typer.Option(None, "--resource-group"),
    limit: int = typer.Option(200, "--limit", min=1, max=500),
) -> None:
    """Verify an exact delegated scope and list its Azure resources."""

    settings = load_settings()
    try:
        credential = credential_from_vault(settings, credential_ref, managing_tenant_id)
        result = AzureLighthouseClient(settings, credential).inventory(
            client_id=client_id,
            managing_tenant_id=managing_tenant_id,
            expected_customer_tenant_id=customer_tenant_id,
            subscription_id=subscription_id,
            resource_group=resource_group,
            limit=limit,
        )
    except AzureLighthouseError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _emit(result.to_dict())


@app.command("onboarding-plan")
def onboarding_plan(
    offer_name: str = typer.Option(..., "--offer-name"),
    offer_description: str = typer.Option(..., "--description"),
    managing_tenant_id: str = typer.Option(..., "--managing-tenant"),
    principal_id: str = typer.Option(..., "--principal"),
    principal_display_name: str = typer.Option(..., "--principal-name"),
    deployment_scope: str = typer.Option("subscription", "--scope"),
) -> None:
    """Generate a Reader-only customer-deployable onboarding bundle; never deploy it."""

    try:
        if deployment_scope not in {"subscription", "resource_group"}:
            raise AzureLighthouseError(
                "Azure Lighthouse deployment scope must be subscription or resource_group."
            )
        bundle = build_onboarding_bundle(
            offer_name=offer_name,
            offer_description=offer_description,
            managing_tenant_id=managing_tenant_id,
            principal_id=principal_id,
            principal_display_name=principal_display_name,
            deployment_scope=deployment_scope,  # type: ignore[arg-type]
        )
        validate_onboarding_bundle(bundle)
    except AzureLighthouseError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from exc
    _emit(bundle.to_dict())


def _emit(payload: object) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True, default=str))
