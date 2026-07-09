from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.store import Store


def test_general_route_rate_limit_returns_429_with_retry_after(settings) -> None:
    limited_settings = settings.__class__(
        **{
            **settings.__dict__,
            "rate_limit_enabled": True,
            "rate_limit_general": "2/minute",
            "rate_limit_connector": "1/minute",
        }
    )
    Store(limited_settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(limited_settings))

    first = client.get("/tickets")
    second = client.get("/tickets")
    third = client.get("/tickets")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.headers["retry-after"]


def test_connector_route_uses_stricter_limit(settings) -> None:
    limited_settings = settings.__class__(
        **{
            **settings.__dict__,
            "rate_limit_enabled": True,
            "rate_limit_general": "5/minute",
            "rate_limit_connector": "1/minute",
        }
    )
    client = TestClient(create_app(limited_settings))

    first = client.get("/connectors/halopsa/health")
    second = client.get("/connectors/halopsa/health")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"]


def test_rate_limit_can_be_disabled(settings) -> None:
    disabled_settings = settings.__class__(
        **{
            **settings.__dict__,
            "rate_limit_enabled": False,
            "rate_limit_general": "1/minute",
            "rate_limit_connector": "1/minute",
        }
    )
    Store(disabled_settings.data_path).ingest_ticket_file(Path("examples/sample_tickets/tickets.json"))
    client = TestClient(create_app(disabled_settings))

    first = client.get("/tickets")
    second = client.get("/tickets")
    third = client.get("/tickets")

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 200
