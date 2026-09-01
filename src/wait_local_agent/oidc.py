from __future__ import annotations

import hashlib
import logging
import re
import secrets
import sqlite3
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from authlib.integrations.starlette_client import OAuth

from wait_local_agent.client_scope import AllClients
from wait_local_agent.config import Settings
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault, SecretVaultError

LOGGER = logging.getLogger(__name__)

OIDC_CLIENT_SECRET_KEY = "WAIT_OIDC_CLIENT_SECRET"  # nosec B105: secret name constant, not a secret value
SESSION_SIGNING_KEY = "WAIT_SESSION_SIGNING_KEY"
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,320}$")


@dataclass(frozen=True)
class OidcConfig:
    tenant_id: str
    client_id: str
    public_base_url: str
    client_secret: str
    enabled: bool
    auto_provision_enabled: bool = False
    auto_provision_tenant_id: str = ""
    auto_provision_client_id: str = ""
    auto_provision_role: str = "viewer"

    @property
    def issuer(self) -> str:
        return f"https://login.microsoftonline.com/{self.tenant_id}/v2.0"

    @property
    def metadata_url(self) -> str:
        return f"{self.issuer}/.well-known/openid-configuration"

    @property
    def redirect_uri(self) -> str:
        return f"{self.public_base_url.rstrip('/')}/auth/oidc/callback"

    @property
    def client_secret_configured(self) -> bool:
        return bool(self.client_secret)

    @property
    def complete(self) -> bool:
        return bool(
            _valid_tenant_id(self.tenant_id)
            and self.client_id
            and self.client_secret
            and _valid_public_base_url(self.public_base_url)
        )


def load_oidc_config(settings: Settings, store: Store, vault: SecretVault) -> OidcConfig:
    """Load DB-backed OIDC settings, using environment values only as first-boot defaults."""

    tenant_id = _stored_or_default(store, "oidc.tenant_id", settings.oidc_tenant_id)
    client_id = _stored_or_default(store, "oidc.client_id", settings.oidc_client_id)
    public_base_url = _stored_or_default(store, "oidc.public_base_url", settings.oidc_public_base_url)
    enabled = _stored_bool(store, "oidc.enabled", False)
    auto_provision_enabled = _stored_bool(store, "oidc.auto_provision_enabled", False)
    auto_provision_tenant_id = _stored_or_default(store, "oidc.auto_provision_tenant_id", tenant_id)
    auto_provision_client_id = _stored_or_default(
        store,
        "oidc.auto_provision_client_id",
        settings.oidc_auto_provision_client_id or settings.client_id,
    )
    try:
        client_secret = vault.get(OIDC_CLIENT_SECRET_KEY) or ""
    except (SecretVaultError, ValueError):
        client_secret = ""  # nosec B105: empty fallback when the vault secret is unavailable
    return OidcConfig(
        tenant_id=tenant_id.strip(),
        client_id=client_id.strip(),
        public_base_url=public_base_url.strip().rstrip("/"),
        client_secret=client_secret,
        enabled=enabled and _valid_tenant_id(tenant_id) and bool(client_id) and bool(client_secret)
        and _valid_public_base_url(public_base_url),
        auto_provision_enabled=auto_provision_enabled,
        auto_provision_tenant_id=auto_provision_tenant_id.strip(),
        auto_provision_client_id=auto_provision_client_id.strip(),
    )


def build_oauth_client(config: OidcConfig):
    """Build a fresh Authlib client so runtime config changes apply per request."""

    oauth = OAuth()
    oauth.register(
        name="entra",
        client_id=config.client_id,
        client_secret=config.client_secret,
        server_metadata_url=config.metadata_url,
        client_kwargs={"scope": "openid profile email"},
        code_challenge_method="S256",
    )
    return oauth.create_client("entra")


def resolve_identity(store: Store, claims: dict[str, object], config: OidcConfig) -> str | None:
    """Resolve an authenticated Entra claim set to an existing principal or a bounded new viewer."""

    oid = _claim_string(claims, "oid")
    email = _claim_string(claims, "preferred_username") or _claim_string(claims, "email")
    if oid:
        principal_id = store.find_principal_by_identity(config.issuer, oid, "oid")
        if principal_id is not None:
            store.mark_identity_login(config.issuer, oid, "oid")
            return principal_id
        if email:
            principal_id = store.upgrade_email_identity(config.issuer, email, oid)
            if principal_id is not None:
                return principal_id

    if (
        config.auto_provision_enabled
        and oid
        and _claim_string(claims, "tid") == config.auto_provision_tenant_id
        and config.auto_provision_role == "viewer"
        and config.auto_provision_client_id
        and store.get_client(AllClients(), config.auto_provision_client_id) is not None
    ):
        principal_id = _auto_provision_principal_id(config, oid)
        display_name = _claim_string(claims, "name") or email or "Microsoft account"
        try:
            store.create_principal(principal_id, kind="staff", display_name=display_name)
            store.add_principal_client_role(principal_id, config.auto_provision_client_id, "viewer")
            store.add_principal_identity(principal_id, config.issuer, oid, "oid")
        except sqlite3.IntegrityError:
            # A concurrent first login may have created the deterministic link.
            existing = store.find_principal_by_identity(config.issuer, oid, "oid")
            if existing is None:
                return None
            principal_id = existing
        store.mark_identity_login(config.issuer, oid, "oid")
        return principal_id
    return None


def validate_next_path(raw: str | None) -> str:
    """Accept only a same-origin application path for the post-login redirect."""

    if raw is None or raw == "":
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        raise ValueError("next must be a local path")
    candidate = raw
    for _ in range(4):
        decoded = unquote(candidate)
        if decoded == candidate:
            break
        candidate = decoded
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or "\\" in candidate
        or "://" in candidate
        or any(ord(char) < 0x20 for char in candidate)
    ):
        raise ValueError("next must be a local path")
    return raw


def get_or_create_session_signing_key(settings: Settings, vault: SecretVault) -> str:
    """Keep Authlib's short-lived transaction cookie stable across restarts."""

    try:
        active_vault = vault
        if not active_vault.is_initialized():
            active_vault = SecretVault.initialize(settings.vault_path, demo_mode=settings.demo_mode)
        key = active_vault.get(SESSION_SIGNING_KEY)
        if not key:
            key = secrets.token_urlsafe(48)
            active_vault.set(SESSION_SIGNING_KEY, key)
        return key
    except SecretVaultError:
        if settings.secrets_backend == "fernet":
            raise
        LOGGER.warning("OIDC transaction cookie signing key is ephemeral because the vault is unavailable")
        return secrets.token_urlsafe(48)


def _stored_or_default(store: Store, key: str, default: str) -> str:
    stored = store.get_app_config(key)
    return default if stored is None else str(stored)


def _stored_bool(store: Store, key: str, default: bool) -> bool:
    value = store.get_app_config(key)
    return default if value is None else str(value).strip().lower() in {"1", "true", "yes", "on"}


def _valid_tenant_id(value: str) -> bool:
    return bool(_TENANT_ID_RE.fullmatch(value.strip()))


def _valid_public_base_url(value: str) -> bool:
    parsed = urlsplit(value.strip())
    return bool(
        parsed.scheme in {"http", "https"}
        and parsed.netloc
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
    )


def _claim_string(claims: dict[str, object], key: str) -> str:
    value = claims.get(key)
    return value.strip() if isinstance(value, str) else ""


def _auto_provision_principal_id(config: OidcConfig, oid: str) -> str:
    digest = hashlib.sha256(f"{config.issuer}\x00{oid}".encode()).hexdigest()[:32]
    return f"oidc-{digest}"
