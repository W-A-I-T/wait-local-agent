"""Historical PSA automation discovery pack."""

PACK_MANIFEST = {
    "name": "automation-discovery",
    "version": "0.1.1",
    "requires_license": False,
    "api_router_factory": "packs.automation_discovery.router.create_router",
    "cli_app": None,
}
