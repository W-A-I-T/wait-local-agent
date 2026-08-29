"""WAIT Microsoft Cloud and Endpoint Administrator pack."""

PACK_MANIFEST = {
    "name": "microsoft-admin",
    "version": "0.1.0",
    "requires_license": False,
    "api_router_factory": "packs.microsoft_admin.router.create_router",
    "cli_app": "packs.microsoft_admin.cli.app",
}
