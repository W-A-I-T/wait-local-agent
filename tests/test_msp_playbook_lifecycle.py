from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app as cli_app
from wait_local_agent.msp_playbooks import (
    get_msp_playbook,
    msp_playbook_revision_diff,
    parse_msp_playbook_definition,
    playbook_view,
    preview_msp_playbook,
    publish_msp_playbook,
    update_msp_playbook,
)
from wait_local_agent.store import Store


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_msp_playbook_entry_lifecycle_is_tenant_scoped_and_versioned(settings) -> None:
    store = Store(settings.data_path)
    entry = publish_msp_playbook(
        store,
        "qbr-review",
        provenance="local fixture",
        client_id="acme",
    )

    assert entry.version == 1
    assert store.get_msp_playbook_entry(entry.id, "beta") is None
    assert [item.id for item in store.list_msp_playbook_entries("acme")] == [entry.id]
    assert store.list_msp_playbook_entries("beta") == []
    assert store.update_msp_playbook_entry(entry.id, client_id="acme") == entry
    assert store.get_msp_playbook_revision(entry.id, 99, "acme") is None
    with pytest.raises(KeyError):
        store.restore_msp_playbook_revision(entry.id, 99, "acme")
    with pytest.raises(ValueError, match="must not be empty"):
        store.update_msp_playbook_entry(entry.id, provenance="", client_id="acme")

    definition = {
        **json.loads(entry.definition_json),
        "description": "Edited local QBR definition",
    }
    updated = update_msp_playbook(
        store,
        entry.id,
        client_id="acme",
        definition=definition,
        enabled=False,
    )
    assert updated.version == 2
    assert updated.enabled is False
    assert len(store.list_msp_playbook_revisions(entry.id, "acme")) == 2

    revisions = store.list_msp_playbook_revisions(entry.id, "acme")
    diff = msp_playbook_revision_diff(revisions[1], revisions[0])
    assert diff["from_version"] == 1
    assert diff["to_version"] == 2
    assert "definition" in diff["changed_fields"]
    try:
        preview_msp_playbook(
            store,
            entry.id,
            client_id="acme",
            input_payload={"period_start": "2026-01-01", "period_end": "2026-01-31"},
        )
    except PermissionError as exc:
        assert str(exc) == "MSP playbook is disabled"
    else:  # pragma: no cover - assertion branch
        raise AssertionError("disabled playbook was executable")

    restored = store.restore_msp_playbook_revision(entry.id, 1, "acme")
    assert restored.version == 3
    assert restored.enabled is True
    assert preview_msp_playbook(
        store,
        entry.id,
        client_id="acme",
        input_payload={"period_start": "2026-01-01", "period_end": "2026-01-31"},
    )["execution_started"] is False


