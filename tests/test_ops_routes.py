from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from wait_local_agent.api.app import create_app
from wait_local_agent.api.packs.loader import PackInstallResult
from wait_local_agent.backup import BACKUP_KEY_SECRET_NAME
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
    assert packs.json() == []
    assert pack_status.status_code == 200
    assert pack_status.json() == []
    assert update_check.status_code == 200
    assert update_check.json()["status"] == "unknown"
    assert update_check.json()["detail"] == "disabled"
    assert secret.status_code == 200
    assert secret.json() == {"name": "WAIT_TEST_SECRET", "status": "stored"}
    assert "value-must-not-echo" not in secret.text
    assert SecretVault(active_settings.vault_path).get("WAIT_TEST_SECRET") == "value-must-not-echo"
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
        **{**settings.__dict__, "vault_path": tmp_path / "vault"}
    )
    client = TestClient(create_app(active_settings))

    secret = client.post("/secrets", json={"value": "validation-secret"})
    pack = client.post(
        "/packs/install",
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


def test_sidecar_write_routes_require_admin(settings, tmp_path: Path) -> None:
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
