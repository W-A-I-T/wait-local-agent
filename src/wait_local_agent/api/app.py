from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from wait_local_agent.config import Settings, load_settings
from wait_local_agent.providers import provider_from_settings
from wait_local_agent.services import TicketIntelligenceService
from wait_local_agent.store import Store


class ApprovalRequest(BaseModel):
    status: Literal["approved", "rejected", "pending"]


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or load_settings()
    store = Store(active_settings.data_path)
    service = TicketIntelligenceService(
        store=store,
        settings=active_settings,
        provider=provider_from_settings(active_settings),
    )

    app = FastAPI(title="WAIT Local Agent", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, object]:
        return {
            "status": "ok",
            "write_actions_enabled": active_settings.allow_write_actions,
            "http_probing_enabled": active_settings.allow_http_probing,
            "cloud_fallback_enabled": active_settings.allow_cloud_fallback,
        }

    @app.get("/settings/providers")
    def providers() -> dict[str, object]:
        return {
            "local_model_provider": active_settings.local_model_provider,
            "local_model_base_url": active_settings.local_model_base_url,
            "local_model_name": active_settings.local_model_name,
            "vector_backend": active_settings.vector_backend,
        }

    @app.get("/tickets")
    def tickets() -> list[dict[str, object]]:
        return [asdict(ticket) for ticket in store.list_tickets()]

    @app.get("/tickets/{ticket_id}/summary")
    def summarize_ticket(ticket_id: str) -> dict[str, object]:
        try:
            return asdict(service.summarize(ticket_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc

    @app.post("/tickets/{ticket_id}/approvals")
    def update_approval(ticket_id: str, request: ApprovalRequest) -> dict[str, str]:
        if store.get_ticket(ticket_id) is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        store.set_approval(ticket_id, request.status)
        return {"ticket_id": ticket_id, "status": request.status}

    @app.get("/audit")
    def audit() -> list[dict[str, object]]:
        return [asdict(event) for event in store.list_audit_events()]

    return app
