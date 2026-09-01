from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from wait_local_agent.sessions import hash_session_token, session_expiries
from wait_local_agent.store import Store


def test_session_tokens_are_hashed_with_a_distinct_stdlib_helper() -> None:
    token = "session-secret"

    assert hash_session_token(token) != token
    assert hash_session_token(token) == hash_session_token(token)


@pytest.mark.parametrize("token", ["", None])
def test_hash_session_token_rejects_missing_tokens(token) -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        hash_session_token(token)


def test_session_expiries_reject_non_positive_ttls_and_normalize_naive_now() -> None:
    with pytest.raises(ValueError, match="TTLs must be positive"):
        session_expiries(idle_ttl_minutes=0)

    idle, absolute = session_expiries(
        now=datetime(2026, 1, 1, 12, 0), idle_ttl_minutes=5, absolute_ttl_minutes=10
    )

    assert idle == "2026-01-01T12:05:00+00:00"
    assert absolute == "2026-01-01T12:10:00+00:00"


def test_session_lifecycle_purges_expiry_and_supports_revocation(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_principal("operator", kind="staff")
    now = datetime.now(UTC)
    idle, absolute = session_expiries(now=now, idle_ttl_minutes=60, absolute_ttl_minutes=120)
    session_hash = hash_session_token("opaque-session")
    store.create_auth_session(
        session_hash,
        "operator",
        idle_expires_at=idle,
        absolute_expires_at=absolute,
        user_agent="test-agent",
    )

    live = store.get_auth_session(session_hash)
    assert live is not None
    assert live.principal_id == "operator"
    assert live.user_agent == "test-agent"
    assert live.session_token_hash == session_hash
    assert store.find_principal_auth_record("operator") is not None

    assert store.revoke_auth_session(session_hash) is True
    assert store.get_auth_session(session_hash) is None

    expired_hash = hash_session_token("expired-session")
    expired = (now - timedelta(minutes=1)).isoformat()
    store.create_auth_session(
        expired_hash,
        "operator",
        idle_expires_at=expired,
        absolute_expires_at=absolute,
    )
    assert store.get_auth_session(expired_hash) is None
    with sqlite3.connect(store.path) as connection:
        assert connection.execute(
            "select 1 from auth_sessions where session_token_hash = ?", (expired_hash,)
        ).fetchone() is None


def test_deactivation_revokes_all_principal_sessions(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    store.create_principal("operator", kind="staff")
    idle, absolute = session_expiries()
    hashes = [hash_session_token(f"session-{index}") for index in range(2)]
    for session_hash in hashes:
        store.create_auth_session(
            session_hash,
            "operator",
            idle_expires_at=idle,
            absolute_expires_at=absolute,
        )

    assert store.revoke_principal_sessions("operator") == 2
    assert all(store.get_auth_session(session_hash) is None for session_hash in hashes)
    store.set_principal_active("operator", False)
    assert store.find_principal_auth_record("operator") is None
