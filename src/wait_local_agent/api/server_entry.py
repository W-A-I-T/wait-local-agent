from __future__ import annotations

import os

import uvicorn

from wait_local_agent.api.app import create_app
from wait_local_agent.config import load_settings

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788


def main() -> None:
    """Start the local sidecar API using environment-configured settings."""
    host = os.getenv("WAIT_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST
    port = _port_from_env(os.getenv("WAIT_PORT"))
    uvicorn.run(create_app(load_settings()), host=host, port=port)


def _port_from_env(value: str | None) -> int:
    if value is None:
        return DEFAULT_PORT
    try:
        port = int(value)
    except ValueError:
        return DEFAULT_PORT
    return port if 1 <= port <= 65535 else DEFAULT_PORT
