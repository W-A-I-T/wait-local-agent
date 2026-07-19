"""Tests for the firewall-rules collector module.

These exercise ``FirewallRulesCollectorModule`` against its concrete return
contract by building a real temporary firewall config tree and redirecting the
module's path alias at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.FirewallRulesCollectorModule


@pytest.fixture()
def firewall_root(tmp_path: Path) -> Path:
    root = tmp_path / "firewall"
    root.mkdir()
    return root


def _write_firewall_file(root: Path, filename: str, content: str) -> None:
    (root / filename).write_text(content)


def _use_firewall_configs(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
    system: str = "Linux",
) -> None:
    original = collectors._FirewallRulesPath
    mapping = {
        "/etc/nftables.conf": "nftables.conf",
        "/etc/iptables/rules.v4": "rules.v4",
        "/etc/iptables/rules.v6": "rules.v6",
        "/etc/ufw/user.rules": "user.rules",
        "/etc/ufw/user6.rules": "user6.rules",
    }

    def _mock_path(path: Path, *, _root=firewall_root, _original=original) -> Path:
        mapped = mapping.get(str(path))
        if mapped is None:
            return _original(path)
        return _root / mapped

    monkeypatch.setattr(collectors, "_FirewallRulesPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_firewall_rules_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "firewall-rules"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "firewall-rule"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == [
        "/etc/nftables.conf",
        "/etc/iptables/rules.v4",
        "/etc/iptables/rules.v6",
        "/etc/ufw/user.rules",
        "/etc/ufw/user6.rules",
    ]
    assert scope["operations"] == ["read-firewall-config"]


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


def test_collect_parses_nftables_and_iptables_rules_and_skips_noise(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _write_firewall_file(
        firewall_root,
        "nftables.conf",
        """
# comment

