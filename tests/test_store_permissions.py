from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

import wait_local_agent.platform_support as platform_support
import wait_local_agent.store as store_module
from wait_local_agent.store import Store


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits are not Windows permissions")
def test_store_database_is_private_and_missing_wal_siblings_are_allowed(tmp_path: Path) -> None:
    path = tmp_path / "state.db"

    Store(path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_store_warns_for_network_path(settings, monkeypatch, caplog) -> None:
    monkeypatch.setattr(platform_support, "is_network_path", lambda _path: True)
    with caplog.at_level(logging.WARNING, logger=store_module.LOGGER.name):
        Store(settings.data_path)

    assert "network path" in caplog.text
