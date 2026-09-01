from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.api.packs.loader import PackInstallResult
from wait_local_agent.backup import BACKUP_KEY_SECRET_NAME
from wait_local_agent.models import RestoreExerciseWrite
from wait_local_agent.reports.hardening_checks import HardeningRunRecord
from wait_local_agent.reports.models import GeneratedReport
from wait_local_agent.store import Store
from wait_local_agent.vault import SecretVault


def test_sidecar_ops_routes_wrap_existing_logic(settings, tmp_path: Path) -> None:
    active_settings = settings.__class__(
        **{**settings.__dict__, "vault_path": tmp_path / "vault"}
    )
    client = TestClient(create_app(active_settings))

    packs = client.get("/packs")
    pack_status = client.get("/packs/status")
    update_check = client.post("/update-check")
    secret = client.post(
        "/secrets",
        json={"name": "WAIT_TEST_SECRET", "value": "value-must-not-echo"},
    )
    backup_path = tmp_path / "backup" / "state.db"
    backup = client.post("/backups", json={"destination": str(backup_path)})
    restore = client.post(
        "/backups/restore",
        json={"source": str(backup_path)},
    )

    assert packs.status_code == 200
    pack_entries = {entry["name"]: entry for entry in packs.json()}
    assert {"microsoft-admin", "automation-discovery"} <= pack_entries.keys()
    assert pack_entries["microsoft-admin"] == {
        "name": "microsoft-admin",
        "version": "0.1.0",
        "locked": False,
        "requires_license": False,
    }
    assert pack_status.status_code == 200
    status_entries = {entry["name"]: entry for entry in pack_status.json()}
    assert {"microsoft-admin", "automation-discovery"} <= status_entries.keys()
    assert status_entries["microsoft-admin"] == {
        "name": "microsoft-admin",
        "version": "0.1.0",
        "locked": False,
        "requires_license": False,
        "cli_available": True,
        "router_available": True,
        "mounted_cli": False,
        "mounted_router": True,
        "error": None,
    }
    assert update_check.status_code == 200
    assert update_check.json()["status"] == "unknown"
    assert update_check.json()["detail"] == "disabled"
    assert secret.status_code == 403
    assert backup.status_code == 200
    assert backup.json() == {"backup": str(backup_path), "encrypted": False}
    assert backup_path.exists()
    assert restore.status_code == 200
    assert restore.json() == {"restored": str(active_settings.data_path), "encrypted": False}
    assert active_settings.data_path.exists()


def test_sidecar_ops_routes_map_precondition_errors_to_4xx(settings, tmp_path: Path) -> None:
    active_settings = settings.__class__(
        **{**settings.__dict__, "vault_path": tmp_path / "vault"}
    )
    client = TestClient(create_app(active_settings))

    outside_backup = client.post(
        "/backups",
        json={"destination": str(tmp_path.parent / "outside-state.db")},
    )
    assert outside_backup.status_code == 400
    assert "appliance data directory" in outside_backup.json()["detail"]

    pack_install = client.post(
        "/packs/install",
        json={"tarball_path": str(tmp_path / "missing.tar.gz")},
    )
    encrypted_backup = client.post(
        "/backups",
        json={"destination": str(tmp_path / "state.db.enc"), "encrypt": True},
    )

    assert pack_install.status_code == 400
    assert "WAIT_PACK_SIGNING_SECRET" in pack_install.json()["detail"]
    assert encrypted_backup.status_code == 400
    assert "WAIT_SECRETS_BACKEND=fernet" in encrypted_backup.json()["detail"]


def test_validation_errors_do_not_echo_secret_inputs(settings, tmp_path: Path) -> None:
    active_settings = settings.__class__(
        **{
            **settings.__dict__,
            "vault_path": tmp_path / "vault",
            "demo_mode": False,
            "admin_token": "admin-token",
        }
    )
    client = TestClient(create_app(active_settings))
    headers = {"Authorization": "Bearer admin-token"}

    secret = client.post("/secrets", headers=headers, json={"value": "validation-secret"})
    pack = client.post(
        "/packs/install",
        headers=headers,
        json={"license_key": "validation-license"},
    )

    assert secret.status_code == 422
    assert pack.status_code == 422
    assert "validation-secret" not in secret.text
    assert "validation-license" not in pack.text


def test_sidecar_restore_maps_missing_source_to_404(settings, tmp_path: Path) -> None:
    client = TestClient(create_app(settings))

    response = client.post(
        "/backups/restore",
        json={"source": str(tmp_path / "missing.db")},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "backup source not found"


def test_pack_install_route_returns_safe_install_result(settings, tmp_path: Path, monkeypatch) -> None:
    result = PackInstallResult(
        pack_name="demo",
        version="2.0.0",
        extracted_files=(tmp_path / "packs" / "demo" / "__init__.py",),
        license_stored_in_vault=True,
    )
    monkeypatch.setattr(app_module, "install_pack_tarball", lambda *args, **kwargs: result)
    client = TestClient(create_app(settings))

    response = client.post(
        "/packs/install",
        json={"tarball_path": str(tmp_path / "demo.tar.gz"), "license_key": "secret-license"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "pack_name": "demo",
        "version": "2.0.0",
        "files": 1,
        "license_stored_in_vault": True,
    }
    assert "secret-license" not in response.text


def test_sidecar_write_routes_require_admin(settings, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WAIT_VAULT_KEY", Fernet.generate_key().decode("utf-8"))
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "vault_path": tmp_path / "vault",
        }
    )
    client = TestClient(create_app(secure_settings))

    write_requests = (
        ("/secrets", {"name": "WAIT_TEST_SECRET", "value": "value"}),
        ("/backups", {"destination": str(tmp_path / "backup.db")}),
        ("/packs/install", {"tarball_path": str(tmp_path / "pack.tar.gz")}),
    )
    for token in ("viewer-token", "tech-token"):
        for path, payload in write_requests:
            response = client.post(
                path,
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
            assert response.status_code == 403

    allowed = client.post(
        "/secrets",
        headers={"Authorization": "Bearer admin-token"},
        json={"name": "WAIT_TEST_SECRET", "value": "value"},
    )
    assert allowed.status_code == 200


def test_encrypted_backup_restore_route_uses_vault_key(settings, tmp_path: Path) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "secrets_backend": "fernet",
            "vault_path": tmp_path / "vault",
        }
    )
    SecretVault.initialize(secure_settings.vault_path).set(
        BACKUP_KEY_SECRET_NAME,
        "not-a-fernet-key",
    )
    Store(secure_settings.data_path)
    client = TestClient(create_app(secure_settings))

    response = client.post(
        "/backups",
        json={"destination": str(tmp_path / "state.db.enc"), "encrypt": True},
    )

    assert response.status_code == 400
    assert "not a valid Fernet key" in response.json()["detail"]


