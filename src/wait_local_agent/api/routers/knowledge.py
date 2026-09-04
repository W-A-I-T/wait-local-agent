"""Knowledge API routes."""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from fastapi import APIRouter, HTTPException

from wait_local_agent.api.context import AdminAccess, ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    KnowledgeAuthorityRequest,
    KnowledgeIngestRequest,
)
from wait_local_agent.api.scopes import resolve_client_scope
from wait_local_agent.knowledge import ingestion_service_from_settings
from wait_local_agent.vector_search import search_backend_from_settings


def create_knowledge_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store

    @router.post("/knowledge/ingest")
    def ingest_knowledge(
        request: KnowledgeIngestRequest,
        context: TechnicianAccess,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, request.client_id).client_id
        if scoped_client_id is None and not context.demo_mode:
            raise HTTPException(status_code=403, detail="knowledge ingestion requires a client scope")
        try:
            settings = replace(
                active_settings,
                document_parser=request.parser or active_settings.document_parser,
                allow_ocr=active_settings.allow_ocr if request.ocr is None else request.ocr,
            )
            service = ingestion_service_from_settings(store, settings)
            documents = service.ingest_path(Path(request.path), client_id=scoped_client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(document) for document in documents]

    @router.get("/knowledge/documents")
    def knowledge_documents(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [asdict(document) for document in store.list_knowledge_documents(client_id=scope)]

    @router.patch("/knowledge/documents/{document_id}/authority")
    def set_knowledge_document_authority(
        document_id: int,
        payload: KnowledgeAuthorityRequest,
        context: AdminAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, client_id)
        actor = context.approver_id or context.principal_id or "authenticated-admin"
        try:
            document = store.set_knowledge_document_authority(
                document_id,
                payload.authority,
                actor,
                client_id=scope,
                sop_version=payload.sop_version,
                superseded_by=payload.superseded_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if document is None:
            raise HTTPException(status_code=404, detail="knowledge document not found")
        return asdict(document)

    @router.get("/knowledge/search")
    def knowledge_search(
        context: ViewerAccess,
        q: str,
        limit: int = 3,
        backend: str | None = None,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        try:
            settings = replace(
                active_settings,
                vector_backend=backend or active_settings.vector_backend,
            )
            search_backend = search_backend_from_settings(settings, store)
            return [asdict(chunk) for chunk in search_backend.search(q, limit=limit, client_id=scope)]
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc





    return router


__all__ = ["create_knowledge_router"]


