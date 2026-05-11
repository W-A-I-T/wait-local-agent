from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    document_parser: str = "basic"
    allow_ocr: bool = False
    embedding_provider: str = "none"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    qdrant_path: Path = Path(".wait-local-agent/qdrant")
    qdrant_url: str = ""
    qdrant_collection: str = "wait_knowledge_chunks"
    connector_timeout_seconds: float = 20.0
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


def load_settings() -> Settings:
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
        document_parser=os.getenv("WAIT_DOCUMENT_PARSER", "basic"),
        allow_ocr=_bool_env("WAIT_ALLOW_OCR"),
        embedding_provider=os.getenv("WAIT_EMBEDDING_PROVIDER", "none"),
        embedding_model=os.getenv("WAIT_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        qdrant_path=Path(os.getenv("WAIT_QDRANT_PATH", ".wait-local-agent/qdrant")),
        qdrant_url=os.getenv("WAIT_QDRANT_URL", ""),
        qdrant_collection=os.getenv("WAIT_QDRANT_COLLECTION", "wait_knowledge_chunks"),
        connector_timeout_seconds=_float_env("WAIT_CONNECTOR_TIMEOUT_SECONDS", 20.0),
        halopsa_base_url=os.getenv("WAIT_HALOPSA_BASE_URL", ""),
        halopsa_client_id=os.getenv("WAIT_HALOPSA_CLIENT_ID", ""),
        halopsa_client_secret=os.getenv("WAIT_HALOPSA_CLIENT_SECRET", ""),
        halopsa_tenant=os.getenv("WAIT_HALOPSA_TENANT", ""),
        halopsa_token_url=os.getenv("WAIT_HALOPSA_TOKEN_URL", ""),
        halopsa_ticket_write_endpoint=os.getenv("WAIT_HALOPSA_TICKET_WRITE_ENDPOINT", "Ticket"),
        halopsa_action_write_endpoint=os.getenv("WAIT_HALOPSA_ACTION_WRITE_ENDPOINT", "Actions"),
        hudu_base_url=os.getenv("WAIT_HUDU_BASE_URL", ""),
        hudu_api_key=os.getenv("WAIT_HUDU_API_KEY", ""),
        hudu_page_size=_int_env("WAIT_HUDU_PAGE_SIZE", 25),
    )
