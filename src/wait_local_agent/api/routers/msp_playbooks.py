"""MSP playbook API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from wait_local_agent.api.context import ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    MspPlaybookEntryCreateRequest,
    MspPlaybookEntryUpdateRequest,
    MspPlaybookRunRequest,
    MspPlaybookSubscriptionCreateRequest,
    MspPlaybookSubscriptionUpdateRequest,
)
from wait_local_agent.api.scopes import _operator_scope, _resolve_detail_scope
from wait_local_agent.api.views import _dispatch_workflow_completion_event
from wait_local_agent.client_scope import AllClients, resolve_client_scope
from wait_local_agent.msp_playbooks import (
    create_msp_playbook_subscription,
    list_msp_playbooks,
    msp_playbook_entry_view,
    msp_playbook_revision_diff,
    msp_playbook_revision_view,
    msp_playbook_subscription_view,
    playbook_view,
    preview_msp_playbook,
    publish_msp_playbook,
    run_msp_playbook,
    update_msp_playbook,
    update_msp_playbook_subscription,
)
from wait_local_agent.rbac import Role


def create_msp_playbooks_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    smart_action_service = ctx.smart_action_service
    event_dispatcher = ctx.event_dispatcher

    @router.get("/msp/playbooks")
    def msp_playbooks(_: ViewerAccess) -> list[dict[str, object]]:
        return [playbook_view(playbook) for playbook in list_msp_playbooks()]

    @router.get("/msp/playbook-entries")
    def msp_playbook_entries(context: ViewerAccess) -> list[dict[str, object]]:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        return [
            msp_playbook_entry_view(entry)
            for entry in store.list_msp_playbook_entries(scope.client_id)
        ]

    @router.post("/msp/playbook-entries", status_code=201)
    def create_msp_playbook_entry_route(
        request: MspPlaybookEntryCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")  # pragma: no cover
        try:
            entry = publish_msp_playbook(
                store,
                request.source_playbook_id,
                provenance=request.provenance,
                definition=request.definition,
                enabled=request.enabled,
                client_id=scoped_client_id,
            )
            return msp_playbook_entry_view(entry)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="source MSP playbook not found") from exc
        except ValueError as exc:  # pragma: no cover
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/msp/playbook-entries/{entry_id}")
    def get_msp_playbook_entry_route(
        entry_id: str,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        entry = store.get_msp_playbook_entry(entry_id, scoped_client_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found")
        return msp_playbook_entry_view(entry)

    @router.patch("/msp/playbook-entries/{entry_id}")
    def update_msp_playbook_entry_route(
        entry_id: str,
        request: MspPlaybookEntryUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        existing = store.get_msp_playbook_entry(entry_id, scoped_client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found")
        try:
            entry = update_msp_playbook(
                store,
                entry_id,
                client_id=existing.client_id,
                definition=request.definition,
                provenance=request.provenance,
                enabled=request.enabled,
            )
            return msp_playbook_entry_view(entry)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/msp/playbook-entries/{entry_id}/enable")
    def enable_msp_playbook_entry_route(
        entry_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_entry_route(
            entry_id,
            MspPlaybookEntryUpdateRequest(enabled=True),
            context,
        )

    @router.post("/msp/playbook-entries/{entry_id}/disable")
    def disable_msp_playbook_entry_route(
        entry_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_entry_route(
            entry_id,
            MspPlaybookEntryUpdateRequest(enabled=False),
            context,
        )

    @router.get("/msp/playbook-entries/{entry_id}/revisions")
    def list_msp_playbook_revisions_route(
        entry_id: str,
        context: ViewerAccess,
    ) -> list[dict[str, object]]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        if store.get_msp_playbook_entry(entry_id, scoped_client_id) is None:
            raise HTTPException(status_code=404, detail="MSP playbook entry not found")
        return [
            msp_playbook_revision_view(revision)
            for revision in store.list_msp_playbook_revisions(entry_id, scoped_client_id)
        ]

    @router.get("/msp/playbook-entries/{entry_id}/revisions/diff")
    def diff_msp_playbook_revisions_route(
        entry_id: str,
        context: ViewerAccess,
        from_version: int = Query(..., ge=1),
        to_version: int = Query(..., ge=1),
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        left = store.get_msp_playbook_revision(entry_id, from_version, scoped_client_id)
        right = store.get_msp_playbook_revision(entry_id, to_version, scoped_client_id)
        if left is None or right is None:
            raise HTTPException(status_code=404, detail="MSP playbook revision not found")
        return msp_playbook_revision_diff(left, right)

    @router.post("/msp/playbook-entries/{entry_id}/revisions/{version}/restore")
    def restore_msp_playbook_revision_route(
        entry_id: str,
        version: int,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id)
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        existing = store.get_msp_playbook_entry(entry_id, scope.client_id)
        if existing is None:
            raise HTTPException(status_code=404, detail="MSP playbook revision not found")
        try:
            return msp_playbook_entry_view(
                store.restore_msp_playbook_revision(entry_id, version, existing.client_id)
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook revision not found") from exc
        except ValueError as exc:  # pragma: no cover
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/msp/playbook-subscriptions")
    def msp_playbook_subscriptions(context: ViewerAccess) -> list[dict[str, object]]:
        scope = resolve_client_scope(context, None)
        return [
            msp_playbook_subscription_view(subscription)
            for subscription in store.list_msp_playbook_subscriptions(scope)
        ]

    @router.post("/msp/playbook-subscriptions", status_code=201)
    def create_msp_playbook_subscription_route(
        request: MspPlaybookSubscriptionCreateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, request.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=422, detail="client_id is required for a playbook subscription")
        try:
            subscription = create_msp_playbook_subscription(
                store,
                request.playbook_id,
                event_type=request.event_type,
                client_id=scoped_client_id,
                input_mapping=request.input_mapping,
                enabled=request.enabled,
            )
            return msp_playbook_subscription_view(subscription)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/msp/playbook-subscriptions/{subscription_id}")
    def get_msp_playbook_subscription_route(
        subscription_id: str,
        context: ViewerAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        subscription = store.get_msp_playbook_subscription(subscription_id, scope)
        if subscription is None:
            raise HTTPException(status_code=404, detail="MSP playbook subscription not found")
        return msp_playbook_subscription_view(subscription)

    @router.patch("/msp/playbook-subscriptions/{subscription_id}")
    def update_msp_playbook_subscription_route(
        subscription_id: str,
        request: MspPlaybookSubscriptionUpdateRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _resolve_detail_scope(context, None)
        existing = store.get_msp_playbook_subscription(subscription_id, scope)
        if existing is None:
            raise HTTPException(status_code=404, detail="MSP playbook subscription not found")
        scoped_client_id = existing.client_id
        try:
            subscription = update_msp_playbook_subscription(
                store,
                subscription_id,
                client_id=scoped_client_id,
                input_mapping=request.input_mapping,
                enabled=request.enabled,
            )
            return msp_playbook_subscription_view(subscription)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook subscription not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/msp/playbook-subscriptions/{subscription_id}/enable")
    def enable_msp_playbook_subscription_route(
        subscription_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_subscription_route(
            subscription_id,
            MspPlaybookSubscriptionUpdateRequest(enabled=True),
            context,
        )

    @router.post("/msp/playbook-subscriptions/{subscription_id}/disable")
    def disable_msp_playbook_subscription_route(
        subscription_id: str,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        return update_msp_playbook_subscription_route(
            subscription_id,
            MspPlaybookSubscriptionUpdateRequest(enabled=False),
            context,
        )

    @router.post("/msp/playbooks/{playbook_id}/preview")
    def preview_msp_playbook_route(
        playbook_id: str,
        request: MspPlaybookRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return preview_msp_playbook(
                store,
                playbook_id,
                ticket_id=request.ticket_id,
                client_id=scoped_client_id,
                input_payload=request.payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/msp/playbooks/{playbook_id}/runs")
    def run_msp_playbook_route(
        playbook_id: str,
        request: MspPlaybookRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scope = _operator_scope(context, active_settings.client_id, request.client_id)
        scoped_client_id = scope.client_id
        if context.role < Role.ADMIN and isinstance(scope, AllClients):
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            result = run_msp_playbook(
                store,
                playbook_id,
                ticket_id=request.ticket_id,
                client_id=scoped_client_id,
                actor=context.approver_id or "api",
                trigger_source="msp_playbook_api",
                input_payload=request.payload,
                tool_executor=smart_action_service,
                smart_action_service=smart_action_service,
                on_workflow_run=lambda run: _dispatch_workflow_completion_event(
                    event_dispatcher, run, context.approver_id or "api"
                ),
            )
            return result
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="MSP playbook not found") from exc
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="ticket not found") from exc
        except PermissionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router


__all__ = ["create_msp_playbooks_router"]
