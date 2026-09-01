from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

COMPOSE_FILE = Path(__file__).parents[1] / "docker-compose.yml"
PROD_COMPOSE_FILE = Path(__file__).parents[1] / "docker-compose.prod.yml"
HEALTHCHECK_COMMAND = (
    "import urllib.request; "
    "urllib.request.urlopen('http://127.0.0.1:8788/healthz', timeout=3)"
)


def _compose_config(*extra_args: str, compose_file: Path = COMPOSE_FILE) -> dict[str, object]:
    try:
        docker = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), *extra_args, "config", "--format", "json"],
            cwd=compose_file.parent,
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
        "entrypoint": None,
        "environment": {
            "WAIT_ALLOWED_DOC_ROOT": "/app/examples/sample_docs",
            "WAIT_DATA_PATH": "/data/state.db",
            "WAIT_DEMO_MODE": "false",
            "WAIT_ADMIN_TOKEN": "",
            "WAIT_API_TOKEN": "",
            "WAIT_CLIENT_ID": "",
            "WAIT_SECRETS_BACKEND": "env",
            "WAIT_VAULT_KEY": "",
            "WAIT_TRUSTED_HOSTS": "127.0.0.1,localhost,api",
            "WAIT_VAULT_PATH": "/data/vault",
        },
        "healthcheck": {
            "test": [
                "CMD",
                "python",
                "-c",
                HEALTHCHECK_COMMAND,
            ],
            "timeout": "5s",
            "interval": "10s",
            "retries": 5,
        },
        "networks": {"default": None},
        "ports": [
            {
                "mode": "ingress",
                "host_ip": "127.0.0.1",
                "target": 8788,
                "published": "8788",
                "protocol": "tcp",
            }
        ],
        "command": ["wait-local-agent", "serve", "--host", "0.0.0.0", "--port", "8788"],
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


def test_production_compose_is_pull_based_and_single_service() -> None:
    config = _compose_config(compose_file=PROD_COMPOSE_FILE)
    services = config["services"]
    assert isinstance(services, dict)
    assert list(services) == ["api"]

    api = services["api"]
    assert isinstance(api, dict)
    assert api["image"] == "ghcr.io/w-a-i-t/wait-local-agent:stable"
    assert "build" not in api
    assert api["restart"] == "unless-stopped"
    assert api["healthcheck"]["test"] == ["CMD", "python", "-c", HEALTHCHECK_COMMAND]
    assert "WAIT_ADMIN_TOKEN" in api["environment"]
    assert "WAIT_VAULT_KEY" in api["environment"]
    assert all(volume["type"] == "volume" for volume in api["volumes"])
    assert api["ports"][0]["host_ip"] == "127.0.0.1"
