#!/usr/bin/env python3
"""Print the stable route, handler, and rate-limit inventory for the API."""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from fastapi import routing
from fastapi.routing import APIRoute
from starlette.routing import Mount, Route

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wait_local_agent.api.app import create_app  # noqa: E402 - sys.path is configured above
from wait_local_agent.config import load_settings  # noqa: E402 - sys.path is configured above


def _route_records(application: Any) -> Iterable[dict[str, object]]:
    limiter = application.state.limiter
    included_router_type = getattr(routing, "_IncludedRouter", None)

    def record(
        route: Any,
        path: str,
        endpoint: Any,
        methods: Iterable[str],
        include_in_schema: bool,
    ) -> Iterable[dict[str, object]]:
        module = endpoint.__module__
        name = endpoint.__name__
        route_key = f"{module}.{name}"
        limits = limiter._route_limits.get(route_key, [])
        rate_limits = [str(limit.limit) for limit in limits]
        exempt = route_key in limiter._exempt_routes
        for method in sorted(methods):
            yield {
                "method": method,
                "path": path,
                "name": name,
                "include_in_schema": include_in_schema,
                "rate_limits": rate_limits,
                "exempt": exempt,
            }

    for route in application.routes:
        if included_router_type is not None and isinstance(route, included_router_type):
            for context in route.effective_route_contexts():
                if isinstance(context.original_route, (APIRoute, Route)):
                    yield from record(
                        context.original_route,
                        context.path,
                        context.endpoint,
                        context.methods or (),
                        context.include_in_schema,
                    )
            continue
        if isinstance(route, Mount) or not isinstance(route, APIRoute):
            continue
        yield from record(route, route.path, route.endpoint, route.methods or (), route.include_in_schema)


def export_route_inventory() -> dict[str, list[dict[str, object]]]:
    """Build a demo app with isolated state and return its route inventory."""

    with tempfile.TemporaryDirectory(prefix="wait-route-inventory-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        settings = replace(
            load_settings(),
            data_path=temporary_root / "state.db",
            vault_path=temporary_root / "vault",
            log_dir=temporary_root / "logs",
            demo_mode=True,
        )
        application = create_app(settings)
        routes = sorted(_route_records(application), key=lambda route: (str(route["path"]), str(route["method"])))

    return {"routes": routes}


if __name__ == "__main__":
    json.dump(export_route_inventory(), sys.stdout, indent=2)
    sys.stdout.write("\n")
