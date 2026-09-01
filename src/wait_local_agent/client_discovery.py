"""PSA-first external organization discovery and deterministic reconciliation."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from wait_local_agent.client_scope import AllClients
from wait_local_agent.config import Settings
from wait_local_agent.connector_factory import ConnectorFactoryError, VaultReader, build_read_client_for
from wait_local_agent.models import ClientCandidate, ConnectorInstance, utc_now
from wait_local_agent.store import Store

PSA_CONNECTOR_TYPES = frozenset({"halopsa", "connectwise", "autotask", "syncro", "servicenow"})
MATCH_STATES = frozenset({"verified", "proposed", "ambiguous", "unmatched", "conflicting", "dismissed"})
_LEGAL_SUFFIXES = frozenset({"ltd", "inc", "llc", "gmbh"})


class ClientDiscoveryError(ValueError):
    """Raised when a provider cannot safely supply a candidate set."""


@dataclass(frozen=True)
class CandidateMatch:
    state: str
    client_id: str | None
    reason: str
    confidence: float


def normalize_client_name(value: str) -> str:
    """Normalize only exact-name comparison tokens; never perform fuzzy matching."""

    tokens = re.findall(r"[a-z0-9]+", value.casefold())
    while tokens and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _value(item: object, *keys: str) -> object:
    if isinstance(item, Mapping):
        for key in keys:
            if item.get(key) not in (None, ""):
                return item[key]
    else:
        for key in keys:
            value = getattr(item, key, None)
            if value not in (None, ""):
                return value
    return None


def _text(item: object, *keys: str) -> str:
    value = _value(item, *keys)
    return "" if value is None else str(value).strip()


def _domains(item: object) -> list[str]:
    value = _value(item, "domains", "domain")
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        return [str(entry).strip() for entry in value if str(entry).strip()]
    return []


def _response_items(response: object) -> tuple[list[object], str]:
    if isinstance(response, list):
        return response, "ready"
    items = getattr(response, "items", None)
    result = getattr(response, "result", None)
    status = str(getattr(result, "status", "ready")).casefold()
    if not isinstance(items, list):
        raise ClientDiscoveryError("provider returned an invalid organization list")
    return items, status


def _list_page(client: Any, provider: str, page: int) -> tuple[list[object], str]:
    if provider == "halopsa":
        response = client.list_clients(page=page, page_size=100)
    elif provider == "syncro":
        response = client.list_customers(page=page)
    elif provider == "servicenow":
        response = client.list_companies(page=page, page_size=100)
    else:
        response = client.list_companies(page=page, page_size=100)
    return _response_items(response)


def _external_candidate(instance: ConnectorInstance, provider: str, item: object, now: str) -> ClientCandidate | None:
    external_id = _text(item, "id", "sys_id", "customer_id", "company_id", "identifier")
    display_name = _text(item, "name", "company_name", "companyName", "customer_name")
    if not external_id or not display_name:
        return None
    candidate_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"wait-local-agent:client-candidate:{instance.connector_instance_id}:{external_id}",
    ))
    return ClientCandidate(
        candidate_id=candidate_id,
        connector_instance_id=instance.connector_instance_id,
        provider=provider,
        external_id=external_id,
        display_name=display_name,
        domains_json=json.dumps(_domains(item), separators=(",", ":")),
        provenance=f"{provider}:{instance.connector_instance_id}",
        first_seen=now,
        last_seen=now,
        match_state="unmatched",
        matched_client_id=None,
        match_reason="",
        confidence=0.0,
    )


def match_candidate(store: Store, candidate: ClientCandidate) -> CandidateMatch:
    mappings = [
        mapping
        for mapping in store.list_client_connector_mappings(
            AllClients(), connector_instance_id=candidate.connector_instance_id
        )
        if mapping.external_company_id == candidate.external_id and mapping.verified
    ]
    mapped_clients = {mapping.client_id for mapping in mappings}
    if len(mapped_clients) == 1:
        return CandidateMatch("verified", next(iter(mapped_clients)), "verified connector mapping", 1.0)
    if len(mapped_clients) > 1:
        return CandidateMatch("conflicting", None, "external ID has multiple verified client mappings", 0.0)

    normalized_name = normalize_client_name(candidate.display_name)
    if not normalized_name:
        return CandidateMatch("unmatched", None, "candidate name has no comparable tokens", 0.0)
    matches = [
        client.client_id
        for client in store.list_clients(AllClients())
        if client.client_id != "__quarantine__" and normalize_client_name(client.name) == normalized_name
    ]
    if len(matches) == 1:
        return CandidateMatch("proposed", matches[0], "exact normalized client name", 0.9)
    if len(matches) > 1:
        return CandidateMatch("ambiguous", None, "exact normalized name matches multiple clients", 0.0)
    return CandidateMatch("unmatched", None, "no exact normalized client name match", 0.0)


def discover_instance(
    store: Store,
    instance: ConnectorInstance,
    *,
    settings: Settings,
    vault: VaultReader | None = None,
) -> list[ClientCandidate]:
    provider = instance.connector_type.casefold().strip()
    if provider not in PSA_CONNECTOR_TYPES:
        raise ClientDiscoveryError("client discovery supports PSA connector instances only")
    if instance.status.casefold().strip() != "active":
        raise ClientDiscoveryError("connector instance is not active")
    try:
        client = build_read_client_for(store, instance.connector_instance_id, base_settings=settings, vault=vault)
        raw_items: list[object] = []
        for page in range(1, 101):
            items, status = _list_page(client, provider, page)
            if status not in {"ready", "ok", "success"}:
                raise ClientDiscoveryError(f"{provider} organization discovery failed")
            raw_items.extend(items)
            if len(items) < (100 if provider != "syncro" else 25):
                break
        now = utc_now()
        candidates: list[ClientCandidate] = []
        for item in raw_items:
            candidate = _external_candidate(instance, provider, item, now)
            if candidate is None:
                continue
            match = match_candidate(store, candidate)
            candidates.append(store.upsert_client_candidate(
                replace(candidate, match_state=match.state, matched_client_id=match.client_id,
                        match_reason=match.reason, confidence=match.confidence)
            ))
        return candidates
    except ConnectorFactoryError as exc:
        raise ClientDiscoveryError("connector instance could not be prepared for discovery") from exc


def assert_bulk_accept_allowed(candidates: list[ClientCandidate]) -> None:
    if any(candidate.match_state != "proposed" for candidate in candidates):
        raise ClientDiscoveryError("bulk accept is limited to proposed candidates")