table inet filter {
chain input {
add rule inet filter input tcp dport 22 accept
add rule inet filter forward ip saddr 10.0.0.0/8 drop
}
""",
    )
    _write_firewall_file(
        firewall_root,
        "rules.v4",
        """
*filter
:INPUT ACCEPT [0:0]
-A INPUT -p tcp --dport 443 -j ACCEPT
-I FORWARD -s 10.0.0.0/8 -j DROP
COMMIT
""",
    )
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().collect()
    assert result["module_id"] == "firewall-rules"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 5
    assert len(result["items"]) == 5

    first_asset = result["items"][0]["canonical_asset"]
    assert first_asset["asset_type"] == "firewall-rule"
    assert first_asset["asset_id"] == "fwrule:rules.v4:1"
    assert first_asset["name"] == "rules.v4:1"
    assert first_asset["attributes"]["source_file"] == "/etc/iptables/rules.v4"
    assert first_asset["attributes"]["chain"] == "INPUT"
    assert first_asset["attributes"]["action"] == "ACCEPT"
    assert first_asset["attributes"]["rule_text"] == "-A INPUT -p tcp --dport 443 -j ACCEPT"

    first_observations = {obs["key"]: obs["value"] for obs in result["items"][0]["observations"]}
    assert first_observations["firewall.source_file"] == "/etc/iptables/rules.v4"
    assert first_observations["firewall.chain"] == "INPUT"
    assert first_observations["firewall.action"] == "ACCEPT"
    assert first_observations["firewall.rule_text"] == "-A INPUT -p tcp --dport 443 -j ACCEPT"

    assert result["items"][1]["canonical_asset"]["attributes"]["chain"] == "FORWARD"
    assert result["items"][1]["canonical_asset"]["attributes"]["action"] == "DROP"

    nft_chain = result["items"][2]["canonical_asset"]
    assert nft_chain["asset_id"] == "fwrule:nftables.conf:1"
    assert nft_chain["attributes"]["source_file"] == "/etc/nftables.conf"
    assert nft_chain["attributes"]["chain"] == "input"
    assert nft_chain["attributes"]["action"] == ""
    assert nft_chain["attributes"]["rule_text"] == "chain input {"

    nft_rule = result["items"][3]["canonical_asset"]
    assert nft_rule["attributes"]["chain"] == "input"
    assert nft_rule["attributes"]["action"] == "accept"
    assert nft_rule["attributes"]["rule_text"] == "add rule inet filter input tcp dport 22 accept"


def test_collect_sorts_by_source_file_then_rule_index(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _write_firewall_file(firewall_root, "nftables.conf", "add rule inet filter output accept\n")
    _write_firewall_file(firewall_root, "rules.v4", "-A INPUT -j ACCEPT\n")
    _write_firewall_file(firewall_root, "user.rules", "allow from 192.0.2.1 to any port 22\n")
    _use_firewall_configs(monkeypatch, firewall_root)

    order = [
        item["canonical_asset"]["attributes"]["source_file"]
        for item in _collector().collect()["items"]
    ]
    assert order == [
        "/etc/iptables/rules.v4",
        "/etc/nftables.conf",
        "/etc/ufw/user.rules",
    ]


def test_collect_parses_ufw_rule_lines(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _write_firewall_file(
        firewall_root,
        "user.rules",
        """
### tuple ### allow tcp 22 0.0.0.0/0 any 0.0.0.0/0 in
allow from any to any port 22
deny from 203.0.113.9 to any
reject from 198.51.100.4 to any
""",
    )
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().collect()
    actions = [item["canonical_asset"]["attributes"]["action"] for item in result["items"]]
    assert actions == ["allow", "deny", "reject"]
    assert result["items"][0]["canonical_asset"]["attributes"]["chain"] == ""


def test_preview_marks_preview_and_caps_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    rows = [f"-A INPUT -p tcp --dport {index} -j ACCEPT" for index in range(1, 16)]
    _write_firewall_file(firewall_root, "rules.v4", "\n".join(rows))
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10
    assert len(result["items"]) == 10


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    rows = [f"-A INPUT -p tcp --dport {index} -j ACCEPT" for index in range(1, 6)]
    _write_firewall_file(firewall_root, "rules.v4", "\n".join(rows))
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().collect({"limit": 2})
    assert result["count"] == 2
    assert [
        item["canonical_asset"]["attributes"]["rule_text"]
        for item in result["items"]
    ] == [
        "-A INPUT -p tcp --dport 1 -j ACCEPT",
        "-A INPUT -p tcp --dport 2 -j ACCEPT",
    ]


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _write_firewall_file(firewall_root, "rules.v4", "-A INPUT -j ACCEPT\n")
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _use_firewall_configs(monkeypatch, firewall_root)
    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _use_firewall_configs(monkeypatch, firewall_root)
    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _write_firewall_file(firewall_root, "rules.v4", "-A INPUT -j ACCEPT\n")
    _use_firewall_configs(monkeypatch, firewall_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_firewall_files_missing(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_swallows_unreadable_file_as_directory(
    monkeypatch: pytest.MonkeyPatch,
    firewall_root: Path,
) -> None:
    (firewall_root / "nftables.conf").mkdir()
    _write_firewall_file(firewall_root, "rules.v4", "-A INPUT -j ACCEPT\n")
    _use_firewall_configs(monkeypatch, firewall_root)

    result = _collector().collect()
    assert result["count"] == 1
    assert result["items"][0]["canonical_asset"]["attributes"]["source_file"] == "/etc/iptables/rules.v4"


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_firewall_rules_collector_is_idempotent() -> None:
    collectors._register_firewall_rules_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("firewall-rules")
        assert module is not None
        assert module.module_id == "firewall-rules"


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

    collectors._register_firewall_rules_collector()
    collectors._register_firewall_rules_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("firewall-rules") == 1
    assert any(getattr(m, "module_id", None) == "firewall-rules" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "firewall-rules"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("firewall-rules") == 1
    assert "FirewallRulesCollectorModule" in collectors.__dict__["__all__"]


def test_register_creates_module_registry_when_no_registry_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(collectors, "MODULE_REGISTRY", raising=False)
    monkeypatch.delattr(collectors, "COLLECTOR_MODULES", raising=False)
    monkeypatch.delattr(collectors, "COLLECTOR_REGISTRY", raising=False)
    monkeypatch.delattr(collectors, "COLLECTORS", raising=False)
    monkeypatch.delattr(collectors, "collector_registry", raising=False)

    collectors._register_firewall_rules_collector()

    registry = collectors.__dict__["MODULE_REGISTRY"]
    assert registry["firewall-rules"].module_id == "firewall-rules"


# --------------------------------------------------------------------------- #
# parse helpers
# --------------------------------------------------------------------------- #


_M = collectors.FirewallRulesCollectorModule


def test_parse_firewall_rule_line_rejects_blank_comment_and_unknown_lines() -> None:
    assert _M._parse_firewall_rule_line("", "/etc/nftables.conf", "nftables.conf", 1) is None
    assert _M._parse_firewall_rule_line("   # comment", "/etc/nftables.conf", "nftables.conf", 1) is None
    assert _M._parse_firewall_rule_line("*filter", "/etc/iptables/rules.v4", "rules.v4", 1) is None
    assert _M._parse_firewall_rule_line("COMMIT", "/etc/iptables/rules.v4", "rules.v4", 1) is None


def test_parse_firewall_rule_line_truncates_long_rule_text() -> None:
    long_rule = "-A INPUT -m comment --comment " + ("x" * 400) + " -j ACCEPT"
    record = _M._parse_firewall_rule_line(long_rule, "/etc/iptables/rules.v4", "rules.v4", 1)
    assert record is not None
    assert len(record["rule_text"]) == 300
    assert record["rule_text"].startswith("-A INPUT -m comment")


def test_extract_nft_chain_error_and_fallback_paths() -> None:
    assert _M._extract_nft_chain(["add", "chain"]) == ""
    assert _M._extract_nft_chain(["add", "rule"]) == ""
    assert _M._extract_nft_chain(["add", "rule", "filter", "input"]) == "input"
    assert _M._extract_nft_chain(["add", "rule", "inet", "filter", "input"]) == "input"


def test_extract_iptables_chain_error_path() -> None:
    assert _M._extract_iptables_chain(["--append", "INPUT"]) == ""


def test_extract_action_paths() -> None:
    assert _M._extract_action(["-A", "INPUT", "--jump", "REJECT"]) == "REJECT"
    assert _M._extract_action(["-A", "INPUT", "-j"]) == ""
    assert _M._extract_action(["add", "rule", "inet", "filter", "input", "drop;"]) == "drop"
    assert _M._extract_action(["chain", "input", "{"]) == ""


def test_rule_type_helpers() -> None:
    assert _M._is_nft_rule(["add", "rule", "inet", "filter", "input"]) is True
    assert _M._is_nft_rule(["chain", "input", "{"]) is True
    assert _M._is_nft_rule(["add"]) is False
    assert _M._is_iptables_rule(["-A", "INPUT"]) is True
    assert _M._is_iptables_rule(["-D", "INPUT"]) is False
    assert _M._is_ufw_rule(["allow", "from", "any"]) is True
    assert _M._is_ufw_rule(["route", "allow"]) is False
