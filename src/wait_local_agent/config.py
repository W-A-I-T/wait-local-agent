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


def _optional_nonnegative_float_env(name: str) -> float | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    try:
        parsed = float(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


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
    allow_insecure_provider_transport: bool = False
    allow_power_platform_deployment: bool = False
    api_token: str = ""
    admin_token: str = ""
    tech_token: str = ""
    viewer_token: str = ""
    end_user_token: str = ""
    end_user_client_id: str = ""
    end_user_user_id: str = ""
    end_user_support_enabled: bool = False
    end_user_brand_name: str = "WAIT Support"
    end_user_brand_tagline: str = "Private help desk"
    end_user_brand_logo_data_uri: str = ""
    end_user_brand_accent_color: str = "#1f6f55"
    end_user_brand_surface_color: str = "#f3f5f2"
    communication_email_host: str = ""
    communication_email_port: int = 587
    communication_email_username: str = ""
    communication_email_password: str = ""
    communication_email_from: str = ""
    communication_email_tls: bool = True
    communication_teams_webhook_url: str = ""
    communication_slack_webhook_url: str = ""
    communication_sms_webhook_url: str = ""
    communication_sms_auth_token: str = ""
    ninjaone_base_url: str = ""
    ninjaone_access_token: str = ""
    ninjaone_organization_map_json: str = ""
    ninjaone_page_size: int = 50
    datto_rmm_base_url: str = ""
    datto_rmm_access_token: str = ""
    datto_rmm_site_map_json: str = ""
    datto_rmm_page_size: int = 50
    ncentral_base_url: str = ""
    ncentral_access_token: str = ""
    ncentral_org_unit_map_json: str = ""
    ncentral_page_size: int = 50
    n_sight_base_url: str = ""
    n_sight_api_key: str = ""
    n_sight_client_map_json: str = ""
    timezest_base_url: str = "https://api.timezest.com"
    timezest_api_key: str = ""
    timezest_client_map_json: str = ""
    scalepad_base_url: str = "https://api.scalepad.com"
    scalepad_api_key: str = ""
    scalepad_client_map_json: str = ""
    scalepad_risk_tenant_map_json: str = ""
    scalepad_compliance_client_map_json: str = ""
    scalepad_lifecycle_client_map_json: str = ""
    kaseya_rmm_base_url: str = ""
    kaseya_rmm_token_id: str = ""
    kaseya_rmm_token_secret: str = ""
    kaseya_rmm_organization_map_json: str = ""
    kaseya_rmm_page_size: int = 50
    screenconnect_base_url: str = ""
    screenconnect_extension_id: str = ""
    screenconnect_auth_secret: str = ""
    screenconnect_origin: str = ""
    screenconnect_client_sessions_map_json: str = ""
    screenconnect_script_catalog_json: str = ""
    client_id: str = ""
    demo_mode: bool = False
    secrets_backend: str = "env"
    vault_path: Path = Path(".wait-local-agent/vault")
    power_platform_workspace: Path = Path(".wait-local-agent/power-platform")
    power_platform_command_timeout_seconds: float = 600.0
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
    mcp_allowed_origins: tuple[str, ...] = ()
    mcp_client_allowed_hosts: tuple[str, ...] = ()
    connector_instance_allowed_hosts: tuple[str, ...] = ()
    halopsa_base_url: str = ""
    halopsa_client_id: str = ""
    halopsa_client_secret: str = ""
    halopsa_tenant: str = ""
    halopsa_token_url: str = ""
    halopsa_client_map_json: str = ""
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
    notion_base_url: str = "https://api.notion.com"
    notion_api_token: str = ""
    notion_version: str = "2026-03-11"
    notion_page_size: int = 25
    notion_client_page_map_json: str = ""
    notion_client_data_source_map_json: str = ""
    sharepoint_base_url: str = ""
    sharepoint_access_token: str = ""
    sharepoint_page_size: int = 25
    work_iq_mcp_endpoint: str = ""
    work_iq_mcp_access_token: str = ""
    work_iq_mcp_timeout_seconds: float = 20.0
    m365_graph_base_url: str = ""
    m365_access_token: str = ""
    m365_page_size: int = 25
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
    remote_model_provider: str = ""
    remote_model_base_url: str = ""
    remote_model_name: str = ""
    remote_model_api_key: str = ""
    remote_model_timeout_seconds: float = 20.0
    model_input_cost_usd_per_million_tokens: float | None = None
    model_output_cost_usd_per_million_tokens: float | None = None
    offline_mode: bool = False
    log_dir: Path | None = None
    log_max_bytes: int = 1_048_576
    log_backup_count: int = 5
    support_upload_endpoint: str = ""


def load_settings() -> Settings:
    backend = _secrets_backend()
    vault_path = Path(os.getenv("WAIT_VAULT_PATH", ".wait-local-agent/vault"))
    return Settings(
        data_path=Path(os.getenv("WAIT_DATA_PATH", ".wait-local-agent/state.db")),
        allowed_doc_root=Path(os.getenv("WAIT_ALLOWED_DOC_ROOT", "examples/sample_docs")),
        allow_write_actions=_bool_env("WAIT_ALLOW_WRITE_ACTIONS"),
        allow_http_probing=_bool_env("WAIT_ALLOW_HTTP_PROBING"),
        allow_insecure_provider_transport=_bool_env("WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT"),
        allow_cloud_fallback=_bool_env("WAIT_ALLOW_CLOUD_FALLBACK"),
        allow_llm_inference=_bool_env("WAIT_ALLOW_LLM_INFERENCE"),
        allow_power_platform_deployment=_bool_env("WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT"),
        local_model_provider=os.getenv("WAIT_LOCAL_MODEL_PROVIDER", "deterministic"),
        local_model_base_url=os.getenv("WAIT_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1"),
        local_model_name=os.getenv("WAIT_LOCAL_MODEL_NAME", "llama3.1"),
        local_model_timeout_seconds=_float_env("WAIT_LOCAL_MODEL_TIMEOUT_SECONDS", 20.0),
        vector_backend=os.getenv("WAIT_VECTOR_BACKEND", "sqlite"),
        remote_model_provider=os.getenv("WAIT_REMOTE_MODEL_PROVIDER", "").strip().lower(),
        remote_model_base_url=os.getenv("WAIT_REMOTE_MODEL_BASE_URL", "").strip(),
        remote_model_name=os.getenv("WAIT_REMOTE_MODEL_NAME", "").strip(),
        remote_model_api_key=_secret_value(
            "WAIT_REMOTE_MODEL_API_KEY",
            os.getenv("WAIT_REMOTE_MODEL_API_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        remote_model_timeout_seconds=_float_env("WAIT_REMOTE_MODEL_TIMEOUT_SECONDS", 20.0),
        model_input_cost_usd_per_million_tokens=_optional_nonnegative_float_env(
            "WAIT_MODEL_INPUT_COST_USD_PER_MILLION_TOKENS"
        ),
        model_output_cost_usd_per_million_tokens=_optional_nonnegative_float_env(
            "WAIT_MODEL_OUTPUT_COST_USD_PER_MILLION_TOKENS"
        ),
        offline_mode=_bool_env("WAIT_OFFLINE_MODE"),
        log_dir=(
            Path(log_dir_value)
            if (log_dir_value := os.getenv("WAIT_LOG_DIR", "").strip())
            else None
        ),
        log_max_bytes=_int_env("WAIT_LOG_MAX_BYTES", 1_048_576),
        log_backup_count=_int_env("WAIT_LOG_BACKUP_COUNT", 5),
        support_upload_endpoint=_secret_value(
            "WAIT_SUPPORT_UPLOAD_ENDPOINT",
            os.getenv("WAIT_SUPPORT_UPLOAD_ENDPOINT", "").strip(),
            backend=backend,
            vault_path=vault_path,
        ),
        api_token=os.getenv("WAIT_API_TOKEN", ""),
        admin_token=os.getenv("WAIT_ADMIN_TOKEN", ""),
        tech_token=os.getenv("WAIT_TECH_TOKEN", ""),
        viewer_token=os.getenv("WAIT_VIEWER_TOKEN", ""),
        end_user_token=os.getenv("WAIT_END_USER_TOKEN", ""),
        end_user_client_id=os.getenv("WAIT_END_USER_CLIENT_ID", "").strip(),
        end_user_user_id=os.getenv("WAIT_END_USER_USER_ID", "").strip(),
        end_user_support_enabled=_bool_env("WAIT_END_USER_SUPPORT_ENABLED"),
        end_user_brand_name=os.getenv("WAIT_END_USER_BRAND_NAME", "WAIT Support").strip()
        or "WAIT Support",
        end_user_brand_tagline=os.getenv(
            "WAIT_END_USER_BRAND_TAGLINE", "Private help desk"
        ).strip()
        or "Private help desk",
        end_user_brand_logo_data_uri=os.getenv("WAIT_END_USER_BRAND_LOGO_DATA_URI", "").strip(),
        end_user_brand_accent_color=os.getenv(
            "WAIT_END_USER_BRAND_ACCENT_COLOR", "#1f6f55"
        ).strip(),
        end_user_brand_surface_color=os.getenv(
            "WAIT_END_USER_BRAND_SURFACE_COLOR", "#f3f5f2"
        ).strip(),
        communication_email_host=_secret_value(
            "WAIT_COMMUNICATION_EMAIL_HOST",
            os.getenv("WAIT_COMMUNICATION_EMAIL_HOST", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        communication_email_port=_int_env("WAIT_COMMUNICATION_EMAIL_PORT", 587),
        communication_email_username=_secret_value(
            "WAIT_COMMUNICATION_EMAIL_USERNAME",
            os.getenv("WAIT_COMMUNICATION_EMAIL_USERNAME", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        communication_email_password=_secret_value(
            "WAIT_COMMUNICATION_EMAIL_PASSWORD",
            os.getenv("WAIT_COMMUNICATION_EMAIL_PASSWORD", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        communication_email_from=os.getenv("WAIT_COMMUNICATION_EMAIL_FROM", "").strip(),
        communication_email_tls=_bool_env("WAIT_COMMUNICATION_EMAIL_TLS", True),
        communication_teams_webhook_url=_secret_value(
            "WAIT_COMMUNICATION_TEAMS_WEBHOOK_URL",
            os.getenv("WAIT_COMMUNICATION_TEAMS_WEBHOOK_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        communication_slack_webhook_url=_secret_value(
            "WAIT_COMMUNICATION_SLACK_WEBHOOK_URL",
            os.getenv("WAIT_COMMUNICATION_SLACK_WEBHOOK_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        communication_sms_webhook_url=_secret_value(
            "WAIT_COMMUNICATION_SMS_WEBHOOK_URL",
            os.getenv("WAIT_COMMUNICATION_SMS_WEBHOOK_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        communication_sms_auth_token=_secret_value(
            "WAIT_COMMUNICATION_SMS_AUTH_TOKEN",
            os.getenv("WAIT_COMMUNICATION_SMS_AUTH_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        ninjaone_base_url=_secret_value(
            "WAIT_NINJAONE_BASE_URL",
            os.getenv("WAIT_NINJAONE_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        ninjaone_access_token=_secret_value(
            "WAIT_NINJAONE_ACCESS_TOKEN",
            os.getenv("WAIT_NINJAONE_ACCESS_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        ninjaone_organization_map_json=os.getenv(
            "WAIT_NINJAONE_ORGANIZATION_MAP_JSON", ""
        ),
        ninjaone_page_size=_int_env("WAIT_NINJAONE_PAGE_SIZE", 50),
        datto_rmm_base_url=_secret_value(
            "WAIT_DATTORMM_BASE_URL",
            os.getenv("WAIT_DATTORMM_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        datto_rmm_access_token=_secret_value(
            "WAIT_DATTORMM_ACCESS_TOKEN",
            os.getenv("WAIT_DATTORMM_ACCESS_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        datto_rmm_site_map_json=os.getenv("WAIT_DATTORMM_SITE_MAP_JSON", ""),
        datto_rmm_page_size=_int_env("WAIT_DATTORMM_PAGE_SIZE", 50),
        ncentral_base_url=_secret_value(
            "WAIT_NCENTRAL_BASE_URL",
            os.getenv("WAIT_NCENTRAL_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        ncentral_access_token=_secret_value(
            "WAIT_NCENTRAL_ACCESS_TOKEN",
            os.getenv("WAIT_NCENTRAL_ACCESS_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        ncentral_org_unit_map_json=os.getenv("WAIT_NCENTRAL_ORG_UNIT_MAP_JSON", ""),
        ncentral_page_size=_int_env("WAIT_NCENTRAL_PAGE_SIZE", 50),
        n_sight_base_url=_secret_value(
            "WAIT_NSIGHT_BASE_URL",
            os.getenv("WAIT_NSIGHT_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        n_sight_api_key=_secret_value(
            "WAIT_NSIGHT_API_KEY",
            os.getenv("WAIT_NSIGHT_API_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        n_sight_client_map_json=os.getenv("WAIT_NSIGHT_CLIENT_MAP_JSON", ""),
        timezest_base_url=_secret_value(
            "WAIT_TIMEZEST_BASE_URL",
            os.getenv("WAIT_TIMEZEST_BASE_URL", "https://api.timezest.com"),
            backend=backend,
            vault_path=vault_path,
        ),
        timezest_api_key=_secret_value(
            "WAIT_TIMEZEST_API_KEY",
            os.getenv("WAIT_TIMEZEST_API_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        timezest_client_map_json=os.getenv("WAIT_TIMEZEST_CLIENT_MAP_JSON", ""),
        scalepad_base_url=_secret_value(
            "WAIT_SCALEPAD_BASE_URL",
            os.getenv("WAIT_SCALEPAD_BASE_URL", "https://api.scalepad.com"),
            backend=backend,
            vault_path=vault_path,
        ),
        scalepad_api_key=_secret_value(
            "WAIT_SCALEPAD_API_KEY",
            os.getenv("WAIT_SCALEPAD_API_KEY", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        scalepad_client_map_json=os.getenv("WAIT_SCALEPAD_CLIENT_MAP_JSON", ""),
        scalepad_risk_tenant_map_json=os.getenv("WAIT_SCALEPAD_RISK_TENANT_MAP_JSON", ""),
        scalepad_compliance_client_map_json=os.getenv(
            "WAIT_SCALEPAD_COMPLIANCE_CLIENT_MAP_JSON", ""
        ),
        scalepad_lifecycle_client_map_json=os.getenv(
            "WAIT_SCALEPAD_LIFECYCLE_CLIENT_MAP_JSON", ""
        ),
        kaseya_rmm_base_url=_secret_value(
            "WAIT_KASEYA_RMM_BASE_URL",
            os.getenv("WAIT_KASEYA_RMM_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        kaseya_rmm_token_id=_secret_value(
            "WAIT_KASEYA_RMM_TOKEN_ID",
            os.getenv("WAIT_KASEYA_RMM_TOKEN_ID", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        kaseya_rmm_token_secret=_secret_value(
            "WAIT_KASEYA_RMM_TOKEN_SECRET",
            os.getenv("WAIT_KASEYA_RMM_TOKEN_SECRET", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        kaseya_rmm_organization_map_json=os.getenv(
            "WAIT_KASEYA_RMM_ORGANIZATION_MAP_JSON", ""
        ),
        kaseya_rmm_page_size=_int_env("WAIT_KASEYA_RMM_PAGE_SIZE", 50),
        screenconnect_base_url=_secret_value(
            "WAIT_SCREENCONNECT_BASE_URL",
            os.getenv("WAIT_SCREENCONNECT_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        screenconnect_extension_id=os.getenv("WAIT_SCREENCONNECT_EXTENSION_ID", ""),
        screenconnect_auth_secret=_secret_value(
            "WAIT_SCREENCONNECT_AUTH_SECRET",
            os.getenv("WAIT_SCREENCONNECT_AUTH_SECRET", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        screenconnect_origin=os.getenv("WAIT_SCREENCONNECT_ORIGIN", ""),
        screenconnect_client_sessions_map_json=os.getenv(
            "WAIT_SCREENCONNECT_CLIENT_SESSIONS_MAP_JSON", ""
        ),
        screenconnect_script_catalog_json=os.getenv(
            "WAIT_SCREENCONNECT_SCRIPT_CATALOG_JSON", ""
        ),
        client_id=os.getenv("WAIT_CLIENT_ID", "").strip(),
        demo_mode=_bool_env("WAIT_DEMO_MODE", False),
        secrets_backend=backend,
        vault_path=vault_path,
        power_platform_workspace=Path(
            os.getenv("WAIT_POWER_PLATFORM_WORKSPACE", ".wait-local-agent/power-platform")
        ),
        power_platform_command_timeout_seconds=_float_env(
            "WAIT_POWER_PLATFORM_COMMAND_TIMEOUT_SECONDS", 600.0
        ),
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
        mcp_allowed_origins=tuple(
            value.strip().rstrip("/")
            for value in os.getenv("WAIT_MCP_ALLOWED_ORIGINS", "").split(",")
            if value.strip()
        ),
        mcp_client_allowed_hosts=tuple(
            value.strip().casefold()
            for value in os.getenv("WAIT_MCP_CLIENT_ALLOWED_HOSTS", "").split(",")
            if value.strip()
        ),
        connector_instance_allowed_hosts=tuple(
            value.strip().casefold()
            for value in os.getenv("WAIT_CONNECTOR_INSTANCE_ALLOWED_HOSTS", "").split(",")
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
        halopsa_client_map_json=os.getenv("WAIT_HALOPSA_CLIENT_MAP_JSON", ""),
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
        notion_base_url=os.getenv("WAIT_NOTION_BASE_URL", "https://api.notion.com"),
        notion_api_token=_secret_value(
            "WAIT_NOTION_API_TOKEN",
            os.getenv("WAIT_NOTION_API_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        notion_version=os.getenv("WAIT_NOTION_VERSION", "2026-03-11").strip(),
        notion_page_size=_int_env("WAIT_NOTION_PAGE_SIZE", 25),
        notion_client_page_map_json=os.getenv("WAIT_NOTION_CLIENT_PAGE_MAP_JSON", ""),
        notion_client_data_source_map_json=os.getenv(
            "WAIT_NOTION_CLIENT_DATA_SOURCE_MAP_JSON", ""
        ),
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
        work_iq_mcp_endpoint=_secret_value(
            "WAIT_WORK_IQ_MCP_ENDPOINT",
            os.getenv("WAIT_WORK_IQ_MCP_ENDPOINT", "").strip(),
            backend=backend,
            vault_path=vault_path,
        ),
        work_iq_mcp_access_token=_secret_value(
            "WAIT_WORK_IQ_MCP_ACCESS_TOKEN",
            os.getenv("WAIT_WORK_IQ_MCP_ACCESS_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        work_iq_mcp_timeout_seconds=_float_env("WAIT_WORK_IQ_MCP_TIMEOUT_SECONDS", 20.0),
        m365_graph_base_url=_secret_value(
            "WAIT_M365_GRAPH_BASE_URL",
            os.getenv("WAIT_M365_GRAPH_BASE_URL", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        m365_access_token=_secret_value(
            "WAIT_M365_ACCESS_TOKEN",
            os.getenv("WAIT_M365_ACCESS_TOKEN", ""),
            backend=backend,
            vault_path=vault_path,
        ),
        m365_page_size=_int_env("WAIT_M365_PAGE_SIZE", 25),
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
