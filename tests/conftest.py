from __future__ import annotations

from pathlib import Path

import pytest

from wait_local_agent.config import Settings


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_path=tmp_path / "state.db",
        allowed_doc_root=Path("examples/sample_docs"),
        allow_write_actions=False,
        allow_http_probing=False,
        allow_cloud_fallback=False,
        allow_llm_inference=False,
        local_model_provider="deterministic",
        local_model_base_url="http://127.0.0.1:11434/v1",
        local_model_name="llama3.1",
        local_model_timeout_seconds=20.0,
        vector_backend="sqlite",
        halopsa_base_url="",
        halopsa_client_id="",
        halopsa_client_secret="",
        halopsa_tenant="",
    )