def test_hardening_and_restore_routes_cover_success_and_listing(
    settings, tmp_path: Path, monkeypatch
) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "viewer_token": "viewer-token",
        }
    )
    run = HardeningRunRecord(7, "completed", "start", "finish", 1, 1)
    exercise = RestoreExerciseWrite(
        exercise_id="exercise-1",
        status="passed",
        target="temporary scratch database",
        backup_artifact_id="backup.db",
        validation={"integrity_check": "ok"},
        evidence={"scratch_removed": True},
    )

    class FakeReportService:
        def __init__(self, _store) -> None:
            pass

        def create_report(self, report_type, title, sections, **kwargs):
            return GeneratedReport.new(
                report_type,
                title,
                sections,
                created_by=kwargs.get("created_by", ""),
                project_id=kwargs.get("project_id", ""),
                metadata=kwargs.get("metadata"),
            )

    monkeypatch.setattr(app_module, "run_hardening_checks", lambda *args, **kwargs: run)
    monkeypatch.setattr(app_module, "build_appliance_hardening_report", lambda *args: ([], {}))
    monkeypatch.setattr(app_module, "run_restore_exercise", lambda *args, **kwargs: exercise)
    monkeypatch.setattr(app_module, "build_restore_evidence_report", lambda *args: ([], {}))
    monkeypatch.setattr(app_module, "ReportService", FakeReportService)
    client = TestClient(create_app(secure_settings))

    hardening = client.post(
        "/hardening/runs",
        headers={"Authorization": "Bearer admin-token"},
        json={"backup_paths": [str(tmp_path / "backup.db")]},
    )
    hardening_list = client.get(
        "/hardening/runs", headers={"Authorization": "Bearer viewer-token"}
    )
    restore = client.post(
        "/backup/restore-exercises",
        headers={"Authorization": "Bearer admin-token"},
        json={"backup_id": "backup.db"},
    )
    restore_list = client.get(
        "/backup/restore-exercises", headers={"Authorization": "Bearer viewer-token"}
    )

    assert hardening.status_code == 200
    assert hardening.json()["run"]["id"] == 7
    assert hardening.json()["report"]["project_id"] == "hardening-run-7"
    assert hardening_list.status_code == 200
    assert hardening_list.json() == []
    assert restore.status_code == 200
    assert restore.json()["exercise"]["exercise_id"] == "exercise-1"
    assert restore.json()["report"]["project_id"] == "restore-exercise-exercise-1"
    assert restore_list.status_code == 200
    assert restore_list.json() == []
    client.close()


def test_hardening_and_restore_routes_map_errors_and_require_admin(settings, monkeypatch) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
        }
    )
    client = TestClient(create_app(secure_settings))

    for path, payload in (
        ("/hardening/runs", {}),
        ("/backup/restore-exercises", {"backup_id": "backup.db"}),
    ):
        response = client.post(path, headers={"Authorization": "Bearer viewer-token"}, json=payload)
        assert response.status_code == 403

    def raise_encryption(*args, **kwargs):
        raise app_module.BackupEncryptionError("bad encrypted backup")

    monkeypatch.setattr(app_module, "restore_state", raise_encryption)
    encrypted = client.post(
        "/backups/restore",
        headers={"Authorization": "Bearer admin-token"},
        json={"source": "backup.db", "encrypted": True},
    )
    assert encrypted.status_code == 400
    assert encrypted.json()["detail"] == "bad encrypted backup"

    monkeypatch.setattr(
        app_module,
        "restore_state",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read failed")),
    )
    os_error = client.post(
        "/backups/restore",
        headers={"Authorization": "Bearer admin-token"},
        json={"source": "backup.db"},
    )
    assert os_error.status_code == 400
    assert os_error.json()["detail"] == "backup source could not be restored"

    monkeypatch.setattr(
        app_module,
        "run_restore_exercise",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("cannot start")),
    )
    exercise_error = client.post(
        "/backup/restore-exercises",
        headers={"Authorization": "Bearer admin-token"},
        json={"backup_id": "backup.db"},
    )
    assert exercise_error.status_code == 400
    assert exercise_error.json()["detail"] == "restore exercise could not be started"

    monkeypatch.setattr(
        app_module,
        "run_hardening_checks",
        lambda *args, **kwargs: HardeningRunRecord(None, "completed", "start", "", 0, 0),
    )
    hardening_error = client.post(
        "/hardening/runs",
        headers={"Authorization": "Bearer admin-token"},
        json={},
    )
    assert hardening_error.status_code == 500
    assert hardening_error.json()["detail"] == "hardening run was not persisted"
    client.close()
