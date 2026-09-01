from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest

from wait_local_agent.client_discovery import (
    ClientDiscoveryError,
    _domains,
    _list_page,
    _response_items,
    assert_bulk_accept_allowed,
    discover_instance,
    match_candidate,
    normalize_client_name,
)
from wait_local_agent.client_scope import AllClients
from wait_local_agent.config import Settings
from wait_local_agent.connector_factory import ConnectorFactoryError
from wait_local_agent.models import ClientCandidate, utc_now
from wait_local_agent.store import Store


def _candidate(instance_id: str, external_id: str, name: str, state: str = "unmatched") -> ClientCandidate:
    now = utc_now()
    return ClientCandidate(
        candidate_id=f"candidate-{external_id}",
        connector_instance_id=instance_id,
        provider="connectwise",
        external_id=external_id,
        display_name=name,
        domains_json="[]",
        provenance="connectwise:test",
        first_seen=now,
        last_seen=now,
        match_state=state,
        matched_client_id=None,
        match_reason="",
        confidence=0.0,
    )


def test_normalization_is_exact_and_removes_only_supported_legal_suffixes() -> None:
    assert normalize_client_name(" ACME, Ltd. ") == "acme"
    assert normalize_client_name("Acme Inc") == "acme"
    assert normalize_client_name("Acme Incorporated") == "acme incorporated"


def test_provider_payload_helpers_normalize_attributes_domains_and_statuses() -> None:
    item = SimpleNamespace(id="42", domains=[" acme.test ", "", 123])
    assert _domains(item) == ["acme.test", "123"]
    assert _domains({"domain": " acme.test "}) == ["acme.test"]
    assert _domains({"domains": "   "}) == []
    assert _domains({"domains": {"not": "a list"}}) == []

    response = SimpleNamespace(items=[item], result=SimpleNamespace(status="SUCCESS"))
    assert _response_items(response) == ([item], "success")
    with pytest.raises(ClientDiscoveryError, match="invalid organization list"):
        _response_items(SimpleNamespace(items=None, result=SimpleNamespace(status="ready")))


@pytest.mark.parametrize(
    ("provider", "method"),
    [
        ("halopsa", "list_clients"),
        ("syncro", "list_customers"),
        ("servicenow", "list_companies"),
    ],
)
def test_list_page_dispatches_provider_specific_client_methods(provider: str, method: str) -> None:
    calls: list[tuple[str, dict[str, int]]] = []

    class FakeClient:
        def __getattr__(self, name: str):
            def list_page(**kwargs: int) -> list[object]:
                calls.append((name, kwargs))
                return []

            return list_page

    assert _list_page(FakeClient(), provider, 3) == ([], "ready")
    assert calls == [(method, {"page": 3, **({"page_size": 100} if provider != "syncro" else {})})]


