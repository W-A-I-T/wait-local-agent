from __future__ import annotations

import hashlib
from typing import Protocol

from wait_local_agent.config import Settings
from wait_local_agent.models import KnowledgeChunk
from wait_local_agent.store import Store, _bounded_search_limit


class KnowledgeSearchBackend(Protocol):
    def upsert_document_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        """Persist searchable chunks in the backend."""

    def search(
        self,
        query: str,
        limit: int = 3,
        client_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        """Return matching chunks."""


class SQLiteKnowledgeSearch:
    def __init__(self, store: Store) -> None:
        self.store = store

    def upsert_document_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        return None

    def search(
        self,
        query: str,
        limit: int = 3,
        client_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        return self.store.search_knowledge_chunks(query, limit, client_id=client_id)


class QdrantKnowledgeSearch:
    def __init__(self, settings: Settings) -> None:
        if settings.qdrant_url and not settings.allow_http_probing:
            raise ValueError(
                "WAIT_VECTOR_BACKEND=qdrant with WAIT_QDRANT_URL requires "
                "WAIT_ALLOW_HTTP_PROBING=true"
            )
        try:
            from fastembed import TextEmbedding
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
        except ImportError as exc:
            raise ValueError(
                "Qdrant search requires optional dependencies; "
                'install with pip install -e ".[qdrant]".'
            ) from exc

        self.settings = settings
        self._embedding = TextEmbedding(model_name=settings.embedding_model)
        if settings.qdrant_url:
            self._client = QdrantClient(
                url=settings.qdrant_url,
                timeout=settings.connector_timeout_seconds,
            )
        else:
            settings.qdrant_path.mkdir(parents=True, exist_ok=True)
            self._client = QdrantClient(path=str(settings.qdrant_path))
        self._models = __import__("qdrant_client.models", fromlist=["PointStruct"])
        self._ensure_collection(VectorParams=VectorParams, Distance=Distance)

    def _ensure_collection(self, *, VectorParams, Distance) -> None:
        sample_vector = next(iter(self._embedding.embed(["dimension probe"])))
        size = len(list(sample_vector))
        if not self._client.collection_exists(self.settings.qdrant_collection):
            self._client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=VectorParams(size=size, distance=Distance.COSINE),
            )

    def upsert_document_chunks(self, chunks: list[KnowledgeChunk]) -> None:
        if not chunks:
            return
        vectors = list(self._embedding.embed([chunk.text for chunk in chunks]))
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            points.append(
                self._models.PointStruct(
                    id=_point_id(chunk.id),
                    vector=list(vector),
                    payload={
                        "chunk_id": chunk.id,
                        "document_id": chunk.document_id,
                        "title": chunk.title,
                        "path": chunk.path,
                        "client_id": chunk.client_id or "",
                        "chunk_index": chunk.chunk_index,
                        "text": chunk.text,
                        "excerpt": chunk.excerpt,
                    },
                )
            )
        self._client.upsert(collection_name=self.settings.qdrant_collection, points=points)

    def search(
        self,
        query: str,
        limit: int = 3,
        client_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        bounded_limit = _bounded_search_limit(limit)
        if not query.strip():
            return []
        query_vector = list(next(iter(self._embedding.embed([query]))))
        hits = self._client.search(
            collection_name=self.settings.qdrant_collection,
            query_vector=query_vector,
            limit=bounded_limit * 4 if client_id else bounded_limit,
        )
        chunks = [_chunk_from_payload(hit.payload or {}) for hit in hits]
        if client_id is not None:
            normalized_client_id = client_id.strip()
            chunks = [chunk for chunk in chunks if (chunk.client_id or "") == normalized_client_id]
        return chunks[:bounded_limit]


def search_backend_from_settings(settings: Settings, store: Store) -> KnowledgeSearchBackend:
    backend = settings.vector_backend.strip().lower()
    if backend in {"", "sqlite", "fts", "fts5"}:
        return SQLiteKnowledgeSearch(store)
    if backend == "qdrant":
        return QdrantKnowledgeSearch(settings)
    raise ValueError(f"unsupported vector backend: {settings.vector_backend}")


def validate_vector_settings(settings: Settings) -> None:
    if settings.vector_backend.strip().lower() == "qdrant" and settings.qdrant_url:
        if not settings.allow_http_probing:
            raise ValueError(
                "WAIT_QDRANT_URL requires WAIT_ALLOW_HTTP_PROBING=true "
                "because it may contact a remote vector service"
            )


def _point_id(chunk_id: int) -> str:
    return hashlib.sha256(f"wait-local-agent:{chunk_id}".encode()).hexdigest()


def _int_payload(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


def _str_payload(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return str(value) if value is not None else ""


def _chunk_from_payload(payload: dict[str, object]) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=_int_payload(payload, "chunk_id"),
        document_id=_int_payload(payload, "document_id"),
        title=_str_payload(payload, "title"),
        path=_str_payload(payload, "path"),
        chunk_index=_int_payload(payload, "chunk_index"),
        text=_str_payload(payload, "text"),
        excerpt=_str_payload(payload, "excerpt"),
        client_id=_str_payload(payload, "client_id") or None,
    )
