from __future__ import annotations

from types import SimpleNamespace

from wait_local_agent.vector_search import (
    QdrantKnowledgeSearch,
    _chunk_from_payload,
    validate_vector_settings,
)


def test_chunk_from_payload_parses_string_identifiers_and_client_id() -> None:
    chunk = _chunk_from_payload(
        {
            "chunk_id": "12",
            "document_id": "34",
            "title": "Runbook",
            "path": "docs/runbook.md",
            "chunk_index": "5",
            "text": "body",
            "excerpt": "excerpt",
            "client_id": "acme",
        }
    )

    assert chunk.id == 12
    assert chunk.document_id == 34
    assert chunk.chunk_index == 5
    assert chunk.client_id == "acme"


def test_qdrant_search_filters_chunks_by_client_id(settings) -> None:
    search = object.__new__(QdrantKnowledgeSearch)
    search.settings = settings.__class__(**{**settings.__dict__, "qdrant_collection": "wait_knowledge_chunks"})

    class FakeEmbedding:
        def embed(self, values):
            return iter([[0.1, 0.2] for _ in values])

    class FakeClient:
        def search(self, **kwargs):
            assert kwargs["limit"] == 12
            return [
                SimpleNamespace(
                    payload={
                        "chunk_id": "1",
                        "document_id": "10",
                        "title": "Acme",
                        "path": "acme.md",
                        "chunk_index": "0",
                        "text": "acme body",
                        "excerpt": "acme excerpt",
                        "client_id": "acme",
                    }
                ),
                SimpleNamespace(
                    payload={
                        "chunk_id": "2",
                        "document_id": "20",
                        "title": "Beta",
                        "path": "beta.md",
                        "chunk_index": "0",
                        "text": "beta body",
                        "excerpt": "beta excerpt",
                        "client_id": "beta",
                    }
                ),
            ]

    search._embedding = FakeEmbedding()
    search._client = FakeClient()

    results = search.search("mailbox permissions", limit=3, client_id="acme")

    assert [chunk.title for chunk in results] == ["Acme"]


def test_validate_vector_settings_requires_http_for_remote_qdrant(settings) -> None:
    remote_settings = settings.__class__(
        **{
            **settings.__dict__,
            "vector_backend": "qdrant",
            "qdrant_url": "https://vector.example.test",
            "allow_http_probing": False,
        }
    )

    try:
        validate_vector_settings(remote_settings)
    except ValueError as exc:
        assert "WAIT_QDRANT_URL requires WAIT_ALLOW_HTTP_PROBING=true" in str(exc)
    else:
        raise AssertionError("expected validate_vector_settings to reject remote qdrant without probing")