def test_matching_ladder_proposes_one_exact_name_and_marks_duplicates_ambiguous(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("existing", "Existing Client")
    store.create_client("acme", "Acme Ltd")
    candidate = _candidate(instance.connector_instance_id, "1", "ACME Ltd")
    proposed = match_candidate(store, candidate)
    assert proposed.state == "proposed"
    assert proposed.client_id == "acme"
    store.create_client("acme-2", "Acme GmbH")
    ambiguous = match_candidate(store, candidate)
    assert ambiguous.state == "ambiguous"
    assert ambiguous.client_id is None


def test_matching_ladder_prefers_verified_mapping_over_contradictory_candidate_and_empty_names_unmatched(
    tmp_path,
) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("one", "One Client")
    store.create_client("two", "Two Client")
    first = store.create_client_connector_mapping(AllClients(), instance.connector_instance_id, "shared", "one")
    store.verify_client_connector_mapping(AllClients(), first.mapping_id)

    contradictory = replace(
        _candidate(instance.connector_instance_id, "shared", "One Client"),
        match_state="verified",
        matched_client_id="two",
    )
    verified = match_candidate(store, contradictory)
    assert verified.state == "verified"
    assert verified.client_id == "one"
    empty = match_candidate(store, _candidate(instance.connector_instance_id, "empty", "---"))
    assert empty.state == "unmatched"
    assert "no comparable" in empty.reason


def test_unknown_candidate_is_unmatched_and_verified_state_is_immutable(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("existing", "Existing Client")
    candidate = _candidate(instance.connector_instance_id, "1", "Unknown")
    store.upsert_client_candidate(candidate)
    verified = replace(candidate, match_state="verified", matched_client_id="existing", confidence=1.0)
    store.upsert_client_candidate(verified, preserve_state=False)
    refreshed = store.upsert_client_candidate(replace(candidate, last_seen=utc_now(), match_reason="new suggestion"))
    assert refreshed.match_state == "verified"
    assert refreshed.matched_client_id == "existing"


def test_upsert_is_idempotent_and_dismissed_is_retained(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("syncro", "PSA")
    candidate = _candidate(instance.connector_instance_id, "1", "Unknown")
    first = store.upsert_client_candidate(candidate)
    second = store.upsert_client_candidate(replace(candidate, last_seen=utc_now(), display_name="Renamed"))
    assert first.candidate_id == second.candidate_id
    assert second.display_name == "Renamed"
    store.set_client_candidate_state(candidate.candidate_id, "dismissed")
    retained = store.upsert_client_candidate(replace(candidate, match_state="proposed"))
    assert retained.match_state == "dismissed"
    assert store.count_client_candidates() == {"dismissed": 1}


def test_candidate_store_validates_states_pagination_and_unknown_ids(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    candidate = _candidate(instance.connector_instance_id, "1", "Unknown")
    with pytest.raises(ValueError, match="unsupported candidate match state"):
        store.upsert_client_candidate(replace(candidate, match_state="invalid"))
    store.upsert_client_candidate(candidate)

    with pytest.raises(ValueError, match="unsupported candidate match state"):
        store.set_client_candidate_state(candidate.candidate_id, "invalid")
    with pytest.raises(ValueError, match="candidate pagination"):
        store.list_client_candidates(offset=-1)
    with pytest.raises(ValueError, match="candidate pagination"):
        store.list_client_candidates(limit=501)
    with pytest.raises(ValueError, match="unsupported candidate match state"):
        store.list_client_candidates(match_state="invalid")
    assert store.get_client_candidate("missing") is None
    assert store.set_client_candidate_state("missing", "proposed") is None
    assert store.set_client_candidate_state("   ", "proposed") is None


def test_candidate_upsert_can_replace_unprotected_state_but_verified_state_stays_protected(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("client", "Client")
    candidate = _candidate(instance.connector_instance_id, "1", "Unknown")
    store.upsert_client_candidate(candidate)
    replaced = store.upsert_client_candidate(
        replace(candidate, match_state="proposed", matched_client_id="client", match_reason="manual", confidence=0.8),
        preserve_state=False,
    )
    assert replaced.match_state == "proposed"
    assert replaced.matched_client_id == "client"
    assert replaced.match_reason == "manual"
    assert replaced.confidence == 0.8

    verified = store.upsert_client_candidate(
        replace(replaced, match_state="verified", matched_client_id="client", confidence=1.0),
        preserve_state=False,
    )
    refreshed = store.upsert_client_candidate(
        replace(verified, match_state="unmatched", matched_client_id=None, match_reason="refresh", confidence=0.0),
        preserve_state=False,
    )
    assert refreshed.match_state == "verified"
    assert refreshed.matched_client_id == "client"
    assert refreshed.confidence == 1.0


def test_verified_mapping_wins_over_name_matching(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    store.create_client("other", "Different Name")
    mapping = store.create_client_connector_mapping(AllClients(), instance.connector_instance_id, "1", "other")
    store.verify_client_connector_mapping(AllClients(), mapping.mapping_id)
    result = match_candidate(store, _candidate(instance.connector_instance_id, "1", "Different Name"))
    assert result.state == "verified"
    assert result.client_id == "other"


def test_bulk_accept_requires_only_proposed_candidates() -> None:
    candidate = _candidate("instance", "1", "Acme", "proposed")
    assert_bulk_accept_allowed([candidate])
    with pytest.raises(ClientDiscoveryError, match="proposed"):
        assert_bulk_accept_allowed([replace(candidate, match_state="ambiguous")])


def test_discovery_reads_instance_client_and_repeats_idempotently(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    store.update_connector_instance(instance.connector_instance_id, status="active")

    class FakeClient:
        def list_companies(self, *, page: int, page_size: int):
            return [{"id": "42", "name": "Acme Ltd"}] if page == 1 else []

    monkeypatch.setattr("wait_local_agent.client_discovery.build_read_client_for", lambda *args, **kwargs: FakeClient())
    stored = store.get_connector_instance(instance.connector_instance_id)
    assert stored is not None
    first = discover_instance(store, stored, settings=cast(Settings, object()))
    second = discover_instance(store, stored, settings=cast(Settings, object()))
    assert len(first) == len(second) == 1
    assert first[0].candidate_id == second[0].candidate_id
    assert len(store.list_client_candidates()) == 1


def test_discovery_rejects_unsupported_and_inactive_instances(tmp_path) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    with pytest.raises(ClientDiscoveryError, match="PSA connector"):
        discover_instance(store, replace(instance, connector_type="other"), settings=cast(Settings, object()))
    with pytest.raises(ClientDiscoveryError, match="not active"):
        discover_instance(store, instance, settings=cast(Settings, object()))


def test_discovery_normalizes_provider_failure_and_factory_errors(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("servicenow", "PSA")
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None

    class FailedClient:
        def list_companies(self, *, page: int, page_size: int):
            return SimpleNamespace(items=[], result=SimpleNamespace(status="failed"))

    monkeypatch.setattr(
        "wait_local_agent.client_discovery.build_read_client_for", lambda *args, **kwargs: FailedClient()
    )
    with pytest.raises(ClientDiscoveryError, match="organization discovery failed"):
        discover_instance(store, active, settings=cast(Settings, object()))

    def raise_factory_error(*args, **kwargs):
        raise ConnectorFactoryError("not configured")

    monkeypatch.setattr("wait_local_agent.client_discovery.build_read_client_for", raise_factory_error)
    with pytest.raises(ClientDiscoveryError, match="could not be prepared"):
        discover_instance(store, active, settings=cast(Settings, object()))


def test_discovery_skips_malformed_records_and_continues_after_full_pages(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("connectwise", "PSA")
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None
    calls: list[int] = []

    class FakeClient:
        def list_companies(self, *, page: int, page_size: int):
            calls.append(page)
            return [object()] * 100 if page == 1 else []

    monkeypatch.setattr(
        "wait_local_agent.client_discovery.build_read_client_for", lambda *args, **kwargs: FakeClient()
    )
    assert discover_instance(store, active, settings=cast(Settings, object())) == []
    assert calls == [1, 2]


def test_syncro_full_page_uses_its_smaller_page_threshold(tmp_path, monkeypatch) -> None:
    store = Store(tmp_path / "state.db")
    instance = store.create_connector_instance("syncro", "PSA")
    active = store.update_connector_instance(instance.connector_instance_id, status="active")
    assert active is not None
    calls: list[int] = []

    class FakeClient:
        def list_customers(self, *, page: int):
            calls.append(page)
            return [object()] * 25 if page == 1 else []

    monkeypatch.setattr(
        "wait_local_agent.client_discovery.build_read_client_for", lambda *args, **kwargs: FakeClient()
    )
    assert discover_instance(store, active, settings=cast(Settings, object())) == []
    assert calls == [1, 2]
