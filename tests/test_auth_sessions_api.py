from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from wait_local_agent.api.app import create_app
from wait_local_agent.sessions import SESSION_COOKIE_NAME, hash_session_token, session_expiries
from wait_local_agent.store import Store


def _secured_settings(settings):
    return replace(
        settings,
        demo_mode=False,
        session_cookie_secure=False,
        admin_token="bootstrap-admin",
        client_id="client-a",
    )


def test_local_login_uses_hashed_cookie_session_and_logout_revokes_it(settings) -> None:
    secured = _secured_settings(settings)
    store = Store(secured.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_credential("operator", "operator-secret")
    store.add_principal_client_role("operator", "client-a", "admin")
    client = TestClient(create_app(secured))

    login = client.post("/auth/login/local", json={"token": "operator-secret"})

    assert login.status_code == 200
    assert login.json()["session_created"] is True
    assert "operator-secret" not in login.text
    set_cookie = login.headers["set-cookie"]
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie
    assert "Path=/" in set_cookie
    cookie_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert cookie_token is not None
    assert store.get_auth_session(hash_session_token(cookie_token)) is not None

    role = client.get("/auth/role")
    assert role.status_code == 200
    assert role.json()["principal_id"] == "operator"
    assert role.json()["auth_method"] == "local"

    csrf_failure = client.post("/auth/logout")
    assert csrf_failure.status_code == 403
    assert csrf_failure.json()["detail"]["code"] == "csrf_required"
    logout = client.post("/auth/logout", headers={"X-WAIT-CSRF": "1"})
    assert logout.status_code == 200
    assert store.get_auth_session(hash_session_token(cookie_token)) is None
    assert client.get("/auth/role").status_code == 401


def test_bootstrap_login_stays_bearer_only_and_bearer_wins_over_cookie(settings) -> None:
    secured = _secured_settings(settings)
    store = Store(secured.data_path)
    store.create_principal("viewer", kind="staff")
    store.add_principal_credential("viewer", "viewer-secret")
    store.add_principal_client_role("viewer", "client-a", "viewer")
    client = TestClient(create_app(secured))

    bootstrap = client.post("/auth/login/local", json={"token": "bootstrap-admin"})
    assert bootstrap.status_code == 200
    assert bootstrap.json() == {"session_created": False}
    assert SESSION_COOKIE_NAME not in client.cookies

    login = client.post("/auth/login/local", json={"token": "viewer-secret"})
    assert login.status_code == 200
    assert login.json()["session_created"] is True
    bearer_role = client.get("/auth/role", headers={"Authorization": "Bearer bootstrap-admin"})
    assert bearer_role.status_code == 200
    assert bearer_role.json()["role"] == "admin"
    assert bearer_role.json()["auth_method"] == "bearer"


def test_session_probe_never_returns_401(settings) -> None:
    secured = _secured_settings(settings)
    client = TestClient(create_app(secured))

    assert client.get("/auth/session").json() == {"authenticated": False}
    assert client.get("/auth/session", headers={"Authorization": "Bearer invalid"}).json() == {
        "authenticated": False
    }


def test_session_probe_returns_authenticated_session_expiry(settings) -> None:
    secured = _secured_settings(settings)
    store = Store(secured.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_client_role("operator", "client-a", "admin")
    raw_token = "probe-session"
    idle, absolute = session_expiries()
    store.create_auth_session(
        hash_session_token(raw_token),
        "operator",
        idle_expires_at=idle,
        absolute_expires_at=absolute,
    )
    client = TestClient(create_app(secured))
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.get("/auth/session")

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["principal_id"] == "operator"
    assert response.json()["expires_at"] == absolute


def test_local_login_rejects_invalid_credentials(settings) -> None:
    client = TestClient(create_app(_secured_settings(settings)))

    response = client.post("/auth/login/local", json={"token": "not-valid"})

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


def test_logout_clears_an_invalid_cookie_without_requiring_csrf(settings) -> None:
    client = TestClient(create_app(_secured_settings(settings)))
    client.cookies.set(SESSION_COOKIE_NAME, "no-longer-valid")

    response = client.post("/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    set_cookie = response.headers.get("set-cookie", "")
    assert f"{SESSION_COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie.lower()


def test_bearer_logout_revokes_cookie_session(settings) -> None:
    secured = _secured_settings(settings)
    store = Store(secured.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_client_role("operator", "client-a", "admin")
    raw_token = "bearer-logout-session"
    idle, absolute = session_expiries()
    session_hash = hash_session_token(raw_token)
    store.create_auth_session(
        session_hash,
        "operator",
        idle_expires_at=idle,
        absolute_expires_at=absolute,
    )
    client = TestClient(create_app(secured))
    client.cookies.set(SESSION_COOKIE_NAME, raw_token)

    response = client.post("/auth/logout", headers={"Authorization": "Bearer bootstrap-admin"})

    assert response.status_code == 200
    assert store.get_auth_session(session_hash) is None


def test_deactivating_principal_revokes_its_sessions(settings) -> None:
    secured = _secured_settings(settings)
    store = Store(secured.data_path)
    store.create_principal("operator", kind="staff")
    store.add_principal_client_role("operator", "client-a", "admin")
    raw_token = "deactivation-session"
    idle, absolute = session_expiries()
    session_hash = hash_session_token(raw_token)
    store.create_auth_session(
        session_hash,
        "operator",
        idle_expires_at=idle,
        absolute_expires_at=absolute,
    )
    client = TestClient(create_app(secured))

    response = client.patch(
        "/auth/principals/operator",
        headers={"Authorization": "Bearer bootstrap-admin"},
        json={"active": False},
    )

    assert response.status_code == 200
    assert response.json()["active"] is False
    assert store.get_auth_session(session_hash) is None
