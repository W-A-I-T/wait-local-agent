"""Bounded Work IQ MCP adapter.

Work IQ is a preview Microsoft 365 MCP service. This adapter deliberately
keeps preview metadata untrusted and does not infer read/write permissions from
remote annotations. Discovery is available to administrators; explicit calls
are library-only and require a locally configured read-tool allowlist.
"""

from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.config import Settings
from wait_local_agent.mcp_client import McpClient, McpClientResponse

WORK_IQ_PROVIDER = "microsoft_work_iq"
WORK_IQ_MUTATING_TOOL_NAMES = frozenset(
    {"create_entity", "update_entity", "delete_entity", "do_action", "call_function"}
)


class WorkIqClient:
    """Use the existing bounded MCP client for an explicitly configured gateway."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._client = McpClient(
            replace(
                settings,
                mcp_client_enabled=settings.work_iq_enabled,
                mcp_client_url=settings.work_iq_url,
                mcp_client_token=settings.work_iq_token,
                mcp_client_name="WAIT Local Agent Work IQ",
                mcp_client_allowed_hosts=settings.work_iq_allowed_hosts,
                mcp_client_timeout_seconds=settings.work_iq_timeout_seconds,
            ),
            transport=transport,
        )

    def list_tools(self) -> McpClientResponse:
        """Discover Work IQ tools without registering or selecting them locally."""

        response = self._client.list_tools()
        if response.status != "ready":
            return response
        result = dict(response.result)
        result.update(
            {
                "provider": WORK_IQ_PROVIDER,
                "preview_integration": True,
                "authentication": "Microsoft Entra ID bearer token supplied by the operator",
                "remote_metadata_untrusted": True,
                "read_only_execution": "disabled_until_locally_allowlisted",
                "configured_read_tool_names": list(self._read_tool_names()),
            }
        )
        return McpClientResponse("ready", "Work IQ tools discovered", result)

    def call_read_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> McpClientResponse:
        """Call one locally allowlisted tool; no API route exposes this method."""

        if not isinstance(name, str):
            return McpClientResponse("failed", "Work IQ tool name is invalid")
        normalized = name.strip()
        if normalized in WORK_IQ_MUTATING_TOOL_NAMES:
            return McpClientResponse(
                "blocked",
                "Work IQ mutation and action tools are not supported by this adapter",
            )
        if normalized not in self._read_tool_names():
            return McpClientResponse(
                "blocked",
                "Work IQ tool is not locally allowlisted for read-only use",
            )
        return self._client.call_tool(normalized, arguments)

    def _read_tool_names(self) -> tuple[str, ...]:
        return tuple(
            name.strip()
            for name in self.settings.work_iq_read_tool_names
            if name.strip()
            and len(name.strip()) <= 200
            and not any(ord(char) < 32 for char in name)
        )
