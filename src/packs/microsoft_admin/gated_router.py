from __future__ import annotations

from fastapi import APIRouter, Depends

from packs.microsoft_admin.capability_access import create_access_router
from packs.microsoft_admin.router import create_router as create_core_router
from wait_local_agent.capabilities import MICROSOFT_ADMIN_CAPABILITY
from wait_local_agent.rbac import require_capability


def create_router() -> APIRouter:
    """Compose access management with capability-gated Microsoft Admin operations."""

    router = APIRouter()
    router.include_router(create_access_router())
    router.include_router(
        create_core_router(),
        dependencies=[Depends(require_capability(MICROSOFT_ADMIN_CAPABILITY))],
    )
    return router
