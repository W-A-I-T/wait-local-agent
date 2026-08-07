from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from wait_local_agent.vault import SecretVault, SecretVaultError


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _secrets_backend() -> str:
    backend = os.getenv("WAIT_SECRETS_BACKEND", "env").strip().lower()
    return backend if backend in {"env", "fernet"} else "env"


def _secret_value(name: str, env_value: str, *, backend: str, vault_path: Path) -> str:
    if backend != "fernet":
        return env_value
    try:
        vaulted = SecretVault(vault_path).get(name)
    except SecretVaultError:
        return env_value
    return vaulted or env_value


@dataclass(frozen=True)
class Settings:
    data_path: Path
    allowed_doc_root: Path
    allow_write_actions: bool
    allow_http_probing: bool
    allow_cloud_fallback: bool
    allow_llm_inference: bool
    local_model_provider: str
    local_model_base_url: str
    local_model_name: str
    local_model_timeout_seconds: float
    vector_backend: str
    api_token: str = ""
    admin_token: str = ""
    tech_token: str = ""
    viewer_token: str = ""
    client_id: str = ""
    demo_mode: bool = True
    secrets_backend: str = "env"
    vault_path: Path = Path(".wait-local-agent/vault")
    document_parser: str = "basic"
    allow_ocr: bool = False
    embedding_provider: str = "none"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    qdrant_path: Path = Path(".wait-local-agent/qdrant")
    qdrant_url: str = ""
    qdrant_collection: str = "wait_knowledge_chunks"
    connector_timeout_seconds: float = 20.0
    scheduler_enabled: bool = True
    rate_limit_enabled: bool = True
    rate_limit_general: str = "100/minute"
    rate_limit_connector: str = "10/minute"
    update_channel_url: str = ""
    update_pubkeys: tuple[str, ...] = ()
    halopsa_base_url: str = ""
    halopsa_client_id: str = ""
    halopsa_client_secret: str = ""
    halopsa_tenant: str = ""
    halopsa_token_url: str = ""
    halopsa_ticket_write_endpoint: str = "Ticket"
    halopsa_action_write_endpoint: str = "Actions"
    hudu_base_url: str = ""
    hudu_api_key: str = ""
    hudu_page_size: int = 25
    itglue_base_url: str = ""
    itglue_api_key: str = ""
    itglue_page_size: int = 25
    confluence_base_url: str = ""
    confluence_email: str = ""
    confluence_api_token: str = ""
    confluence_page_size: int = 25
    sharepoint_base_url: str = ""
    sharepoint_access_token: str = ""
    sharepoint_page_size: int = 25
    connectwise_base_url: str = ""
    connectwise_company: str = ""
    connectwise_public_key: str = ""
    connectwise_private_key: str = ""
    connectwise_client_id: str = ""
    connectwise_api_version: str = "2022.1"
    connectwise_page_size: int = 25
    syncro_base_url: str = ""
    syncro_api_token: str = ""
    servicenow_base_url: str = ""
    servicenow_username: str = ""
    servicenow_password: str = ""
    servicenow_api_version: str = ""
    servicenow_page_size: int = 25
    autotask_base_url: str = ""
    autotask_username: str = ""
    autotask_secret: str = ""
    autotask_integration_code: str = ""
    autotask_page_size: int = 50
    license_key: str = ""
    license_secret: str = ""
    pack_signing_secret: str = ""


