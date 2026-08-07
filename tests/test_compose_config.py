from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

COMPOSE_FILE = Path(__file__).parents[1] / "docker-compose.yml"


def _compose_config(*extra_args: str) -> dict[str, object]:
    try:
        docker = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), *extra_args, "config", "--format", "json"],
            cwd=COMPOSE_FILE.parent,
            env={key: value for key, value in os.environ.items() if key != "WAIT_DEMO_MODE"},
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        pytest.skip("Docker Compose is not installed")
    if docker.returncode != 0 and "not found" in docker.stderr.lower():
        pytest.skip("Docker Compose is not installed")
    assert docker.returncode == 0, docker.stderr
    return json.loads(docker.stdout)


def _expected_default_api_service() -> dict[str, object]:
    return {
        "build": {"context": str(COMPOSE_FILE.parent), "dockerfile": "Dockerfile"},
        "command": None,
        "entrypoint": None,
        "environment": {
            "WAIT_ALLOWED_DOC_ROOT": "/app/examples/sample_docs",
            "WAIT_DATA_PATH": "/data/state.db",
            "WAIT_DEMO_MODE": "true",
            "WAIT_SECRETS_BACKEND": "env",
            "WAIT_VAULT_PATH": "/data/vault",
        },
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8788/health', timeout=3)",
            ],
            "timeout": "5s",
            "interval": "10s",
            "retries": 5,
        },
        "networks": {"default": None},
        "ports": [{"mode": "ingress", "target": 8788, "published": "8788", "protocol": "tcp"}],
        "volumes": [
            {
                "type": "volume",
                "source": "wait-local-agent-data",
                "target": "/data",
                "volume": {},
            }
        ],
    }


def test_default_api_service_definition_is_unchanged() -> None:
    config = _compose_config()
    services = config["services"]
    assert isinstance(services, dict)
    assert services["api"] == _expected_default_api_service()
    assert "api-host-collect" not in services


def test_host_collection_service_has_no_default_port_reset_dependency() -> None:
    config = _compose_config("--profile", "host-collect")
    services = config["services"]
    assert isinstance(services, dict)
    assert services["api"] == _expected_default_api_service()
    host_service = services["api-host-collect"]
    assert isinstance(host_service, dict)
    assert "ports" not in host_service
    assert host_service["network_mode"] == "host"
