"""Router mounting helpers."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI


def mount_flat(app: FastAPI, router: APIRouter) -> None:
    """Mount an API router while keeping its routes directly inspectable."""

    app.router.routes.extend(router.routes)


__all__ = ["mount_flat"]
