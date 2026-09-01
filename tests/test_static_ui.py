from __future__ import annotations

from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount

from wait_local_agent.api.app import create_app


def test_ui_is_not_mounted_without_wait_ui_dist(settings, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_UI_DIST", raising=False)

    app = create_app(settings)
    response = TestClient(app).get("/not-a-dashboard-route")

    assert response.status_code == 404
    assert not any(isinstance(route, Mount) and route.path in {"", "/"} for route in app.routes)


def test_compiled_ui_has_assets_and_spa_fallback(settings, monkeypatch, tmp_path: Path) -> None:
    ui_dist = tmp_path / "ui-dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text('<html><body><div id="root"></div></body></html>', encoding="utf-8")
    (ui_dist / "assets").mkdir()
    (ui_dist / "assets/app.js").write_text("console.log('wait');", encoding="utf-8")
    monkeypatch.setenv("WAIT_UI_DIST", str(ui_dist))

    app = create_app(settings)
    client = TestClient(app)

    root = client.get("/")
    asset = client.get("/assets/app.js")
    browser_route = client.get("/settings/unknown-view")
    api_namespace = client.get("/api/unknown")
    known_api_404 = client.get("/clients/does-not-exist")
    openapi = client.get("/openapi.json")

    assert root.status_code == 200
    assert 'id="root"' in root.text
    assert asset.status_code == 200
    assert "console.log('wait');" in asset.text
    assert browser_route.status_code == 200
    assert 'id="root"' in browser_route.text
    assert api_namespace.status_code == 404
    assert 'id="root"' not in api_namespace.text
    assert known_api_404.status_code == 404
    assert known_api_404.json() == {"detail": "client not found"}
    assert openapi.status_code == 200
    static_mount = next(route for route in app.routes if isinstance(route, Mount) and route.path in {"", "/"})
    assert app.routes[-1] is static_mount

    registered_health = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/health")
    assert app.routes.index(registered_health) < app.routes.index(static_mount)


def test_healthz_is_public_but_health_remains_authenticated(settings, monkeypatch) -> None:
    monkeypatch.delenv("WAIT_UI_DIST", raising=False)
    secure_settings = settings.__class__(
        **{**settings.__dict__, "api_token": "local-secret", "demo_mode": False}
    )
    client = TestClient(create_app(secure_settings))

    healthz = client.get("/healthz")
    health = client.get("/health")
    authenticated_health = client.get("/health", headers={"Authorization": "Bearer local-secret"})

    assert healthz.status_code == 200
    assert healthz.json() == {"status": "ok"}
    assert health.status_code == 401
    assert authenticated_health.status_code == 200
