from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SURFACE_CLASSES = frozenset({"exposed", "admin", "embedded", "hidden-by-design"})


def enumerate_fastapi_routes(application: Any) -> list[str]:
    """Return stable method/path identifiers for every mounted HTTP route."""

    from fastapi.routing import APIRoute
    from starlette.routing import Mount, Route

    identifiers: list[str] = []

    def visit(routes: Iterable[Any]) -> None:
        for route in routes:
            if isinstance(route, Mount):
                visit(route.routes)
                continue
            if not isinstance(route, (APIRoute, Route)):
                continue
            for method in sorted(route.methods or ()):
                identifiers.append(f"{method} {route.path}")

    visit(application.routes)
    return sorted(set(identifiers))


def enumerate_typer_commands(application: Any) -> list[str]:
    """Return stable dotted command identifiers from a Typer command tree."""

    from typer.main import get_command

    root = get_command(application)
    identifiers: list[str] = []

    def visit(command: Any, prefix: tuple[str, ...]) -> None:
        commands = getattr(command, "commands", None)
        if not isinstance(commands, dict):
            identifiers.append(" ".join((*prefix, command.name or "")))
            return
        for name, child in sorted(commands.items()):
            visit(child, (*prefix, name))

    visit(root, ())
    return sorted(identifier for identifier in identifiers if identifier.strip())


def enumerate_mcp_tools(agent_service: Any) -> list[str]:
    """Return the tool names exposed through WaitMcpServer.tools/list."""

    return sorted(f"wait.{tool.id}" for tool in agent_service.list_tools())


def build_surface_inventory(*, application: Any, cli_application: Any, agent_service: Any) -> dict[str, list[str]]:
    return {
        "fastapi_routes": enumerate_fastapi_routes(application),
        "typer_commands": enumerate_typer_commands(cli_application),
        "mcp_tools": enumerate_mcp_tools(agent_service),
    }
