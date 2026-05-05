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
        local_model_provider="ollama",
        local_model_base_url="http://127.0.0.1:11434/v1",
        local_model_name="llama3.1",
        vector_backend="sqlite",
    )

