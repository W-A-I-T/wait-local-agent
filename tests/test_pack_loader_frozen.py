from __future__ import annotations

import wait_local_agent.api.packs.loader as loader_module
from wait_local_agent.api.packs.loader import load_pack_registry


def test_frozen_runtime_discovers_builtin_pack_without_pkgutil_enumeration(monkeypatch, settings) -> None:
    monkeypatch.setattr(loader_module.sys, "frozen", True, raising=False)
    monkeypatch.setattr(loader_module.pkgutil, "iter_modules", lambda _paths: [])
    monkeypatch.setattr(loader_module.importlib.util, "find_spec", lambda _name: None)

    discovered = loader_module._discover_candidate_modules(None)
    registry = load_pack_registry(settings)

    assert discovered == ["packs.microsoft_admin"]
    assert [status.name for status in registry.statuses] == ["microsoft-admin"]
    assert registry.get_pack("microsoft-admin") is not None