def test_msp_playbook_definition_rejects_unsupported_execution_surfaces() -> None:
    source = get_msp_playbook("qbr-review")
    assert source is not None
    definition = {
        "name": source.name,
        "trigger": source.trigger,
        "description": source.description,
        "risk_level": source.risk_level,
        "steps": [
            {
                "id": "unsafe",
                "name": "Unsafe",
                "kind": "shell",
                "description": "not supported",
            }
        ],
        "output_evidence": ["none"],
    }
    try:
        parse_msp_playbook_definition(definition, playbook_id="custom")
    except ValueError as exc:
        assert "workflow or report" in str(exc)
    else:  # pragma: no cover - assertion branch
        raise AssertionError("unsupported playbook step was accepted")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (None, "definition must be an object"),
        ({"name": "x", "trigger": "x", "description": "x", "risk_level": "unknown"}, "risk_level"),
        ({"name": "x", "trigger": "x", "description": "x", "risk_level": "low", "steps": []}, "steps"),
        (
            {
                "name": "x",
                "trigger": "x",
                "description": "x",
                "risk_level": "low",
                "steps": ["bad"],
            },
            "each playbook step",
        ),
        (
            {
                "name": "x",
                "trigger": "x",
                "description": "x",
                "risk_level": "low",
                "steps": [
                    {"id": "same", "name": "x", "kind": "report", "description": "x", "report_type": "qbr"},
                    {"id": "same", "name": "x", "kind": "report", "description": "x", "report_type": "qbr"},
                ],
            },
            "duplicate",
        ),
        (
            {
                "name": "x",
                "trigger": "x",
                "description": "x",
                "risk_level": "low",
                "steps": [
                    {
                        "id": "bad",
                        "name": "x",
                        "kind": "workflow",
                        "description": "x",
                        "workflow_template_id": "missing",
                    }
                ],
            },
            "unsupported workflow",
        ),
    ],
)
def test_msp_playbook_definition_validation_boundaries(payload, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_msp_playbook_definition(payload, playbook_id="custom")  # type: ignore[arg-type]


def test_msp_playbook_definition_rejects_duplicate_fields_and_bad_stored_json(tmp_path) -> None:
    source = get_msp_playbook("qbr-review")
    assert source is not None
    base = playbook_view(source)
    with pytest.raises(ValueError, match="output_evidence"):
        parse_msp_playbook_definition({**base, "output_evidence": []}, playbook_id="custom")
    with pytest.raises(ValueError, match="required_inputs"):
        parse_msp_playbook_definition(
            {
                **base,
                "steps": [
                    {
                        "id": "qbr",
                        "name": "QBR",
                        "kind": "report",
                        "description": "report",
                        "report_type": "qbr",
                        "required_inputs": ["period_start", "period_start"],
                    }
                ],
            },
            playbook_id="custom",
        )
    with pytest.raises(ValueError, match="non-empty string"):
        parse_msp_playbook_definition({**base, "name": ""}, playbook_id="custom")

    store = Store(tmp_path / "missing-msp-playbook-state.db")
    with pytest.raises(KeyError):
        update_msp_playbook(store, "missing")
    with pytest.raises(KeyError):
        store.update_msp_playbook_entry("missing")
    assert store.list_msp_playbook_entries() == []


def test_msp_playbook_entry_api_exposes_publish_disable_compare_restore(settings) -> None:
    secure_settings = settings.__class__(
        **{
            **settings.__dict__,
            "demo_mode": False,
            "admin_token": "admin-token",
            "tech_token": "tech-token",
            "viewer_token": "viewer-token",
            "client_id": "acme",
        }
    )
    client = TestClient(create_app(secure_settings))
    created = client.post(
        "/msp/playbook-entries",
        headers=_auth("tech-token"),
        json={"source_playbook_id": "qbr-review", "provenance": "fixture"},
    )
    assert created.status_code == 201
    entry_id = created.json()["id"]
    detail = client.get(f"/msp/playbook-entries/{entry_id}", headers=_auth("viewer-token"))
    assert detail.status_code == 200
    assert client.get("/msp/playbook-entries", headers=_auth("viewer-token")).status_code == 200
    patched = client.patch(
        f"/msp/playbook-entries/{entry_id}",
        headers=_auth("tech-token"),
        json={"provenance": "edited"},
    )
    assert patched.status_code == 200
    assert patched.json()["version"] == 2
    enabled = client.post(
        f"/msp/playbook-entries/{entry_id}/enable",
        headers=_auth("tech-token"),
    )
    assert enabled.status_code == 200
    assert enabled.json()["version"] == 3

    disabled = client.post(
        f"/msp/playbook-entries/{entry_id}/disable",
        headers=_auth("tech-token"),
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["version"] == 4
    preview = client.post(
        f"/msp/playbooks/{entry_id}/preview",
        headers=_auth("tech-token"),
        json={"client_id": "acme", "payload": {"period_start": "2026-01-01", "period_end": "2026-01-31"}},
    )
    assert preview.status_code == 409

    restored = client.post(
        f"/msp/playbook-entries/{entry_id}/revisions/1/restore",
        headers=_auth("tech-token"),
    )
    assert restored.status_code == 200
    assert restored.json()["enabled"] is True
    assert restored.json()["version"] == 5
    revisions = client.get(
        f"/msp/playbook-entries/{entry_id}/revisions",
        headers=_auth("viewer-token"),
    )
    assert revisions.status_code == 200
    assert [revision["version"] for revision in revisions.json()] == [5, 4, 3, 2, 1]
    diff = client.get(
        f"/msp/playbook-entries/{entry_id}/revisions/diff",
        params={"from_version": 1, "to_version": 2},
        headers=_auth("viewer-token"),
    )
    assert diff.status_code == 200
    assert "provenance" in diff.json()["changed_fields"]

    no_tenant_settings = secure_settings.__class__(
        **{**secure_settings.__dict__, "client_id": "", "tech_token": "no-tenant-tech"}
    )
    no_tenant_client = TestClient(create_app(no_tenant_settings))
    assert no_tenant_client.get("/msp/playbook-entries", headers=_auth("no-tenant-tech")).status_code == 403
    assert (
        no_tenant_client.get(f"/msp/playbook-entries/{entry_id}", headers=_auth("no-tenant-tech")).status_code
        == 403
    )
    assert (
        no_tenant_client.patch(
            f"/msp/playbook-entries/{entry_id}",
            headers=_auth("no-tenant-tech"),
            json={"enabled": True},
        ).status_code
        == 403
    )
    assert (
        no_tenant_client.get(
            f"/msp/playbook-entries/{entry_id}/revisions",
            headers=_auth("no-tenant-tech"),
        ).status_code
        == 403
    )
    assert (
        no_tenant_client.get(
            f"/msp/playbook-entries/{entry_id}/revisions/diff?from_version=1&to_version=2",
            headers=_auth("no-tenant-tech"),
        ).status_code
        == 403
    )
    assert (
        no_tenant_client.post(
            f"/msp/playbook-entries/{entry_id}/revisions/1/restore",
            headers=_auth("no-tenant-tech"),
        ).status_code
        == 403
    )

    missing = client.get("/msp/playbook-entries/missing", headers=_auth("viewer-token"))
    assert missing.status_code == 404
    missing_patch = client.patch(
        "/msp/playbook-entries/missing",
        headers=_auth("tech-token"),
        json={"enabled": True},
    )
    assert missing_patch.status_code == 404
    missing_revisions = client.get(
        "/msp/playbook-entries/missing/revisions", headers=_auth("viewer-token")
    )
    assert missing_revisions.status_code == 404
    missing_diff = client.get(
        "/msp/playbook-entries/missing/revisions/diff?from_version=1&to_version=2",
        headers=_auth("viewer-token"),
    )
    assert missing_diff.status_code == 404
    missing_restore = client.post(
        "/msp/playbook-entries/missing/revisions/1/restore", headers=_auth("tech-token")
    )
    assert missing_restore.status_code == 404
    unknown_source = client.post(
        "/msp/playbook-entries",
        headers=_auth("tech-token"),
        json={"source_playbook_id": "missing", "provenance": "fixture"},
    )
    assert unknown_source.status_code == 404
    invalid_definition = client.post(
        "/msp/playbook-entries",
        headers=_auth("tech-token"),
        json={
            "source_playbook_id": "qbr-review",
            "provenance": "fixture",
            "definition": {"name": "bad"},
        },
    )
    assert invalid_definition.status_code == 422
    invalid_patch = client.patch(
        f"/msp/playbook-entries/{entry_id}",
        headers=_auth("tech-token"),
        json={"definition": {"name": "bad"}},
    )
    assert invalid_patch.status_code == 422


def test_msp_playbook_entry_cli_exposes_publish_and_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    runner = CliRunner()
    published = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-entry-publish",
            "qbr-review",
            "fixture",
            "--client-id",
            "acme",
        ],
    )
    assert published.exit_code == 0, published.stdout
    entry_id = json.loads(published.stdout)["id"]
    listed = runner.invoke(cli_app, ["workflows", "playbook-entries", "--client-id", "acme"])
    revisions = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-revisions", entry_id, "--client-id", "acme"],
    )
    assert listed.exit_code == 0
    assert entry_id in listed.stdout
    assert revisions.exit_code == 0
    assert '"version": 1' in revisions.stdout
    disabled = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-update", entry_id, "--disabled", "--client-id", "acme"],
    )
    diff = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-diff", entry_id, "1", "2", "--client-id", "acme"],
    )
    restored = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-restore", entry_id, "1", "--client-id", "acme"],
    )
    assert disabled.exit_code == 0
    assert diff.exit_code == 0
    assert restored.exit_code == 0
    catalog = runner.invoke(cli_app, ["workflows", "playbooks"])
    preview = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-preview",
            "qbr-review",
            "--client-id",
            "acme",
            "--payload",
            '{"period_start":"2026-01-01","period_end":"2026-01-31"}',
        ],
    )
    missing = runner.invoke(cli_app, ["workflows", "playbook-entry-revisions", "missing"])
    assert catalog.exit_code == 0
    assert preview.exit_code == 0
    assert missing.exit_code != 0
    preview_missing = runner.invoke(cli_app, ["workflows", "playbook-preview", "missing"])
    preview_bad_payload = runner.invoke(
        cli_app,
        ["workflows", "playbook-preview", "qbr-review", "--client-id", "acme", "--payload", "[]"],
    )
    run_missing = runner.invoke(cli_app, ["workflows", "playbook-run", "missing"])
    run_bad_payload = runner.invoke(
        cli_app,
        ["workflows", "playbook-run", "qbr-review", "--client-id", "acme", "--payload", "[]"],
    )
    publish_bad = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-publish", "missing", "fixture"],
    )
    update_missing = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-update", "missing"],
    )
    diff_missing = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-diff", "missing", "1", "2"],
    )
    restore_missing = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-restore", "missing", "1"],
    )
    assert preview_missing.exit_code != 0
    assert preview_bad_payload.exit_code != 0
    assert run_missing.exit_code != 0
    assert run_bad_payload.exit_code != 0
    assert publish_bad.exit_code != 0
    assert update_missing.exit_code != 0
    assert diff_missing.exit_code != 0
    assert restore_missing.exit_code != 0
    disable_entry = runner.invoke(
        cli_app,
        ["workflows", "playbook-entry-update", entry_id, "--disabled", "--client-id", "acme"],
    )
    preview_disabled = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-preview",
            entry_id,
            "--client-id",
            "acme",
            "--payload",
            '{"period_start":"2026-01-01","period_end":"2026-01-31"}',
        ],
    )
    run_disabled = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-run",
            entry_id,
            "--client-id",
            "acme",
            "--payload",
            '{"period_start":"2026-01-01","period_end":"2026-01-31"}',
        ],
    )
    assert disable_entry.exit_code == 0
    assert preview_disabled.exit_code != 0
    assert run_disabled.exit_code != 0
    preview_lookup = runner.invoke(
        cli_app,
        ["workflows", "playbook-preview", "security-response-review", "--ticket-id", "missing", "--client-id", "acme"],
    )
    preview_value = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-preview",
            "qbr-review",
            "--payload",
            '{"period_start":"2026-01-01","period_end":"2026-01-31"}',
        ],
    )
    run_lookup = runner.invoke(
        cli_app,
        ["workflows", "playbook-run", "security-response-review", "--ticket-id", "missing", "--client-id", "acme"],
    )
    run_value = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-run",
            "qbr-review",
            "--payload",
            '{"period_start":"2026-01-01","period_end":"2026-01-31"}',
        ],
    )
    run_success = runner.invoke(
        cli_app,
        [
            "workflows",
            "playbook-run",
            "qbr-review",
            "--client-id",
            "acme",
            "--payload",
            '{"period_start":"2026-01-01","period_end":"2026-01-31"}',
        ],
    )
    assert preview_lookup.exit_code != 0
    assert preview_value.exit_code != 0
    assert run_lookup.exit_code != 0
    assert run_value.exit_code != 0
    assert run_success.exit_code == 0


