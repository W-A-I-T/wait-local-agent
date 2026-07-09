from __future__ import annotations

from typer.testing import CliRunner

import wait_local_agent.cli as cli_module
from wait_local_agent.api.packs.loader import PackInstallError, PackInstallResult, PackRegistry, PackStatus


def test_packs_list_is_empty_when_no_packs_are_discovered(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    cli_module.sync_pack_cli([])
    runner = CliRunner()

    result = runner.invoke(cli_module.app, ["packs", "list"])

    assert result.exit_code == 0
    assert "no packs discovered" in result.output


def test_packs_commands_and_doctor_report_discovered_packs(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(cli_module, "sync_pack_cli", lambda *args, **kwargs: None)
    registry = PackRegistry(
        statuses=[
            PackStatus(
                name="demo",
                version="1.0.0",
                locked=False,
                requires_license=False,
                cli_available=True,
                router_available=True,
            ),
            PackStatus(
                name="licensed",
                version="2.0.0",
                locked=True,
                requires_license=True,
                cli_available=True,
                router_available=False,
            ),
        ]
    )
    monkeypatch.setattr(cli_module, "load_pack_registry", lambda _settings: registry)
    runner = CliRunner()

    doctor = runner.invoke(cli_module.app, ["doctor"])
    listing = runner.invoke(cli_module.app, ["packs", "list"])
    status = runner.invoke(cli_module.app, ["packs", "status"])

    assert doctor.exit_code == 0
    assert "packs_discovered=2" in doctor.output
    assert listing.exit_code == 0
    assert "demo 1.0.0 unlocked" in listing.output
    assert "licensed 2.0.0 locked" in listing.output
    assert status.exit_code == 0
    assert "demo version=1.0.0 state=unlocked router=True cli=True" in status.output


def test_packs_install_command_reports_success_and_failure(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    monkeypatch.setattr(
        cli_module,
        "install_pack_tarball",
        lambda *_args, **_kwargs: PackInstallResult(
            pack_name="demo",
            version="1.0.0",
            extracted_files=(tmp_path / "packs" / "demo" / "__init__.py",),
            license_stored_in_vault=False,
        ),
    )
    runner = CliRunner()

    success = runner.invoke(cli_module.app, ["packs", "install", "bundle.tar.gz", "--license", "abc"])

    assert success.exit_code == 0
    assert "installed=demo version=1.0.0 files=1 license_stored_in_vault=False" in success.output
    assert "set WAIT_LICENSE_KEY in the environment" in success.output

    def fail(*_args, **_kwargs):
        raise PackInstallError("bad tarball")

    monkeypatch.setattr(cli_module, "install_pack_tarball", fail)
    failure = runner.invoke(cli_module.app, ["packs", "install", "bundle.tar.gz"])

    assert failure.exit_code != 0
    assert "bad tarball" in failure.output
