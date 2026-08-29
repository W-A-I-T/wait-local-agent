from __future__ import annotations

from dataclasses import replace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from wait_local_agent.capabilities import MICROSOFT_ADMIN_CAPABILITY, grant_capability
from wait_local_agent.rbac import require_capability
from wait_local_agent.store import Store


def _app(settings, store: Store) -> FastAPI:
    app = FastAPI()
    app.state.settings = settings
    app.state.store = store

    @app.get("/protected", dependencies=[Depends(require_capability(MICROSOFT_ADMIN_CAPABILITY))])
    def protected() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_selected_client_header_is_validated_as_scope_not_authority(settings) -> None:
    configured = replace(settings, demo_mode=False)
    store = Store(configured.data_path)
    store.create_client("alpha", "Alpha")
    store.create_client("beta", "Beta")
    store.create_principal("viewer-ab", kind="staff", display_name="Viewer AB")
    store.add_principal_credential("viewer-ab", "viewer-secret")
    store.add_principal_client_role("viewer-ab", "alpha", "viewer")
    store.add_principal_client_role("viewer-ab", "beta", "viewer")
    grant_capability(
        store,
        principal_id="viewer-ab",
        capability_key=MICROSOFT_ADMIN_CAPABILITY,
        client_id="beta",
        actor_id="bootstrap",
    )
    client = TestClient(_app(configured, store))
    auth = {"Authorization": "Bearer viewer-secret"}

    beta = client.get("/protected", headers={**auth, "X-WAIT-Client-ID": "beta"})
    alpha = client.get("/protected", headers={**auth, "X-WAIT-Client-ID": "alpha"})
    conflict = client.get(
        "/protected?client_id=alpha",
        headers={**auth, "X-WAIT-Client-ID": "beta"},
    )

    assert beta.status_code == 200
    assert alpha.status_code == 403
    assert conflict.status_code == 400
    assert conflict.json()["detail"] == "conflicting Microsoft Admin client scopes"
