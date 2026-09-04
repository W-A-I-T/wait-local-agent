"""Client tenancy, discovery, connector-instance, and ingestion API routes."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import Annotated, Literal, cast

from fastapi import APIRouter, HTTPException, Query

from wait_local_agent.api.context import AdminAccess, ApiContext, ViewerAccess
from wait_local_agent.api.schemas import (
    ClientConnectorMappingCreateRequest,
    ClientCreateRequest,
    ClientDiscoveryBulkAcceptRequest,
    ClientDiscoveryRunRequest,
    ClientStatusRequest,
    ConnectorInstanceCreateRequest,
    ConnectorInstanceUpdateRequest,
    DeploymentModeRequest,
    QuarantineReclassificationRequest,
)
from wait_local_agent.api.scopes import (
    _require_commercial_activation_access,
    _require_msp_operator,
    _resolve_client_target_scope,
)
from wait_local_agent.api.views import _baseline_view
from wait_local_agent.client_discovery import (
    PSA_CONNECTOR_TYPES,
    ClientDiscoveryError,
    assert_bulk_accept_allowed,
    discover_instance,
)
from wait_local_agent.client_scope import AllClients, BoundClients, resolve_client_scope
from wait_local_agent.connector_factory import (
    SUPPORTED_CONNECTOR_TYPES,
    ConnectorFactoryError,
    validate_connector_instance,
)
from wait_local_agent.m365_auth import M365ProfileResolutionError
from wait_local_agent.models import ClientCandidate, ConnectorInstance
from wait_local_agent.operational_graph import OperationalGraphService
from wait_local_agent.rbac import AuthContext
from wait_local_agent.rmm import RmmProviderResolutionError, rmm_provider_from_settings
from wait_local_agent.store import (
    _QUARANTINE_CLIENT_ID,
    ClientConnectorMappingConflictError,
    QuarantineRetenantStateError,
    QuarantineRetenantTargetError,
    _normalize_client_id,
)


def create_tenancy_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    vault = ctx.vault
    operational_graph_service = ctx.operational_graph_service
    baseline_service = ctx.baseline_service
    _m365_graph_service_for_client = ctx.m365_graph_service_for_client

    @router.get("/clients")
    def clients(context: ViewerAccess, client_id: str | None = None) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, client_id)
        return [asdict(client) for client in store.list_clients(scope)]

    @router.get("/clients/commercial-activations")
    def commercial_activations(context: AdminAccess) -> list[dict[str, object]]:
        _require_commercial_activation_access(context)
        return [asdict(activation) for activation in store.list_commercial_activations(AllClients())]

    def _discovery_summary() -> dict[str, int]:
        counts = store.count_client_candidates()
        return {
            "discovered": sum(
                counts.get(state, 0)
                for state in ("verified", "proposed", "ambiguous", "unmatched", "conflicting")
            ),
            "reconciled": counts.get("verified", 0),
            "need_confirmation": counts.get("proposed", 0) + counts.get("ambiguous", 0),
            "unmatched": counts.get("unmatched", 0),
            "conflicts": counts.get("conflicting", 0),
        }

    def _require_discovery_write(context: AuthContext) -> None:
        if active_settings.demo_mode:
            raise HTTPException(status_code=403, detail="client discovery is unavailable in demo mode")
        _require_msp_operator(context)

    @router.get("/setup/mode")
    def deployment_mode(_: ViewerAccess) -> dict[str, str | None]:
        mode = store.get_app_config("deployment.mode")
        return {"mode": mode if mode in {"msp", "smb"} else None}

    @router.put("/setup/mode")
    def set_deployment_mode(payload: DeploymentModeRequest, context: AdminAccess) -> dict[str, str]:
        _require_discovery_write(context)
        store.set_app_config("deployment.mode", payload.mode, updated_by=context.approver_id or "admin")
        store.add_audit_event(
            "deployment.mode.updated", "deployment.mode", f"mode={payload.mode}", approver_id=context.approver_id
        )
        return {"mode": payload.mode}

    @router.post("/discovery/clients/run")
    def run_client_discovery(payload: ClientDiscoveryRunRequest, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        instances = store.list_connector_instances()
        if payload.connector_instance_id:
            instance = store.get_connector_instance(payload.connector_instance_id)
            if instance is None:
                raise HTTPException(status_code=404, detail="connector instance not found")
            instances = [instance]
        instances = [
            instance for instance in instances if instance.connector_type.casefold().strip() in PSA_CONNECTOR_TYPES
        ]
        if payload.connector_instance_id and not instances:
            raise HTTPException(status_code=409, detail="connector instance is not a supported PSA instance")
        discovered: list[ClientCandidate] = []
        failures: list[dict[str, str]] = []
        for instance in instances:
            try:
                discovered.extend(discover_instance(store, instance, settings=active_settings, vault=vault))
            except ClientDiscoveryError as exc:
                failures.append({"connector_instance_id": instance.connector_instance_id, "detail": str(exc)})
        store.add_audit_event(
            "client.discovery.run",
            payload.connector_instance_id or "all",
            f"candidates={len(discovered)} failures={len(failures)}",
            approver_id=context.approver_id,
        )
        return {
            "candidates": [asdict(candidate) for candidate in discovered],
            "failures": failures,
            "summary": _discovery_summary(),
        }

    @router.get("/discovery/clients")
    def list_client_discovery_candidates(
        context: AdminAccess,
        match_state: Literal[
            "verified", "proposed", "ambiguous", "unmatched", "conflicting", "dismissed"
        ] | None = None,
        page: int = Query(default=1, ge=1, le=5000),
        page_size: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, object]:
        _require_discovery_write(context)
        candidates = store.list_client_candidates(
            match_state=match_state, offset=(page - 1) * page_size, limit=page_size
        )
        return {
            "items": [asdict(candidate) for candidate in candidates],
            "page": page,
            "page_size": page_size,
            "summary": _discovery_summary(),
        }

    def _accept_discovery_candidate(candidate: ClientCandidate, context: AuthContext) -> dict[str, object]:
        if candidate.match_state != "proposed" or not candidate.matched_client_id:
            raise HTTPException(
                status_code=409, detail="only proposed candidates with one matched client can be accepted"
            )
        if store.get_client(AllClients(), candidate.matched_client_id) is None:
            raise HTTPException(status_code=409, detail="the proposed client no longer exists")
        try:
            mapping = store.create_client_connector_mapping(
                AllClients(), candidate.connector_instance_id, candidate.external_id, candidate.matched_client_id,
                external_company_name=candidate.display_name,
            )
            verification = store.verify_client_connector_mapping(
                AllClients(), mapping.mapping_id, return_retenanted_count=True
            )
        except ClientConnectorMappingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (sqlite3.IntegrityError, KeyError, ValueError) as exc:
            raise HTTPException(status_code=409, detail="candidate mapping could not be created") from exc
        if not isinstance(verification, tuple):  # pragma: no cover
            raise RuntimeError("mapping verification did not return re-tenant count")
        verified_mapping, retenanted_count = verification
        updated = store.set_client_candidate_state(
            candidate.candidate_id, "verified", matched_client_id=verified_mapping.client_id,
            match_reason="accepted proposed exact normalized name", confidence=1.0,
        )
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="candidate not found")
        store.add_audit_event(
            "client.discovery.accepted",
            candidate.candidate_id,
            f"client={verified_mapping.client_id}",
            client_id=verified_mapping.client_id,
            approver_id=context.approver_id,
        )
        return {
            **asdict(updated),
            "mapping": asdict(verified_mapping),
            "retenanted_count": retenanted_count,
        }

    @router.post("/discovery/clients/{candidate_id}/accept")
    def accept_client_discovery_candidate(candidate_id: str, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        candidate = store.get_client_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        return _accept_discovery_candidate(candidate, context)

    @router.post("/discovery/clients/accept-proposed")
    def bulk_accept_client_discovery_candidates(
        payload: ClientDiscoveryBulkAcceptRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_discovery_write(context)
        candidates = [store.get_client_candidate(candidate_id) for candidate_id in payload.candidate_ids]
        if any(candidate is None for candidate in candidates):
            raise HTTPException(status_code=404, detail="candidate not found")
        resolved = cast(list[ClientCandidate], candidates)
        try:
            assert_bulk_accept_allowed(resolved)
        except ClientDiscoveryError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        accepted = [_accept_discovery_candidate(candidate, context) for candidate in resolved]
        return {"accepted": accepted, "summary": _discovery_summary()}

    @router.post("/discovery/clients/{candidate_id}/create-client")
    def create_client_from_discovery_candidate(candidate_id: str, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        candidate = store.get_client_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if candidate.match_state in {"verified", "dismissed"}:
            raise HTTPException(status_code=409, detail="candidate cannot create a client in its current state")
        client_id = f"discovered-{candidate.candidate_id.replace('-', '')[:24]}"
        try:
            client = store.create_client(client_id, candidate.display_name)
            mapping = store.create_client_connector_mapping(
                AllClients(), candidate.connector_instance_id, candidate.external_id, client.client_id,
                external_company_name=candidate.display_name,
            )
            verification = store.verify_client_connector_mapping(
                AllClients(), mapping.mapping_id, return_retenanted_count=True
            )
        except (sqlite3.IntegrityError, KeyError, ValueError, ClientConnectorMappingConflictError) as exc:
            raise HTTPException(status_code=409, detail="client or candidate mapping already exists") from exc
        if not isinstance(verification, tuple):  # pragma: no cover
            raise RuntimeError("mapping verification did not return re-tenant count")
        verified_mapping, retenanted_count = verification
        updated = store.set_client_candidate_state(
            candidate.candidate_id,
            "verified",
            matched_client_id=client.client_id,
            match_reason="new client created from provider candidate",
            confidence=1.0,
        )
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="candidate not found")
        store.add_audit_event(
            "client.discovery.created",
            candidate.candidate_id,
            f"client={client.client_id}",
            client_id=client.client_id,
            approver_id=context.approver_id,
        )
        return {
            **asdict(updated),
            "client": asdict(client),
            "mapping": asdict(verified_mapping),
            "retenanted_count": retenanted_count,
        }

    @router.post("/discovery/clients/{candidate_id}/dismiss")
    def dismiss_client_discovery_candidate(candidate_id: str, context: AdminAccess) -> dict[str, object]:
        _require_discovery_write(context)
        candidate = store.get_client_candidate(candidate_id)
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        if candidate.match_state == "verified":
            raise HTTPException(status_code=409, detail="verified candidates cannot be dismissed")
        updated = store.set_client_candidate_state(candidate_id, "dismissed", match_reason="dismissed by administrator")
        if updated is None:  # pragma: no cover
            raise HTTPException(status_code=404, detail="candidate not found")
        store.add_audit_event(
            "client.discovery.dismissed", candidate_id, "dismissed by administrator", approver_id=context.approver_id
        )
        return asdict(updated)

    @router.post("/clients")
    def create_client(payload: ClientCreateRequest, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        try:
            return asdict(store.create_client(payload.client_id, payload.name))
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="client already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/clients/{client_id}")
    def client_detail(client_id: str, context: ViewerAccess) -> dict[str, object]:
        scope = _resolve_client_target_scope(context, client_id)
        client = store.get_client(scope, client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        return asdict(client)

    @router.post("/clients/{client_id}/commercial-activation")
    def activate_commercial_client(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_commercial_activation_access(context)
        scope = _resolve_client_target_scope(context, client_id)
        try:
            activation = store.activate_commercial_client(
                scope,
                client_id,
                context.approver_id or "admin",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if activation is None:
            raise HTTPException(status_code=404, detail="client not found")
        store.add_audit_event(
            "commercial.client_activated",
            activation.client_id,
            "commercial managed-client bookkeeping activated",
            client_id=activation.client_id,
            approver_id=context.approver_id,
        )
        return asdict(activation)

    @router.delete("/clients/{client_id}/commercial-activation")
    def deactivate_commercial_client(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_commercial_activation_access(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        store.deactivate_commercial_client(scope, client_id)
        store.add_audit_event(
            "commercial.client_deactivated",
            client_id,
            "commercial managed-client bookkeeping deactivated",
            client_id=client_id,
            approver_id=context.approver_id,
        )
        return {"client_id": client_id.strip(), "commercial_managed": False}

    @router.post("/clients/{client_id}/baselines", status_code=201)
    def create_client_baseline(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        if active_settings.demo_mode or not active_settings.allow_write_actions:
            raise HTTPException(status_code=403, detail="baseline writes are unavailable in demo mode")
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            return _baseline_view(baseline_service.create_baseline(client_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:  # do not expose provider failures
            raise HTTPException(status_code=503, detail="baseline collection failed") from exc

    @router.get("/clients/{client_id}/baselines")
    def client_baselines(client_id: str, context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        store.add_audit_event(
            "baseline.listed",
            client_id,
            "baseline versions listed",
            client_id=client_id,
            approver_id=context.approver_id,
        )
        return [_baseline_view(baseline) for baseline in store.list_client_baselines(scope)]

    @router.post("/clients/{client_id}/baselines/{version}/accept")
    def accept_client_baseline(client_id: str, version: int, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        if active_settings.demo_mode or not active_settings.allow_write_actions:
            raise HTTPException(status_code=403, detail="baseline writes are unavailable in demo mode")
        scope = _resolve_client_target_scope(context, client_id)
        accepted = store.accept_client_baseline(scope, version)
        if accepted is None or accepted.client_id != client_id.strip():
            raise HTTPException(status_code=404, detail="baseline not found")
        return _baseline_view(accepted)

    @router.get("/clients/{client_id}/drift")
    def client_drift(
        client_id: str,
        context: AdminAccess,
        baseline_version: Annotated[int | None, Query(ge=1)] = None,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        if not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="baseline drift requires live read probing")
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            result = baseline_service.diff_baseline(
                client_id,
                baseline_version=baseline_version,
            )
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="client baseline not found") from exc
        store.add_audit_event(
            "baseline.drift.viewed",
            client_id,
            "baseline drift comparison completed",
            client_id=client_id,
            approver_id=context.approver_id,
        )
        return result

    @router.get("/clients/{client_id}/graph")
    def client_graph(
        client_id: str,
        context: ViewerAccess,
        entity_type: str | None = None,
        link_type: str | None = None,
        source_system: str | None = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=200)] = 100,
    ) -> dict[str, object]:
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            return asdict(
                operational_graph_service.client_graph(
                    scope,
                    entity_type=entity_type,
                    link_type=link_type,
                    source_system=source_system,
                    offset=offset,
                    limit=limit,
                )
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/clients/{client_id}/graph/sync-rmm")
    def sync_client_rmm_graph(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        try:
            client_rmm_provider = rmm_provider_from_settings(
                active_settings,
                store,
                client_id,
                vault,
            )
        except RmmProviderResolutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if client_rmm_provider.adapter_id != "local-collector" and not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="RMM read probing is disabled")
        return dict(OperationalGraphService(store, rmm_provider=client_rmm_provider).seed_rmm_inventory(scope))

    @router.post("/clients/{client_id}/graph/sync-m365")
    def sync_client_m365_graph(client_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        if store.get_client(scope, client_id) is None:
            raise HTTPException(status_code=404, detail="client not found")
        if not active_settings.allow_http_probing:
            raise HTTPException(status_code=409, detail="Microsoft 365 read probing is disabled")
        try:
            service = _m365_graph_service_for_client(client_id)
        except M365ProfileResolutionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return dict(service.seed_m365_inventory(scope))

    @router.patch("/clients/{client_id}")
    def update_client_status(
        client_id: str,
        payload: ClientStatusRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        scope = _resolve_client_target_scope(context, client_id)
        try:
            client = store.set_client_status(scope, client_id, payload.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        return asdict(client)

    @router.get("/connector-instances")
    def connector_instances(context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        return [asdict(instance) for instance in store.list_connector_instances()]

    @router.get("/ingestion/sync-cursors")
    def ingestion_sync_cursors(context: AdminAccess) -> list[dict[str, object]]:
        _require_msp_operator(context)
        return [asdict(cursor) for cursor in store.list_sync_cursors()]

    @router.get("/ingestion/unmapped")
    def ingestion_unmapped(
        context: ViewerAccess,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        try:
            records = store.list_unmapped_records(
                scope,
                connector_instance_id=connector_instance_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(record) for record in records]

    @router.get("/ingestion/quarantined")
    def ingestion_quarantined(
        context: ViewerAccess,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        normalized_instance_id = _normalize_client_id(connector_instance_id)
        if connector_instance_id is not None and normalized_instance_id is None:
            raise HTTPException(status_code=400, detail="connector_instance_id must be non-empty")
        if isinstance(scope, BoundClients):
            # Quarantine is not a client membership.  Bound viewers must name an
            # instance pinned to one of their ordinary client memberships.
            if normalized_instance_id is None:
                return []
            instance = store.get_connector_instance(normalized_instance_id)
            if (
                instance is None
                or instance.client_id == _QUARANTINE_CLIENT_ID
                or instance.client_id not in scope.client_ids
            ):
                return []
        try:
            tickets = store.list_quarantined_tickets(normalized_instance_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(ticket) for ticket in tickets]

    @router.post("/ingestion/unmapped/{record_id}/resolve")
    def resolve_ingestion_unmapped(record_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        record = store.resolve_unmapped_record(record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unmapped record not found")
        return asdict(record)

    @router.post("/ingestion/quarantined/{ticket_id}/reclassify")
    def reclassify_ingestion_quarantined(
        ticket_id: str,
        payload: QuarantineReclassificationRequest,
        context: AdminAccess,
    ) -> dict[str, str]:
        _require_msp_operator(context)
        try:
            store.reclassify_quarantined_ticket(ticket_id, payload.client_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ticket_id": ticket_id, "client_id": payload.client_id.strip()}

    @router.post("/connector-instances")
    def create_connector_instance(
        payload: ConnectorInstanceCreateRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        connector_type = payload.connector_type.strip().casefold()
        if not connector_type:
            raise HTTPException(status_code=400, detail="connector_type must be non-empty")
        if connector_type not in SUPPORTED_CONNECTOR_TYPES:
            accepted_types = ", ".join(sorted(SUPPORTED_CONNECTOR_TYPES))
            raise HTTPException(
                status_code=422,
                detail=f"unsupported connector_type; accepted types: {accepted_types}",
            )
        if payload.credential_ref and connector_type in {
            "autotask",
            "syncro",
            "servicenow",
            "ninjaone",
            "dattormm",
            "ncentral",
            "m365",
        }:
            candidate = ConnectorInstance(
                connector_instance_id="pending-validation",
                connector_type=connector_type,
                display_name=payload.display_name,
                client_id=payload.client_id,
                credential_ref=payload.credential_ref,
                config_json=payload.config_json,
                status="inactive",
                created_at="",
                updated_at="",
            )
            try:
                validate_connector_instance(candidate, base_settings=active_settings, vault=vault)
            except ConnectorFactoryError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            instance = store.create_connector_instance(
                payload.connector_type,
                payload.display_name,
                client_id=payload.client_id,
                credential_ref=payload.credential_ref,
                config_json=payload.config_json,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="connector instance already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(instance)

    @router.get("/connector-instances/{connector_instance_id}")
    def connector_instance_detail(
        connector_instance_id: str,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        instance = store.get_connector_instance(connector_instance_id)
        if instance is None:
            raise HTTPException(status_code=404, detail="connector instance not found")
        return asdict(instance)

    @router.patch("/connector-instances/{connector_instance_id}")
    def update_connector_instance(
        connector_instance_id: str,
        payload: ConnectorInstanceUpdateRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        _require_msp_operator(context)
        try:
            instance = store.update_connector_instance(
                connector_instance_id,
                **payload.model_dump(exclude_unset=True),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="client not found") from exc
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="connector instance already exists") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if instance is None:
            raise HTTPException(status_code=404, detail="connector instance not found")
        return asdict(instance)

    @router.get("/client-connector-mappings")
    def client_connector_mappings(
        context: ViewerAccess,
        connector_instance_id: str | None = None,
    ) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        try:
            mappings = store.list_client_connector_mappings(
                scope,
                connector_instance_id=connector_instance_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [asdict(mapping) for mapping in mappings]

    @router.post("/client-connector-mappings")
    def create_client_connector_mapping(
        payload: ClientConnectorMappingCreateRequest,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _resolve_client_target_scope(context, payload.client_id)
        try:
            mapping = store.create_client_connector_mapping(
                scope,
                payload.connector_instance_id,
                payload.external_company_id,
                payload.client_id,
                external_company_name=payload.external_company_name,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            detail = (
                "client not found"
                if str(exc.args[0]) == _normalize_client_id(payload.client_id)
                else "connector instance not found"
            )
            raise HTTPException(status_code=404, detail=detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return asdict(mapping)

    @router.post("/client-connector-mappings/{mapping_id}/verify")
    def verify_client_connector_mapping(mapping_id: str, context: AdminAccess) -> dict[str, object]:
        _require_msp_operator(context)
        scope = resolve_client_scope(context, None)
        try:
            verification = store.verify_client_connector_mapping(
                scope,
                mapping_id,
                return_retenanted_count=True,
            )
        except ClientConnectorMappingConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except QuarantineRetenantTargetError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except QuarantineRetenantStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="mapping not found") from exc
        if not isinstance(verification, tuple):  # pragma: no cover - opt-in route return is always a tuple
            raise RuntimeError("mapping verification did not return re-tenant count")
        mapping, retenanted_count = verification
        response = asdict(mapping)
        response["retenanted_count"] = retenanted_count
        return response

    return router