def test_msp_playbook_private_bounds_and_missing_revision_paths(tmp_path) -> None:
    from wait_local_agent import msp_playbooks as module

    with pytest.raises(ValueError, match="at most 16"):
        module._bounded_string_list("not-a-list", "items")
    with pytest.raises(ValueError, match="duplicates"):
        module._bounded_string_list(["same", "same"], "items")
    with pytest.raises(ValueError, match="invalid"):
        module._json_object("not-json")
    with pytest.raises(ValueError, match="must be an object"):
        module._json_object("[]")
    store = Store(tmp_path / "missing-revision.db")
    assert store.get_msp_playbook_revision("missing", 1) is None
    assert store.list_msp_playbook_revisions("missing") == []


def test_msp_playbook_parser_covers_workflow_and_report_rejection(settings) -> None:
    store = Store(settings.data_path)
    workflow_entry = publish_msp_playbook(
        store,
        "ticket-intake-review",
        provenance="fixture",
        client_id="acme",
    )
    assert workflow_entry.source_playbook_id == "ticket-intake-review"
    with pytest.raises(ValueError, match="unsupported report type"):
        source = playbook_view(get_msp_playbook("qbr-review"))  # type: ignore[arg-type]
        source["steps"] = [
            {"id": "bad", "name": "bad", "kind": "report", "description": "bad", "report_type": "missing"}
        ]
        parse_msp_playbook_definition(source, playbook_id="bad")
    with pytest.raises(KeyError):
        publish_msp_playbook(store, "missing", provenance="fixture")
