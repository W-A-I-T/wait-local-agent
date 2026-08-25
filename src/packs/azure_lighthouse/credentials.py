"""Vault-backed credential resolution for Azure Lighthouse."""

from __future__ import annotations

import json
from importlib import import_module

from wait_local_agent.config import Settings
from wait_local_agent.vault import SecretVault, SecretVaultError

from .models import AzureLighthouseCredentialError, TokenCredential
from .validation import normalize_uuid


def credential_from_vault(
    settings: Settings,
    credential_ref: str,
    managing_tenant_id: str,
    *,
    vault: SecretVault | None = None,
) -> TokenCredential:
    """Resolve a managing-tenant service-principal credential without persisting tokens."""

    reference = credential_ref.strip()
    if not reference:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential reference is required."
        )
    if len(reference) > 256 or any(ord(character) < 32 for character in reference):
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential reference is invalid."
        )
    tenant_id = normalize_uuid(managing_tenant_id, "managing tenant ID")
    active_vault = vault or SecretVault(settings.vault_path)
    try:
        raw_secret = active_vault.get(reference)
    except (SecretVaultError, ValueError) as exc:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential reference could not be read."
        ) from exc
    if not raw_secret:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential reference was not found in the local vault."
        )
    try:
        payload = json.loads(raw_secret)
    except json.JSONDecodeError as exc:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential value is not valid JSON."
        ) from exc
    if not isinstance(payload, dict):
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential value must be a JSON object."
        )
    supported_keys = {"tenant_id", "client_id", "client_secret"}
    if set(payload) - supported_keys:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential value contains unsupported fields."
        )
    values: dict[str, str] = {}
    for key in supported_keys:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AzureLighthouseCredentialError(
                "Azure Lighthouse credential value is incomplete."
            )
        values[key] = value.strip()
    if normalize_uuid(values["tenant_id"], "credential tenant ID") != tenant_id:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential tenant does not match the managing tenant."
        )
    normalize_uuid(values["client_id"], "credential client ID")
    try:
        credential_type = getattr(import_module("azure.identity"), "ClientSecretCredential")
        return credential_type(
            tenant_id=values["tenant_id"],
            client_id=values["client_id"],
            client_secret=values["client_secret"],
        )
    except (ImportError, AttributeError) as exc:
        raise AzureLighthouseCredentialError(
            "Azure Identity SDK is unavailable."
        ) from exc
    except Exception as exc:
        raise AzureLighthouseCredentialError(
            "Azure Lighthouse credential could not be initialized."
        ) from exc
