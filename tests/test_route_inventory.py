from __future__ import annotations

import json
from pathlib import Path

from fastapi import routing
from fastapi.routing import APIRoute
from starlette.routing import Mount

from scripts.export_route_inventory import export_route_inventory
from wait_local_agent.api.app import create_app


def _direct_routes(application) -> list[APIRoute]:
    return [route for route in application.routes if isinstance(route, APIRoute)]


def test_exported_route_inventory_matches_committed_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "route_inventory.json"
    committed = json.loads(fixture_path.read_text(encoding="utf-8"))

    assert committed == export_route_inventory()


def test_ui_mount_is_last_route(settings, monkeypatch, tmp_path: Path) -> None:
    ui_dist = tmp_path / "ui"
    ui_dist.mkdir()
    (ui_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setenv("WAIT_UI_DIST", str(ui_dist))

    application = create_app(settings)

    assert isinstance(application.routes[-1], Mount)


def test_migrated_router_routes_follow_existing_included_routers(settings) -> None:
    application = create_app(settings)
    included_router_type = routing._IncludedRouter
    migrated_prefix = "wait_local_agent.api.routers."
    first_migrated_route = next(
        index
        for index, route in enumerate(application.routes)
        if isinstance(route, APIRoute) and route.endpoint.__module__.startswith(migrated_prefix)
    )

    assert all(
        not isinstance(route, included_router_type) or index < first_migrated_route
        for index, route in enumerate(application.routes)
    )


def test_literal_route_registration_precedes_parameterized_shadow(settings) -> None:
    application = create_app(settings)
    routes = _direct_routes(application)

    def route_index(path: str, method: str) -> int:
        return next(
            index for index, route in enumerate(routes) if route.path == path and method in (route.methods or set())
        )

    assert route_index("/clients/commercial-activations", "GET") < route_index("/clients/{client_id}", "GET")
    assert route_index("/smart-actions/runs", "GET") < route_index("/smart-actions/{action_id}", "GET")


def test_literal_routes_are_not_shadowed_by_earlier_parameterized_routes(settings) -> None:
    application = create_app(settings)
    routes = _direct_routes(application)

    for index, literal_route in enumerate(routes):
        if "{" in literal_route.path:
            continue
        literal_methods = literal_route.methods or set()
        for earlier_route in routes[:index]:
            earlier_methods = earlier_route.methods or set()
            if "{" not in earlier_route.path or not (literal_methods & earlier_methods):
                continue
            assert earlier_route.path_regex.match(literal_route.path) is None, (
                f"{earlier_route.path} shadows {literal_route.path}"
            )
