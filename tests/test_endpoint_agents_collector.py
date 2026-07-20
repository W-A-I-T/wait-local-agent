"""Tests for the endpoint-agents collector module.

These exercise ``EndpointAgentsCollectorModule`` against its concrete return
contract by building a temporary root tree and redirecting the module's absolute
endpoint-agent marker paths at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.EndpointAgentsCollectorModule


@pytest.fixture()
def marker_root(tmp_path: Path) -> Path:
    root = tmp_path / "markers"
    root.mkdir()
    return root


def _use_marker_root(monkeypatch: pytest.MonkeyPatch, marker_root: Path, system: str = "Linux") -> None:
    original = collectors._EndpointAgentsPath

    def _mock_path(path: str, *, _root=marker_root, _original=original) -> Path:
        text = str(path)
        if text.startswith("/"):
            return _root / text.removeprefix("/")
        return _original(path)

    monkeypatch.setattr(collectors, "_EndpointAgentsPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _mkdir_marker(marker_root: Path, marker: str) -> Path:
    path = marker_root / marker.removeprefix("/")
    path.mkdir(parents=True)
    return path


def _touch_marker(marker_root: Path, marker: str) -> Path:
    path = marker_root / marker.removeprefix("/")
    path.parent.mkdir(parents=True)
    path.write_text("")
    return path


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_endpoint_agent_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "endpoint-agents"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "endpoint-agent"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == [
        "/opt/CrowdStrike",
        "/etc/systemd/system/falcon-sensor.service",
        "/opt/sentinelone",
        "/etc/systemd/system/sentinelone.service",
        "/opt/microsoft/mdatp",
        "/etc/opt/microsoft/mdatp",
        "/usr/local/jamf",
        "/Library/Application Support/JAMF",
        "/opt/microsoft/intune",
        "/etc/intune",
        "/etc/osquery",
        "/usr/bin/osqueryd",
        "/var/ossec",
        "/etc/ossec-init.conf",
        "/opt/carbonblack",
        "/etc/cb",
        "/opt/Tanium",
    ]
    assert scope["operations"] == ["read-endpoint-agent-marker"]


# --------------------------------------------------------------------------- #
# validate_config
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("config", [None, {}, {"limit": 0}, {"limit": 5}])
def test_validate_config_accepts_valid_config(config: Any) -> None:
    result = _collector().validate_config(config)
    assert result["ok"] is True
    assert result["errors"] == []


@pytest.mark.parametrize("config", [{"limit": -1}, {"limit": "x"}, {"limit": 1.5}])
def test_validate_config_rejects_bad_limit(config: Any) -> None:
    result = _collector().validate_config(config)
    assert result["ok"] is False
    assert any("limit" in error for error in result["errors"])


def test_validate_config_rejects_non_mapping() -> None:
    result = _collector().validate_config(["not", "a", "mapping"])
    assert result["ok"] is False
    assert any("mapping" in error for error in result["errors"])


# --------------------------------------------------------------------------- #
# collect / preview - concrete return contract
# --------------------------------------------------------------------------- #


def test_collect_detects_endpoint_agent_markers(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    crowdstrike_marker = _mkdir_marker(marker_root, "/opt/CrowdStrike")
    osquery_marker = _mkdir_marker(marker_root, "/etc/osquery")
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().collect()
    assert result["module_id"] == "endpoint-agents"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 2

    items = result["items"]
    assert [item["canonical_asset"]["attributes"]["agent"] for item in items] == [
        "CrowdStrike Falcon",
        "osquery",
    ]

    crowdstrike = items[0]["canonical_asset"]
    assert crowdstrike["asset_type"] == "endpoint-agent"
    assert crowdstrike["asset_id"] == "agent:crowdstrike-falcon"
    assert crowdstrike["name"] == "CrowdStrike Falcon"
    assert crowdstrike["attributes"]["agent"] == "CrowdStrike Falcon"
    assert crowdstrike["attributes"]["category"] == "edr"
    assert crowdstrike["attributes"]["detected_path"] == str(crowdstrike_marker)

    observations = {item["key"]: item["value"] for item in items[0]["observations"]}
    assert observations["agent.name"] == "CrowdStrike Falcon"
    assert observations["agent.category"] == "edr"
    assert observations["agent.detected_path"] == str(crowdstrike_marker)

    osquery = items[1]["canonical_asset"]
    assert osquery["asset_id"] == "agent:osquery"
    assert osquery["attributes"]["agent"] == "osquery"
    assert osquery["attributes"]["category"] == "osquery"
    assert osquery["attributes"]["detected_path"] == str(osquery_marker)

    agents = [item["canonical_asset"]["attributes"]["agent"] for item in items]
    assert "SentinelOne" not in agents
    assert "Tanium" not in agents


def test_collect_uses_first_marker_for_agent(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    first_marker = _mkdir_marker(marker_root, "/opt/sentinelone")
    _touch_marker(marker_root, "/etc/systemd/system/sentinelone.service")
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().collect()
    asset = result["items"][0]["canonical_asset"]
    assert asset["asset_id"] == "agent:sentinelone"
    assert asset["attributes"]["detected_path"] == str(first_marker)


def test_preview_marks_preview_and_caps_at_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    for marker in _collector().scope()["paths"]:
        _mkdir_marker(marker_root, marker)
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 9


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _mkdir_marker(marker_root, "/opt/CrowdStrike")
    _mkdir_marker(marker_root, "/etc/osquery")
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().collect({"limit": 1})
    assert result["ok"] is True
    assert result["count"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["canonical_asset"]["attributes"]["agent"] == "CrowdStrike Falcon"


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _mkdir_marker(marker_root, "/opt/CrowdStrike")
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _mkdir_marker(marker_root, "/opt/CrowdStrike")
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _mkdir_marker(marker_root, "/opt/CrowdStrike")
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _mkdir_marker(marker_root, "/opt/CrowdStrike")
    _use_marker_root(monkeypatch, marker_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_no_markers_exist(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _use_marker_root(monkeypatch, marker_root)

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_swallows_unreadable_marker(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    denied_marker = _mkdir_marker(marker_root, "/opt/CrowdStrike")
    _use_marker_root(monkeypatch, marker_root)

    real_exists = Path.exists

    def deny_exists(self: Path) -> bool:
        if self == denied_marker:
            raise PermissionError("denied")
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", deny_exists)
    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_endpoint_agents_collector_is_idempotent() -> None:
    collectors._register_endpoint_agents_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("endpoint-agents")
        assert module is not None
        assert module.module_id == "endpoint-agents"


def test_register_supports_list_set_tuple_and_register_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    class RegistryObject:
        def register(self, module: Any) -> None:
            calls["register"] = module

    listed: list[Any] = []
    setted: set[Any] = set()
    monkeypatch.setattr(collectors, "COLLECTOR_MODULES", listed, raising=False)
    monkeypatch.setattr(collectors, "COLLECTORS", setted, raising=False)
    monkeypatch.setattr(collectors, "COLLECTOR_REGISTRY", RegistryObject(), raising=False)
    monkeypatch.setattr(collectors, "collector_registry", (), raising=False)
    monkeypatch.setattr(collectors, "__all__", [], raising=False)

    collectors._register_endpoint_agents_collector()
    collectors._register_endpoint_agents_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("endpoint-agents") == 1
    assert any(getattr(m, "module_id", None) == "endpoint-agents" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "endpoint-agents"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("endpoint-agents") == 1
    assert "EndpointAgentsCollectorModule" in collectors.__dict__["__all__"]


# --------------------------------------------------------------------------- #
# detection helpers
# --------------------------------------------------------------------------- #


_M = collectors.EndpointAgentsCollectorModule


def test_agent_slug_lowercases_and_replaces_spaces_only() -> None:
    assert _M._agent_slug("Microsoft Intune / Company Portal") == "microsoft-intune-/-company-portal"


def test_first_existing_marker_returns_none_when_marker_missing(
    monkeypatch: pytest.MonkeyPatch,
    marker_root: Path,
) -> None:
    _use_marker_root(monkeypatch, marker_root)

    result = _M._first_existing_marker(("/opt/Tanium",))
    assert result is None
