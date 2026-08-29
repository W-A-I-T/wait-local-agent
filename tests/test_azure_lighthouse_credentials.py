from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from packs.azure_lighthouse.credentials import credential_from_vault
from packs.azure_lighthouse.models import AzureLighthouseCredentialError, AzureLighthouseError
from tests.azure_lighthouse_support import MANAGING_TENANT_ID, PRINCIPAL_ID, configured_settings
from wait_local_agent.vault import SecretVaultError


class FakeVault:
    def __init__(self, value: str | None = None, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.keys: list[str] = []

    def get(self, key: str) -> str | None:
        self.keys.append(key)
        if self.error is not None:
            raise self.error
        return self.value


def valid_secret(**overrides: object) -> str:
    payload: dict[str, object] = {
        "tenant_id": MANAGING_TENANT_ID,
        "client_id": PRINCIPAL_ID,
        "client_secret": "vault-secret-value",
    }
    payload.update(overrides)
    return json.dumps(payload)


def test_credential_from_vault_builds_client_secret_credential(settings, monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeClientSecretCredential:
        def __init__(self, *, tenant_id: str, client_id: str, client_secret: str) -> None:
            captured.update(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )

    monkeypatch.setattr(
        "packs.azure_lighthouse.credentials.import_module",
        lambda name: SimpleNamespace(ClientSecretCredential=FakeClientSecretCredential),
    )
    vault = FakeVault(valid_secret())
    credential = credential_from_vault(
        configured_settings(settings),
        "cloud/lighthouse",
        MANAGING_TENANT_ID,
        vault=vault,  # type: ignore[arg-type]
    )

    assert isinstance(credential, FakeClientSecretCredential)
    assert vault.keys == ["cloud/lighthouse"]
    assert captured == {
        "tenant_id": MANAGING_TENANT_ID,
        "client_id": PRINCIPAL_ID,
        "client_secret": "vault-secret-value",
    }


@pytest.mark.parametrize(
    ("reference", "vault", "tenant_id", "message"),
    [
        ("", FakeVault(valid_secret()), MANAGING_TENANT_ID, "reference is required"),
        ("x" * 257, FakeVault(valid_secret()), MANAGING_TENANT_ID, "reference is invalid"),
        ("bad\nref", FakeVault(valid_secret()), MANAGING_TENANT_ID, "reference is invalid"),
        ("missing", FakeVault(None), MANAGING_TENANT_ID, "was not found"),
        ("bad-json", FakeVault("{"), MANAGING_TENANT_ID, "not valid JSON"),
        ("not-object", FakeVault("[]"), MANAGING_TENANT_ID, "must be a JSON object"),
        ("extra", FakeVault(valid_secret(extra="value")), MANAGING_TENANT_ID, "unsupported fields"),
        ("missing-field", FakeVault(json.dumps({"tenant_id": MANAGING_TENANT_ID})), MANAGING_TENANT_ID, "incomplete"),
        ("wrong-tenant", FakeVault(valid_secret(tenant_id=PRINCIPAL_ID)), MANAGING_TENANT_ID, "does not match"),
        ("bad-client", FakeVault(valid_secret(client_id="not-a-guid")), MANAGING_TENANT_ID, "client ID"),
        ("bad-tenant", FakeVault(valid_secret()), "not-a-guid", "managing tenant"),
    ],
)
def test_credential_from_vault_rejects_invalid_secret_contracts(
    settings,
    reference: str,
    vault: FakeVault,
    tenant_id: str,
    message: str,
) -> None:
    with pytest.raises(AzureLighthouseError, match=message):
        credential_from_vault(
            configured_settings(settings),
            reference,
            tenant_id,
            vault=vault,  # type: ignore[arg-type]
        )


def test_credential_from_vault_sanitizes_vault_sdk_and_constructor_failures(settings, monkeypatch) -> None:
    with pytest.raises(AzureLighthouseCredentialError, match="could not be read") as exc:
        credential_from_vault(
            configured_settings(settings),
            "cloud/lighthouse",
            MANAGING_TENANT_ID,
            vault=FakeVault(error=SecretVaultError("vault-secret")),  # type: ignore[arg-type]
        )
    assert "vault-secret" not in str(exc.value)

    monkeypatch.setattr(
        "packs.azure_lighthouse.credentials.import_module",
        lambda name: (_ for _ in ()).throw(ImportError("sdk-secret")),
    )
    with pytest.raises(AzureLighthouseCredentialError, match="SDK is unavailable") as exc:
        credential_from_vault(
            configured_settings(settings),
            "cloud/lighthouse",
            MANAGING_TENANT_ID,
            vault=FakeVault(valid_secret()),  # type: ignore[arg-type]
        )
    assert "sdk-secret" not in str(exc.value)

    class FailingCredential:
        def __init__(self, **kwargs: object) -> None:
            raise RuntimeError("constructor-secret")

    monkeypatch.setattr(
        "packs.azure_lighthouse.credentials.import_module",
        lambda name: SimpleNamespace(ClientSecretCredential=FailingCredential),
    )
    with pytest.raises(AzureLighthouseCredentialError, match="could not be initialized") as exc:
        credential_from_vault(
            configured_settings(settings),
            "cloud/lighthouse",
            MANAGING_TENANT_ID,
            vault=FakeVault(valid_secret()),  # type: ignore[arg-type]
        )
    assert "constructor-secret" not in str(exc.value)
