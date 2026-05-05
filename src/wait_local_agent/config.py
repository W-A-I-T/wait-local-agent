from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_path: Path
    allowed_doc_root: Path
    allow_write_actions: bool
    allow_http_probing: bool
    allow_cloud_fallback: bool
    local_model_provider: str
    local_model_base_url: str
    local_model_name: str
    vector_backend: str


def load_settings() -> Settings:
    return Settings(
        data_path=Path(os.getenv("WAIT_DATA_PATH", ".wait-local-agent/state.db")),
        allowed_doc_root=Path(os.getenv("WAIT_ALLOWED_DOC_ROOT", "examples/sample_docs")),
        allow_write_actions=_bool_env("WAIT_ALLOW_WRITE_ACTIONS"),
        allow_http_probing=_bool_env("WAIT_ALLOW_HTTP_PROBING"),
        allow_cloud_fallback=_bool_env("WAIT_ALLOW_CLOUD_FALLBACK"),
        local_model_provider=os.getenv("WAIT_LOCAL_MODEL_PROVIDER", "ollama"),
        local_model_base_url=os.getenv("WAIT_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:11434/v1"),
        local_model_name=os.getenv("WAIT_LOCAL_MODEL_NAME", "llama3.1"),
        vector_backend=os.getenv("WAIT_VECTOR_BACKEND", "sqlite"),
    )

