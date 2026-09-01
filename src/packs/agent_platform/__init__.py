"""Governed agent platform extensions for WAIT Local Agent."""

PACK_MANIFEST = {
    "name": "agent-platform",
    "version": "0.1.0",
    "requires_license": False,
    "api_router_factory": "packs.agent_platform.router.create_router",
    "cli_app": None,
}