def load_settings() -> Settings:
    backend = _secrets_backend()
    vault_path = Path(os.getenv("WAIT_VAULT_PATH", ".wait-local-agent/vault"))
    return Settings(
        data_path=Path(os.getenv("WAIT_DATA_PATH", ".wait-local-agent/state.db")),
        allowed_doc_root=Path(os.getenv("WAIT_ALLOWED_DOC_ROOT", "examples/sample_docs")),
        allow_write_actions=_bool_env("WAIT_ALLOW_WRITE_ACTIONS"),
        allow_http_probing=_bool_env("WAIT_ALLOW_HTTP_PROBING"),
        allow_cloud_fallback=_bool_env("WAIT_ALLOW_CLOUD_FALLBACK"),
        allow_llm_inference=_bool_env("WAIT_ALLOW_LLM_INFERENCE"),
        local_model_provider=os.getenv("WAIT_LOCAL_MODEL_PROVIDER", "deterministic"),
        local_model_base_url=os.getenv("WAIT_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1"),
        local_model_name=os.getenv("WAIT_LOCAL_MODEL_NAME", "llama3.1"),
        local_model_timeout_seconds=_float_env("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", 20.0),
        vector_backend=os.getenv("WAIT_VECTOR_BACKEND", "sqlite"),
        api_token=os.getenv("WAIT_API_TOKEN", ""),
        admin_token=os.getenv("WAIT_ADMIN_TOKEN", ""),
        tech_token=os.getenv("WAIT_TECH_TOKEN", ""),
        viewer_token=os.getenv("WAIT_VIEWER_TOKEN", ""),
        client_id=os.getenv("WAIT_CLIENT_ID", "").strip(),
        demo_mode=_bool_env("WAIT_DEMO_MODE", True),
        secrets_backend=backend,
        vault_path=vault_path,
        document_parser=os.getenv("WAIT_DOCUMENT_PARSER", "basic"),
        allow_ocr=_bool_env("WAIT_ALLOW_OCR"),
        embedding_provider=os.getenv("WAIT_EMBEDDING_PROVIDER", "none"),
        embedding_model=os.getenv("WAIT_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        qdrant_path=Path(os.getenv("WAIT_QDRANT_PATH", ".wait-local-agent/qdrant")),
        qdrant_url=os.getenv("WAIT_QDRANT_URL", ""),
        qdrant_collection=os.getenv("WAIT_QDRANT_COLLECTION", "wait_knowledge_chunks"),
        connector_timeout_seconds=_float_env("WAIT_CONNECTOR_TIMEOUT_SECONDS", 20.0),
        scheduler_enabled=_bool_env("WAIT_SCHEDULER_ENABLED", True),
        rate_limit_enabled=_bool_env("WAIT_RATE_LIMIT_ENABLED", True),
        rate_limit_general=os.getenv("WAIT_RATE_LIMIT_GENERAL", "100/minute"),
        rate_limit_connector=os.getenv("WAIT_RATE_LIMIT_CONNECTOR", "10/minute"),
        update_channel_url=os.getenv("WAIT_UPDATE_CHANNEL_URL", "").strip(),
        update_pubkeys=tuple(
            value.strip()
            for value in os.getenv("WAIT_UPDATE_PUBKEYS", "").split(",")
            if value.strip()
        ),
        halopsa_base_url=_secret_value(
            "WAIT_HALOPSA_BASE_URL",
            os.getenv("WAIT_HALOPSA_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        halopsa_client_id=_secret_value(
            "WAIT_HALOPSA_CLIENT_ID",
            os.getenv("WAIT_HALOPSA_CLIENT_ID", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        halopsa_client_secret=_secret_value(
            "WAIT_HALOPSA_CLIENT_SECRET",
            os.getenv("WAIT_HALOPSA_CLIENT_SECRET", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        halopsa_tenant=_secret_value(
            "WAIT_HALOPSA_TENANT",
            os.getenv("WAIT_HALOPSA_TENANT", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        halopsa_token_url=_secret_value(
            "WAIT_HALOPSA_TOKEN_URL",
            os.getenv("WAIT_HALOPSA_TOKEN_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        halopsa_ticket_write_endpoint=os.getenv("WAIT_HALOPSA_TICKET_WRITE_ENDPOINT", "Ticket"),
        halopsa_action_write_endpoint=os.getenv("WAIT_HALOPSA_ACTION_WRITE_ENDPOINT", "Actions"),
        hudu_base_url=_secret_value(
            "WAIT_HUDU_BASE_URL",
            os.getenv("WAIT_HUDU_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        hudu_api_key=_secret_value(
            "WAIT_HUDU_API_KEY",
            os.getenv("WAIT_HUDU_API_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        hudu_page_size=_int_env("WAIT_HUDU_PAGE_SIZE", 25),
        itglue_base_url=_secret_value(
            "WAIT_ITGLUE_BASE_URL",
            os.getenv("WAIT_ITGLUE_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        itglue_api_key=_secret_value(
            "WAIT_ITGLUE_API_KEY",
            os.getenv("WAIT_ITGLUE_API_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        itglue_page_size=_int_env("WAIT_ITGLUE_PAGE_SIZE", 25),
        confluence_base_url=_secret_value(
            "WAIT_CONFLUENCE_BASE_URL",
            os.getenv("WAIT_CONFLUENCE_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        confluence_email=_secret_value(
            "WAIT_CONFLUENCE_EMAIL",
            os.getenv("WAIT_CONFLUENCE_EMAIL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        confluence_api_token=_secret_value(
            "WAIT_CONFLUENCE_API_TOKEN",
            os.getenv("WAIT_CONFLUENCE_API_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        confluence_page_size=_int_env("WAIT_CONFLUENCE_PAGE_SIZE", 25),
        sharepoint_base_url=_secret_value(
            "WAIT_SHAREPOINT_BASE_URL",
            os.getenv("WAIT_SHAREPOINT_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        sharepoint_access_token=_secret_value(
            "WAIT_SHAREPOINT_ACCESS_TOKEN",
            os.getenv("WAIT_SHAREPOINT_ACCESS_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        sharepoint_page_size=_int_env("WAIT_SHAREPOINT_PAGE_SIZE", 25),
        connectwise_base_url=_secret_value(
            "WAIT_CONNECTWISE_BASE_URL",
            os.getenv("WAIT_CONNECTWISE_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        connectwise_company=_secret_value(
            "WAIT_CONNECTWISE_COMPANY",
            os.getenv("WAIT_CONNECTWISE_COMPANY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        connectwise_public_key=_secret_value(
            "WAIT_CONNECTWISE_PUBLIC_KEY",
            os.getenv("WAIT_CONNECTWISE_PUBLIC_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        connectwise_private_key=_secret_value(
            "WAIT_CONNECTWISE_PRIVATE_KEY",
            os.getenv("WAIT_CONNECTWISE_PRIVATE_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        connectwise_client_id=_secret_value(
            "WAIT_CONNECTWISE_CLIENT_ID",
            os.getenv("WAIT_CONNECTWISE_CLIENT_ID", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        connectwise_api_version=os.getenv("WAIT_CONNECTWISE_API_VERSION", "2022.1"),
        connectwise_page_size=_int_env("WAIT_CONNECTWISE_PAGE_SIZE", 25),
        syncro_base_url=_secret_value(
            "WAIT_SYNCRO_BASE_URL",
            os.getenv("WAIT_SYNCRO_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        syncro_api_token=_secret_value(
            "WAIT_SYNCRO_API_TOKEN",
            os.getenv("WAIT_SYNCRO_API_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        servicenow_base_url=_secret_value(
            "WAIT_SERVICENOW_BASE_URL",
            os.getenv("WAIT_SERVICENOW_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        servicenow_username=_secret_value(
            "WAIT_SERVICENOW_USERNAME",
            os.getenv("WAIT_SERVICENOW_USERNAME", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        servicenow_password=_secret_value(
            "WAIT_SERVICENOW_PASSWORD",
            os.getenv("WAIT_SERVICENOW_PASSWORD", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        servicenow_api_version=os.getenv("WAIT_SERVICENOW_API_VERSION", "").strip(),
        servicenow_page_size=_int_env("WAIT_SERVICENOW_PAGE_SIZE", 25),
        autotask_base_url=_secret_value(
            "WAIT_AUTOTASK_BASE_URL",
            os.getenv("WAIT_AUTOTASK_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        autotask_username=_secret_value(
            "WAIT_AUTOTASK_USERNAME",
            os.getenv("WAIT_AUTOTASK_USERNAME", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        autotask_secret=_secret_value(
            "WAIT_AUTOTASK_SECRET",
            os.getenv("WAIT_AUTOTASK_SECRET", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        autotask_integration_code=_secret_value(
            "WAIT_AUTOTASK_INTEGRATION_CODE",
            os.getenv("WAIT_AUTOTASK_INTEGRATION_CODE", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        autotask_page_size=_int_env("WAIT_AUTOTASK_PAGE_SIZE", 50),
        license_key=_secret_value(
            "license_key",
            os.getenv("WAIT_LICENSE_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        license_secret=os.getenv("WAIT_LICENSE_SECRET", ""),
        pack_signing_secret=os.getenv("WAIT_PACK_SIGNING_SECRET", ""),
    )
