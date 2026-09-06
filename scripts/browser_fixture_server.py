"""Serve the real compiled UI/API with disposable, offline acceptance fixtures.

Never used by the appliance entrypoint. All WAIT configuration is replaced in
this child process; it binds loopback and removes its database on shutdown.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import httpx
import uvicorn
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request

from wait_local_agent.api import founder
from wait_local_agent.api.app import create_app
from wait_local_agent.config import load_settings
from wait_local_agent.lp_client import LaunchPassportClient
from wait_local_agent.store import Store

ADMIN_TOKEN = "acceptance-admin-token"
END_USER_TOKEN = "acceptance-requester-token"


def serve(port: int, ui_dist: Path) -> None:
    if not (ui_dist / "index.html").is_file():
        raise SystemExit("Build the UI before running browser acceptance.")
    with tempfile.TemporaryDirectory(prefix="wait-browser-acceptance-") as temporary:
        root = Path(temporary)
        for key in list(os.environ):
            if key.startswith("WAIT_"):
                del os.environ[key]
        os.environ.update({
            "WAIT_DATA_PATH": str(root / "state.db"),
            "WAIT_UI_DIST": str(ui_dist.resolve()),
            "WAIT_ALLOWED_DOC_ROOT": str(root),
            "WAIT_ADMIN_TOKEN": ADMIN_TOKEN,
            "WAIT_END_USER_TOKEN": END_USER_TOKEN,
            "WAIT_END_USER_SUPPORT_ENABLED": "true",
            "WAIT_END_USER_CLIENT_ID": "acceptance-alpha",
            "WAIT_END_USER_USER_ID": "acceptance-requester",
            "WAIT_SECRETS_BACKEND": "fernet",
            "WAIT_VAULT_PATH": str(root / "vault"),
            "WAIT_VAULT_KEY": Fernet.generate_key().decode(),
            "WAIT_SESSION_COOKIE_SECURE": "false",
            "WAIT_RATE_LIMIT_ENABLED": "false",
            "WAIT_POWER_PLATFORM_WORKSPACE": str(root / "delivery"),
        })
        (root / "delivery").mkdir()
        project = root / "project"
        project.mkdir()
        (project / "package.json").write_text('{"name":"acceptance-project","dependencies":{"react":"19"}}')
        (project / "private.ts").write_text("// acceptance-private-source-must-stay-local")
        (project / ".env.example").write_text("EXAMPLE_API_KEY=acceptance-private-env-value\n")
        (project / ".gitignore").write_text("ignored/\n")
        (project / "ignored").mkdir()
        (project / "ignored" / "private.txt").write_text("acceptance-ignored-source")
        (project / "broken").mkdir()
        (project / "broken" / "package.json").write_text("{ malformed manifest")

        settings = load_settings()
        assert not settings.demo_mode
        assert not settings.allow_write_actions
        assert not settings.allow_http_probing
        store = Store(settings.data_path)
        store.create_client("acceptance-alpha", "Client Alpha")
        store.create_client("acceptance-beta", "Client Beta")
        other = store.create_end_user_ticket(
            client_id="acceptance-alpha", requester_id="another-requester",
            subject="Other requester's private ticket", body="Another requester's private details",
        )
        beta = store.create_end_user_ticket(
            client_id="acceptance-beta", requester_id="acceptance-requester",
            subject="Client Beta private ticket", body="Client Beta private details",
        )
        founder.configure_founder(
            settings, store, "https://launch-passport.invalid", "acceptance-project", "fixture-lp-token",
        )
        uploads: list[dict[str, object]] = []

        def provider(request: httpx.Request) -> httpx.Response:
            if request.method == "POST" and request.url.path.endswith("collector-bundle"):
                wire = request.content.decode()
                assert "acceptance-private-source-must-stay-local" not in wire
                assert "acceptance-private-env-value" not in wire
                assert "acceptance-ignored-source" not in wire
                assert "fixture-lp-token" not in wire
                uploads.append(json.loads(wire))
                if len(uploads) == 1:
                    return httpx.Response(503, json={"error": "Fixture connection unavailable"})
                return httpx.Response(200, json={"artifact_id": "fixture-remote-artifact", "status": "uploaded"})
            if request.url.path == "/api/health":
                return httpx.Response(200, json={"capabilities": {"launch_scan": False}})
            return httpx.Response(200, json=[])

        # Only the external transport is a fixture. Scan, privacy projection,
        # review, upload approval, storage and audit use the shipped services.
        founder._open_client = lambda _settings, _config: LaunchPassportClient(
            "https://launch-passport.invalid", lambda: "fixture-lp-token", transport=httpx.MockTransport(provider),
        )
        app = create_app(settings)

        @app.get("/__acceptance/fixtures")
        def fixtures(request: Request) -> dict[str, object]:
            if request.headers.get("Authorization") != f"Bearer {ADMIN_TOKEN}":
                raise HTTPException(status_code=403)
            return {
                "project": str(project), "delivery": str(root / "delivery"),
                "other_ticket": other.ticket_id, "beta_ticket": beta.ticket_id,
                "uploads": len(uploads),
            }

        # Insert the fixture metadata route before the SPA catch-all mount.
        app.router.routes.insert(0, app.router.routes.pop())
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18790)
    parser.add_argument("--ui-dist", type=Path, default=Path(__file__).resolve().parents[1] / "ui" / "dist")
    arguments = parser.parse_args()
    serve(arguments.port, arguments.ui_dist)
