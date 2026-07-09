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
        document_parser="basic",
        allow_ocr=False,
        embedding_provider="none",
        embedding_model="BAAI/bge-small-en-v1.5",
        admin_token="",
        tech_token="",
        viewer_token="",
        qdrant_path=tmp_path / "qdrant",
        qdrant_url="",
        qdrant_collection="wait_knowledge_chunks",
        connector_timeout_seconds=20.0,
        halopsa_base_url="",
        halopsa_client_id="",
        halopsa_client_secret="",
        halopsa_tenant="",
        halopsa_token_url="",
        halopsa_ticket_write_endpoint="Ticket",
        halopsa_action_write_endpoint="Actions",
        hudu_base_url="",
        hudu_api_key="",
        hudu_page_size=25,
        demo_mode=True,
        api_token="",
    )
