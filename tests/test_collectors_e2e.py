from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from wait_local_agent.api.app import create_app
from wait_local_agent.cli import app
from wait_local_agent.collectors import default_registry

_REGISTERED_MODULES = tuple(default_registry.list())


def _module_ids() -> list[str]:
    return [module.manifest.id for module in _REGISTERED_MODULES]


def _round_trip_config(module) -> dict[str, object]:
    if module.manifest.id == "host-runtime":
        return {}
    if module.manifest.id.startswith("cloud-"):
        config: dict[str, object] = {"credential_ref": "missing-cloud-test", "limit": 0}
        if module.manifest.id == "cloud-azure":
            config["subscription_id"] = "subscription-test"
        return config
    return {"limit": 0}


def test_default_registry_has_fourteen_modules() -> None:
    assert len(_REGISTERED_MODULES) == 14
    assert _module_ids() == [module.manifest.id for module in default_registry.list()]


@pytest.mark.parametrize(
    "module",
    _REGISTERED_MODULES,
    ids=lambda module: module.manifest.id,
)
def test_each_registered_module_round_trips_through_api(
    settings,
    isolated_default_registry,
    module,
) -> None:
    client = TestClient(create_app(settings))
    module_id = module.manifest.id
    config = _round_trip_config(module)

    listed = client.get("/collectors/modules")
    validate = client.post(f"/collectors/modules/{module_id}/validate", json={"config": config})
    preview = client.post(f"/collectors/modules/{module_id}/preview", json={"config": config})
    run = client.post(
        f"/collectors/modules/{module_id}/run",
        json={"confirm": True, "config": config},
    )
    run_id = run.json()["id"]
    export = client.post(f"/collectors/runs/{run_id}/export")

    assert listed.status_code == 200
    assert module_id in {item["id"] for item in listed.json()}
    assert validate.status_code == 200
    assert validate.json()["passed"] is True
    assert preview.status_code == 200
    assert preview.json()["module_id"] == module_id
    assert run.status_code == 200
    assert run.json()["module_id"] == module_id
    assert export.status_code == 200
    assert export.json()["report_type"] == "collector_bundle"


@pytest.mark.parametrize(
    "module",
    _REGISTERED_MODULES,
    ids=lambda module: module.manifest.id,
)
def test_each_registered_module_round_trips_through_cli(
    monkeypatch,
    tmp_path,
    isolated_default_registry,
    module,
) -> None:
    monkeypatch.setenv("WAIT_DATA_PATH", str(tmp_path / "state.db"))
    config_path = tmp_path / "collector-config.json"
    output_path = tmp_path / "collector-bundle.json"
    runner = CliRunner()
    module_id = module.manifest.id
    config = _round_trip_config(module)

    listed = runner.invoke(app, ["collectors", "list"])
    config_path.write_text(json.dumps(config), encoding="utf-8")
    validate = runner.invoke(app, ["collectors", "validate", module_id, "--config", str(config_path)])
    preview = runner.invoke(app, ["collectors", "preview", module_id, "--config", str(config_path)])
    run = runner.invoke(
        app,
        ["collectors", "run", module_id, "--config", str(config_path), "--confirm"],
    )
    run_match = re.search(r"run_id=(\d+)", run.output)
    assert run_match is not None
    run_id = int(run_match.group(1))
    export = runner.invoke(
        app,
        ["collectors", "bundle", "export", str(run_id), "--output", str(output_path)],
    )

    assert listed.exit_code == 0
    assert module_id in listed.output
    assert validate.exit_code == 0
    assert json.loads(validate.output)["passed"] is True
    assert preview.exit_code == 0
    assert json.loads(preview.output)["module_id"] == module_id
    assert run.exit_code == 0
    assert f"module={module_id}" in run.output
    assert export.exit_code == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["report_type"] == "collector_bundle"
