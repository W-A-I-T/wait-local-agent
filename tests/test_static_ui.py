from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from pathlib import Path

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount

from wait_local_agent.api.app import SPAHtmlRoutesMiddleware, create_app
from wait_local_agent.spa_routes import SPA_ROUTE_PATHS

BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


def _ui_dist(tmp_path: Path) -> Path:
    ui_dist = tmp_path / "ui-dist"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html><body>spa-sentinel</body></html>", encoding="utf-8")
    return ui_dist


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
    docs_namespace = client.get("/docs/unknown")
    post_unknown = client.post("/unknown")
    known_api_404 = client.get("/clients/does-not-exist")
    openapi = client.get("/openapi.json")

    assert root.status_code == 200
    assert 'id="root"' in root.text
    assert asset.status_code == 200
    assert "console.log('wait');" in asset.text
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert browser_route.status_code == 200
    assert 'id="root"' in browser_route.text
    assert api_namespace.status_code == 404
    assert 'id="root"' not in api_namespace.text
    assert docs_namespace.status_code == 404
    assert 'id="root"' not in docs_namespace.text
    assert post_unknown.status_code in {404, 405}
    assert 'id="root"' not in post_unknown.text
    assert known_api_404.status_code == 404
    assert known_api_404.json() == {"detail": "client not found"}
    assert openapi.status_code == 200
    static_mount = next(route for route in app.routes if isinstance(route, Mount) and route.path in {"", "/"})
    assert app.routes[-1] is static_mount

    registered_health = next(route for route in app.routes if isinstance(route, APIRoute) and route.path == "/health")
    assert app.routes.index(registered_health) < app.routes.index(static_mount)


def test_known_browser_routes_are_served_before_api_matching(settings, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WAIT_UI_DIST", str(_ui_dist(tmp_path)))
    secure_settings = replace(settings, api_token="local-secret", demo_mode=False)
    client = TestClient(create_app(secure_settings))
    browser_headers = {"Accept": BROWSER_ACCEPT}

    browser_route = client.get("/clients", headers=browser_headers)
    json_request = client.get("/clients", headers={"Accept": "application/json"})
    curl_request = client.get("/clients", headers={"Accept": "*/*"})
    authenticated_api = client.get(
        "/clients",
        headers={"Accept": "application/json", "Authorization": "Bearer local-secret"},
    )
    session_authenticated_api = client.get(
        "/clients",
        headers={"Accept": "application/json", "Cookie": "wait_session=session"},
    )
    authenticated_browser = client.get(
        "/clients",
        headers={**browser_headers, "Authorization": "Bearer local-secret"},
    )
    known_api_404 = client.get(
        "/clients/does-not-exist",
        headers={**browser_headers, "Authorization": "Bearer local-secret"},
    )
    write_request = client.post("/clients", headers=browser_headers, json={"client_id": "new", "name": "New"})
    nested_route = client.get("/system/appliance-health", headers=browser_headers)
    nested_route_two = client.get("/microsoft-admin/azure-lighthouse", headers=browser_headers)
    trailing_slash = client.get("/clients/", headers=browser_headers)
    head_route = client.head("/clients", headers=browser_headers)
    docs = client.get("/docs", headers=browser_headers)
    openapi = client.get("/openapi.json", headers=browser_headers)
    untrusted_host = client.get(
        "/clients",
        headers={**browser_headers, "Host": "untrusted.example"},
    )

    assert browser_route.status_code == 200
    assert "spa-sentinel" in browser_route.text
    assert browser_route.headers["cache-control"] == "no-store"
    assert browser_route.headers["vary"] == "Accept"
    assert json_request.status_code == 401
    assert json_request.json()["detail"]
    assert "spa-sentinel" not in json_request.text
    assert curl_request.status_code == 401
    assert "spa-sentinel" not in curl_request.text
    assert authenticated_api.status_code == 200
    assert isinstance(authenticated_api.json(), list)
    assert "spa-sentinel" not in authenticated_api.text
    assert authenticated_api.headers["vary"] == "Accept"
    assert authenticated_api.headers["cache-control"] == "no-store"
    assert session_authenticated_api.status_code == 401
    assert session_authenticated_api.headers["vary"] == "Accept"
    assert session_authenticated_api.headers["cache-control"] == "no-store"
    assert authenticated_browser.status_code == 200
    assert "spa-sentinel" in authenticated_browser.text
    assert authenticated_browser.headers["cache-control"] == "no-store"
    assert authenticated_browser.headers["vary"] == "Accept"
    assert known_api_404.status_code == 404
    assert known_api_404.json() == {"detail": "client not found"}
    assert write_request.status_code == 401
    assert "spa-sentinel" not in write_request.text
    assert nested_route.status_code == 200
    assert "spa-sentinel" in nested_route.text
    assert nested_route_two.status_code == 200
    assert "spa-sentinel" in nested_route_two.text
    assert trailing_slash.status_code == 200
    assert "spa-sentinel" in trailing_slash.text
    assert trailing_slash.headers["cache-control"] == "no-store"
    assert trailing_slash.headers["vary"] == "Accept"
    assert head_route.status_code == 200
    assert head_route.headers["content-type"].startswith("text/html")
    assert head_route.content == b""
    assert head_route.headers["cache-control"] == "no-store"
    assert head_route.headers["vary"] == "Accept"
    assert docs.status_code == 200
    assert "spa-sentinel" not in docs.text
    assert openapi.status_code == 200
    assert openapi.json()["openapi"]
    assert "spa-sentinel" not in openapi.text
    assert untrusted_host.status_code == 400
    assert "spa-sentinel" not in untrusted_host.text


def test_spa_middleware_passes_non_http_scopes_to_wrapped_app(tmp_path: Path) -> None:
    calls: list[str] = []

    async def downstream(scope, receive, send) -> None:
        calls.append(scope["type"])

    async def receive():
        return {"type": "websocket.disconnect"}

    async def send(message) -> None:
        pass

    middleware = SPAHtmlRoutesMiddleware(
        downstream,
        index_path=tmp_path / "index.html",
        route_paths=SPA_ROUTE_PATHS,
    )
    asyncio.run(middleware({"type": "websocket"}, receive, send))

    assert calls == ["websocket"]


def test_spa_route_manifest_matches_ui_routes_and_reserved_namespaces() -> None:
    route_source = Path(__file__).parents[1] / "ui/src/routes.tsx"
    source = route_source.read_text(encoding="utf-8")
    explicit_paths = {
        f"/{path}"
        for path in re.findall(r'path="([^"]+)"', source)
        if path != "*"
    }
    assert re.search(r"<Route\s+index(?:\s|>)", source)
    ui_paths = explicit_paths | {"/"}

    assert len(SPA_ROUTE_PATHS) == 43
    assert ui_paths == SPA_ROUTE_PATHS
    reserved_prefixes = ("/api", "/docs", "/packs", "/openapi.json", "/healthz", "/auth")
    assert not any(
        route == reserved or route.startswith(f"{reserved}/")
        for route in SPA_ROUTE_PATHS
        for reserved in reserved_prefixes
    )


def test_browser_fallback_is_not_installed_without_valid_ui_dist(settings, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WAIT_UI_DIST", str(tmp_path / "missing-ui-dist"))
    secure_settings = replace(settings, api_token="local-secret", demo_mode=False)
    app = create_app(secure_settings)
    client = TestClient(app)

    response = client.get("/clients", headers={"Accept": BROWSER_ACCEPT})

    assert response.status_code == 401
    assert response.json()["detail"]
    assert not any(isinstance(route, Mount) and route.path in {"", "/"} for route in app.routes)


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
