"""Tests for the web-services collector module.

These exercise ``WebServicesCollectorModule`` against its concrete return
contract by building a real temporary ``/etc`` tree and redirecting the module's
web config path alias at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.WebServicesCollectorModule


@pytest.fixture()
def etc_root(tmp_path: Path) -> Path:
    root = tmp_path / "etc"
    root.mkdir()
    return root


def _use_etc(monkeypatch: pytest.MonkeyPatch, etc_root: Path, system: str = "Linux") -> None:
    original = collectors._WebServicesPath

    def _mock_path(path: Path, *, _root=etc_root, _original=original) -> Path:
        text = str(path)
        if text == "/etc":
            return _root
        if text.startswith("/etc/"):
            return _root / text.removeprefix("/etc/")
        return _original(path)

    monkeypatch.setattr(collectors, "_WebServicesPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _write_nginx_config(etc_root: Path) -> Path:
    config_path = etc_root / "nginx" / "sites-enabled" / "site.conf"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "server {",
                "  listen 443 ssl;",
                "  server_name example.com www.example.com;",
                "  root /var/www;",
                "}",
            ]
        )
    )
    return config_path


def _write_apache_config(etc_root: Path) -> Path:
    config_path = etc_root / "apache2" / "sites-enabled" / "vhost.conf"
    config_path.parent.mkdir(parents=True)
    config_path.write_text("<VirtualHost *:80>ServerName a.test DocumentRoot /srv</VirtualHost>")
    return config_path


def _write_caddy_config(etc_root: Path) -> Path:
    config_path = etc_root / "caddy" / "Caddyfile"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "https://caddy.test:8443 {",
                "  root * /srv/caddy",
                "}",
            ]
        )
    )
    return config_path


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_web_services_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "web-services"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "web-service"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == [
        "/etc/nginx/nginx.conf",
        "/etc/nginx/sites-enabled/*",
        "/etc/nginx/conf.d/*.conf",
        "/etc/apache2/sites-enabled/*",
        "/etc/httpd/conf.d/*.conf",
        "/etc/apache2/apache2.conf",
        "/etc/caddy/Caddyfile",
    ]
    assert scope["operations"] == ["read-web-service-config"]


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


def test_collect_parses_nginx_and_apache_configs(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    nginx_config = _write_nginx_config(etc_root)
    apache_config = _write_apache_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect()
    assert result["module_id"] == "web-services"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 2

    items_by_type = {
        item["canonical_asset"]["attributes"]["server_type"]: item
        for item in result["items"]
    }

    apache = items_by_type["apache"]["canonical_asset"]
    assert apache["asset_type"] == "web-service"
    assert apache["asset_id"] == "web:apache:1"
    assert apache["name"] == "a.test:80"
    assert apache["attributes"]["server_type"] == "apache"
    assert apache["attributes"]["config_file"] == str(apache_config)
    assert apache["attributes"]["server_name"] == "a.test"
    assert apache["attributes"]["port"] == "80"
    assert apache["attributes"]["document_root"] == "/srv"

    apache_observations = {
        item["key"]: item["value"] for item in items_by_type["apache"]["observations"]
    }
    assert apache_observations["web.server_type"] == "apache"
    assert apache_observations["web.config_file"] == str(apache_config)
    assert apache_observations["web.server_name"] == "a.test"
    assert apache_observations["web.port"] == "80"
    assert apache_observations["web.document_root"] == "/srv"

    nginx = items_by_type["nginx"]["canonical_asset"]
    assert nginx["asset_id"] == "web:nginx:1"
    assert nginx["name"] == "example.com:443"
    assert nginx["attributes"]["server_type"] == "nginx"
    assert nginx["attributes"]["config_file"] == str(nginx_config)
    assert nginx["attributes"]["server_name"] == "example.com"
    assert nginx["attributes"]["port"] == "443"
    assert nginx["attributes"]["document_root"] == "/var/www"


def test_collect_parses_caddy_config(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    caddy_config = _write_caddy_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect()
    asset = result["items"][0]["canonical_asset"]
    assert asset["asset_id"] == "web:caddy:1"
    assert asset["name"] == "caddy.test:8443"
    assert asset["attributes"]["server_type"] == "caddy"
    assert asset["attributes"]["config_file"] == str(caddy_config)
    assert asset["attributes"]["server_name"] == "caddy.test"
    assert asset["attributes"]["port"] == "8443"
    assert asset["attributes"]["document_root"] == "/srv/caddy"


def test_collect_sorts_by_server_type_config_file_and_index(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_nginx_config(etc_root)
    _write_apache_config(etc_root)
    _write_caddy_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    order = [
        item["canonical_asset"]["attributes"]["server_type"]
        for item in _collector().collect()["items"]
    ]
    assert order == ["apache", "caddy", "nginx"]


def test_preview_marks_preview_and_caps_at_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    config_path = etc_root / "nginx" / "sites-enabled" / "site.conf"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            f"server {{ listen 8{index}; server_name site{index}.test; root /srv/{index}; }}"
            for index in range(15)
        )
    )
    _use_etc(monkeypatch, etc_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 10
    assert len(result["items"]) == 10


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_nginx_config(etc_root)
    _write_apache_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect({"limit": 1})
    assert result["ok"] is True
    assert result["count"] == 1
    assert len(result["items"]) == 1
    assert result["items"][0]["canonical_asset"]["attributes"]["server_type"] == "apache"


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_nginx_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _use_etc(monkeypatch, etc_root)
    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _use_etc(monkeypatch, etc_root)
    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_nginx_config(etc_root)
    _use_etc(monkeypatch, etc_root, system="Darwin")

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_returns_empty_when_no_configs_exist(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_swallows_unreadable_config(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    nginx_config = _write_nginx_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    real_read_text = Path.read_text

    def deny_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == nginx_config:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_read_text)
    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_swallows_glob_error(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_apache_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    real_glob = Path.glob

    def boom(self: Path, pattern: str) -> Any:
        if self.name == "conf.d":
            raise OSError("boom")
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", boom)
    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"][0]["canonical_asset"]["attributes"]["server_type"] == "apache"


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_web_services_collector_is_idempotent() -> None:
    collectors._register_web_services_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("web-services")
        assert module is not None
        assert module.module_id == "web-services"


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

    collectors._register_web_services_collector()
    collectors._register_web_services_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("web-services") == 1
    assert any(getattr(m, "module_id", None) == "web-services" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "web-services"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("web-services") == 1
    assert "WebServicesCollectorModule" in collectors.__dict__["__all__"]


def test_register_creates_module_registry_when_no_registry_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(collectors, "MODULE_REGISTRY", raising=False)
    monkeypatch.delattr(collectors, "COLLECTOR_MODULES", raising=False)
    monkeypatch.delattr(collectors, "COLLECTOR_REGISTRY", raising=False)
    monkeypatch.delattr(collectors, "COLLECTORS", raising=False)
    monkeypatch.delattr(collectors, "collector_registry", raising=False)

    collectors._register_web_services_collector()

    registry = collectors.__dict__["MODULE_REGISTRY"]
    assert registry["web-services"].module_id == "web-services"


# --------------------------------------------------------------------------- #
# parse helpers
# --------------------------------------------------------------------------- #


_M = collectors.WebServicesCollectorModule


def test_parse_nginx_config_handles_missing_fields_and_comments() -> None:
    records = _M._parse_nginx_config(
        "\n".join(
            [
                "server {",
                "  listen 127.0.0.1:8080; # comment",
                "  server_name 'quoted.test';",
                "}",
                "server {",
                "  root /srv/default;",
                "}",
            ]
        ),
        "/etc/nginx/nginx.conf",
    )
    assert records[0]["server_name"] == "quoted.test"
    assert records[0]["port"] == "8080"
    assert records[0]["document_root"] == ""
    assert records[1]["server_name"] == ""
    assert records[1]["port"] == ""
    assert records[1]["document_root"] == "/srv/default"


def test_parse_apache_config_handles_case_and_missing_fields() -> None:
    records = _M._parse_apache_config(
        "<virtualhost 0.0.0.0:8081>servername lower.test</virtualhost>",
        "/etc/apache2/sites-enabled/lower.conf",
    )
    assert records[0]["server_name"] == "lower.test"
    assert records[0]["port"] == "8081"
    assert records[0]["document_root"] == ""


def test_parse_caddy_config_skips_nested_route_blocks() -> None:
    records = _M._parse_caddy_config(
        "\n".join(
            [
                "caddy.test {",
                "  route {",
                "    root * /ignored",
                "  }",
                "  root * /srv/caddy",
                "}",
            ]
        ),
        "/etc/caddy/Caddyfile",
    )
    assert len(records) == 1
    assert records[0]["server_name"] == "caddy.test"
    assert records[0]["document_root"] == "/srv/caddy"


def test_extract_port_and_caddy_name_helpers() -> None:
    assert _M._extract_port("[::]:8443 ssl") == "8443"
    assert _M._extract_port("*:80") == "80"
    assert _M._extract_port("example.test") == ""
    assert _M._caddy_server_name(":8080") == ""
    assert _M._caddy_server_name("https://example.test:443") == "example.test"


def test_clean_config_value_and_unclosed_block_paths() -> None:
    assert _M._clean_config_value("'quoted', # comment") == "quoted"
    assert _M._extract_brace_body("server { listen 80;", 7) is None
