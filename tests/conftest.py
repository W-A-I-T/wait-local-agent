from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.collectors import CollectorRegistry
from wait_local_agent.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class LiveTestClient(TestClient):
    """TestClient helper that makes the bearer credential explicit per request set."""

    def set_authorization(self, token: str | None) -> None:
        if token is None:
            self.headers.pop("Authorization", None)
        else:
            self.headers["Authorization"] = f"Bearer {token}"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_path=tmp_path / "state.db",
        allowed_doc_root=Path("examples/sample_docs"),
        allow_write_actions=False,
        allow_http_probing=False,
        allow_insecure_provider_transport=False,
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
        scheduler_enabled=False,
        trusted_hosts=("127.0.0.1", "localhost", "api", "testserver"),
        rate_limit_enabled=False,
        rate_limit_general="100/minute",
        rate_limit_connector="10/minute",
        update_channel_url="",
        update_pubkeys=(),
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
        license_key="",
        license_secret="",
        pack_signing_secret="",
        demo_mode=True,
        api_token="",
    )


@pytest.fixture()
def live_settings(settings: Settings) -> Settings:
    """Non-demo settings for API tests that must exercise real auth and scopes."""

    return settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "test-admin-token",
            "tech_token": "test-tech-token",
            "viewer_token": "test-viewer-token",
            # The live fixture uses an HTTP TestClient; production keeps the
            # secure-cookie default, while this local transport must retain
            # the browser session for CSRF tests.
            "session_cookie_secure": False,
        }
    )


@pytest.fixture()
def live_client(live_settings: Settings) -> Iterator[LiveTestClient]:
    """Live-auth TestClient with an explicit helper for selecting a bearer role."""

    client = LiveTestClient(create_app(live_settings))
    yield client
    client.close()


@pytest.fixture()
def isolated_default_registry() -> Iterator[CollectorRegistry]:
    """Restore the process-wide collector registry after registry-mutating tests."""
    from wait_local_agent.collectors import default_registry

    original_modules = default_registry.list()
    yield default_registry
    default_registry.clear()
    for module in original_modules:
        default_registry.register(module)
