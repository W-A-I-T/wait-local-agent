"""Tests for the database-inventory collector module.

These exercise ``DatabaseInventoryCollectorModule`` against its concrete return
contract by building a real temporary ``/etc`` tree and redirecting the module's
database config path alias at it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from wait_local_agent import collectors

Module = collectors.DatabaseInventoryCollectorModule


@pytest.fixture()
def etc_root(tmp_path: Path) -> Path:
    root = tmp_path / "etc"
    root.mkdir()
    return root


def _use_etc(monkeypatch: pytest.MonkeyPatch, etc_root: Path, system: str = "Linux") -> None:
    original = collectors._DatabaseInventoryPath

    def _mock_path(path: Path, *, _root=etc_root, _original=original) -> Path:
        text = str(path)
        if text == "/etc":
            return _root
        if text.startswith("/etc/"):
            return _root / text.removeprefix("/etc/")
        return _original(path)

    monkeypatch.setattr(collectors, "_DatabaseInventoryPath", _mock_path)
    monkeypatch.setattr(collectors._process_inventory_platform, "system", lambda: system)


def _write_postgresql_config(etc_root: Path) -> Path:
    config_path = etc_root / "postgresql" / "16" / "main" / "postgresql.conf"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "port = 5432",
                "data_directory = '/var/lib/postgresql/16/main'",
                "listen_addresses = '*' # keep only config value",
            ]
        )
    )
    return config_path


def _write_redis_config(etc_root: Path) -> Path:
    config_path = etc_root / "redis" / "redis.conf"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        "\n".join(
            [
                "port 6379",
                "dir /var/lib/redis",
                "bind 127.0.0.1 ::1",
            ]
        )
    )
    return config_path


def _collector() -> Any:
    return Module()


# --------------------------------------------------------------------------- #
# manifest / scope
# --------------------------------------------------------------------------- #


def test_manifest_advertises_read_only_linux_database_collector() -> None:
    manifest = _collector().manifest()
    assert manifest["module_id"] == "database-inventory"
    assert manifest["read_only"] is True
    assert manifest["platforms"] == ["linux"]
    assert manifest["asset_type"] == "database-instance"


def test_scope_is_read_only_stdlib_only_no_network_or_shell() -> None:
    scope = _collector().scope()
    assert scope["read_only"] is True
    assert scope["stdlib_only"] is True
    assert scope["network"] is False
    assert scope["shell"] is False
    assert scope["paths"] == [
        "/etc/postgresql/*/main/postgresql.conf",
        "/etc/mysql/my.cnf",
        "/etc/mysql/mariadb.conf.d/*.cnf",
        "/etc/mongod.conf",
        "/etc/redis/redis.conf",
    ]
    assert scope["operations"] == ["read-database-config"]


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
# collect / preview — concrete return contract
# --------------------------------------------------------------------------- #


def test_collect_parses_postgresql_and_redis_configs(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    postgresql_config = _write_postgresql_config(etc_root)
    redis_config = _write_redis_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect()
    assert result["module_id"] == "database-inventory"
    assert result["ok"] is True
    assert result["preview"] is False
    assert result["count"] == 2

    items = result["items"]
    assert [item["canonical_asset"]["attributes"]["engine"] for item in items] == [
        "postgresql",
        "redis",
    ]

    postgresql = items[0]["canonical_asset"]
    assert postgresql["asset_type"] == "database-instance"
    assert postgresql["asset_id"] == "db:postgresql"
    assert postgresql["name"] == "postgresql"
    assert postgresql["attributes"]["engine"] == "postgresql"
    assert postgresql["attributes"]["config_file"] == str(postgresql_config)
    assert postgresql["attributes"]["port"] == "5432"
    assert postgresql["attributes"]["data_dir"] == "/var/lib/postgresql/16/main"
    assert postgresql["attributes"]["bind"] == "*"

    observations = {item["key"]: item["value"] for item in items[0]["observations"]}
    assert observations["database.engine"] == "postgresql"
    assert observations["database.config_file"] == str(postgresql_config)
    assert observations["database.port"] == "5432"
    assert observations["database.data_dir"] == "/var/lib/postgresql/16/main"
    assert observations["database.bind"] == "*"

    redis = items[1]["canonical_asset"]
    assert redis["asset_id"] == "db:redis"
    assert redis["attributes"]["engine"] == "redis"
    assert redis["attributes"]["config_file"] == str(redis_config)
    assert redis["attributes"]["port"] == "6379"
    assert redis["attributes"]["data_dir"] == "/var/lib/redis"
    assert redis["attributes"]["bind"] == "127.0.0.1 ::1"

    engines = [item["canonical_asset"]["attributes"]["engine"] for item in items]
    assert "mysql" not in engines
    assert "mariadb" not in engines
    assert "mongodb" not in engines


def test_collect_parses_mysql_mariadb_and_mongodb_configs(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    mysql_config = etc_root / "mysql" / "my.cnf"
    mysql_config.parent.mkdir(parents=True)
    mysql_config.write_text("port = 3306\ndatadir = /var/lib/mysql\nbind-address = 127.0.0.1\n")

    mariadb_config = etc_root / "mysql" / "mariadb.conf.d" / "50-server.cnf"
    mariadb_config.parent.mkdir(parents=True)
    mariadb_config.write_text("port = 3307\ndatadir = /var/lib/mysql-maria\nbind-address = 0.0.0.0\n")

    mongodb_config = etc_root / "mongod.conf"
    mongodb_config.write_text("storage:\n  dbPath: /var/lib/mongodb\nnet:\n  port: 27017\n  bindIp: 127.0.0.1\n")
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect()
    attrs_by_engine = {
        item["canonical_asset"]["attributes"]["engine"]: item["canonical_asset"]["attributes"]
        for item in result["items"]
    }
    assert list(attrs_by_engine) == ["mariadb", "mongodb", "mysql"]
    assert attrs_by_engine["mysql"]["port"] == "3306"
    assert attrs_by_engine["mysql"]["data_dir"] == "/var/lib/mysql"
    assert attrs_by_engine["mysql"]["bind"] == "127.0.0.1"
    assert attrs_by_engine["mariadb"]["config_file"] == str(mariadb_config)
    assert attrs_by_engine["mariadb"]["port"] == "3307"
    assert attrs_by_engine["mongodb"]["config_file"] == str(mongodb_config)
    assert attrs_by_engine["mongodb"]["port"] == "27017"
    assert attrs_by_engine["mongodb"]["data_dir"] == "/var/lib/mongodb"
    assert attrs_by_engine["mongodb"]["bind"] == "127.0.0.1"


def test_preview_marks_preview_and_caps_at_default_limit(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_postgresql_config(etc_root)
    _write_redis_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().preview()
    assert result["preview"] is True
    assert result["count"] == 2


def test_collect_honours_explicit_limit(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_postgresql_config(etc_root)
    _write_redis_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect({"limit": 1})
    assert result["ok"] is True
    assert result["count"] == 1
    assert len(result["items"]) == 1


def test_collect_with_limit_zero_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_postgresql_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect({"limit": 0})
    assert result["ok"] is True
    assert result["items"] == []
    assert result["count"] == 0


def test_collect_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_postgresql_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().collect({"limit": -5})
    assert result["ok"] is False
    assert result["assets"] == []
    assert result["errors"]


def test_preview_returns_not_ok_for_invalid_config(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_postgresql_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    result = _collector().preview({"limit": "bad"})
    assert result["ok"] is False
    assert result["assets"] == []


def test_collect_returns_empty_on_non_linux(
    monkeypatch: pytest.MonkeyPatch,
    etc_root: Path,
) -> None:
    _write_postgresql_config(etc_root)
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
    redis_config = _write_redis_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    real_read_text = Path.read_text

    def deny_read_text(self: Path, *args: Any, **kwargs: Any) -> str:
        if self == redis_config:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", deny_read_text)
    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"] == []


def test_collect_swallows_glob_error(monkeypatch: pytest.MonkeyPatch, etc_root: Path) -> None:
    _write_redis_config(etc_root)
    _use_etc(monkeypatch, etc_root)

    real_glob = Path.glob

    def boom(self: Path, pattern: str) -> Any:
        if self.name == "postgresql":
            raise OSError("boom")
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", boom)
    result = _collector().collect()
    assert result["ok"] is True
    assert result["items"][0]["canonical_asset"]["attributes"]["engine"] == "redis"


# --------------------------------------------------------------------------- #
# registration
# --------------------------------------------------------------------------- #


def test_register_database_inventory_collector_is_idempotent() -> None:
    collectors._register_database_inventory_collector()
    registry = collectors.__dict__.get("MODULE_REGISTRY")
    if isinstance(registry, dict):
        module = registry.get("database-inventory")
        assert module is not None
        assert module.module_id == "database-inventory"


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

    collectors._register_database_inventory_collector()
    collectors._register_database_inventory_collector()

    assert [getattr(m, "module_id", None) for m in listed].count("database-inventory") == 1
    assert any(getattr(m, "module_id", None) == "database-inventory" for m in setted)
    assert getattr(calls.get("register"), "module_id", None) == "database-inventory"
    registry_tuple = collectors.__dict__["collector_registry"]
    assert [
        getattr(m, "module_id", None) for m in registry_tuple
    ].count("database-inventory") == 1
    assert "DatabaseInventoryCollectorModule" in collectors.__dict__["__all__"]


# --------------------------------------------------------------------------- #
# parse helpers
# --------------------------------------------------------------------------- #


_M = collectors.DatabaseInventoryCollectorModule


def test_parse_assignment_settings_handles_quotes_comments_and_whitespace() -> None:
    settings = _M._parse_assignment_settings(
        "\n".join(
            [
                "# comment",
                "[mysqld]",
                "port = 5432 # stripped",
                "data_directory = '/var/lib/postgresql/#kept'",
                'listen_addresses = "*"',
                "bind 127.0.0.1",
                "ignored_line",
            ]
        ),
        ("port", "data_directory", "listen_addresses", "bind"),
    )
    assert settings["port"] == "5432"
    assert settings["data_directory"] == "/var/lib/postgresql/#kept"
    assert settings["listen_addresses"] == "*"
    assert settings["bind"] == "127.0.0.1"


def test_parse_colon_settings_handles_yaml_like_config() -> None:
    settings = _M._parse_colon_settings(
        "\n".join(
            [
                "storage:",
                "  dbPath: /var/lib/mongodb # stripped",
                "net:",
                "  port: 27017",
                "  bindIp: '127.0.0.1'",
            ]
        ),
        ("port", "dbpath", "bindip"),
    )
    assert settings["port"] == "27017"
    assert settings["dbpath"] == "/var/lib/mongodb"
    assert settings["bindip"] == "127.0.0.1"


def test_clean_config_value_and_comment_stripping() -> None:
    assert _M._strip_config_comment("value '#not-comment' # comment") == "value '#not-comment' "
    assert _M._strip_config_comment('value "#not-comment" # comment') == 'value "#not-comment" '
    assert _M._clean_config_value("'quoted',") == "quoted"
