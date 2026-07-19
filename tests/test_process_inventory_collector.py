from wait_local_agent.collectors import ProcessInventoryCollectorModule


def test_process_inventory_preview_and_collect_emit_process_assets(monkeypatch):
    module = ProcessInventoryCollectorModule()
    records = [
        {
            "pid": 123,
            "name": "python",
            "cmdline": "python -m wait_local_agent",
            "state": "S (sleeping)",
        }
    ]

    monkeypatch.setattr(module, "_process_records", lambda limit=None: records)

    preview = module.preview()
    collected = module.collect()

    for result in (preview, collected):
        assert result["ok"] is True
        assert result["assets"][0]["asset_type"] == "process"
        assert result["assets"][0]["asset_id"] == "process:123"
        assert result["items"][0]["canonical_asset"]["asset_type"] == "process"
        assert result["items"][0]["observations"]
        assert {
            observation["key"] for observation in result["items"][0]["observations"]
        } >= {"process.pid", "process.name", "process.cmdline", "process.state"}


def test_process_inventory_module_is_registered():
    import wait_local_agent.collectors as collectors

    registries = [
        getattr(collectors, name)
        for name in (
            "MODULE_REGISTRY",
            "COLLECTOR_MODULES",
            "COLLECTOR_REGISTRY",
            "COLLECTORS",
            "collector_registry",
        )
        if isinstance(getattr(collectors, name, None), dict)
    ]

    assert any("process-inventory" in registry for registry in registries)
