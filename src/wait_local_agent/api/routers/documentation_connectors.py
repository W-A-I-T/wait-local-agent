"""Documentation Connectors API routes."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast

from fastapi import APIRouter, HTTPException, Request

from wait_local_agent.api.context import ApiContext, ViewerAccess
from wait_local_agent.api.views import redact_value
from wait_local_agent.client_scope import requested_client_from, resolve_client_scope
from wait_local_agent.confluence import ConfluenceClient, ConfluenceReadResponse
from wait_local_agent.hudu import HuduClient, HuduReadResponse
from wait_local_agent.itglue import ItGlueClient, ItGlueReadResponse
from wait_local_agent.notion import NotionDataSourceResponse, NotionReadResponse
from wait_local_agent.scalepad import (
    ScalePadAssessmentResponse,
    ScalePadClientResponse,
    ScalePadComplianceHealthResponse,
    ScalePadGoalResponse,
    ScalePadRiskSummaryResponse,
)
from wait_local_agent.sharepoint import SharePointClient, SharePointReadResponse


def create_documentation_connectors_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    hudu_client = ctx.hudu_client
    itglue_client = ctx.itglue_client
    confluence_client = ctx.confluence_client
    notion_client = ctx.notion_client
    sharepoint_client = ctx.sharepoint_client
    scalepad_client = ctx.scalepad_client
    _connector_read_client = ctx.connector_read_client

    def _hudu_response(read_type: str, response: HuduReadResponse) -> dict[str, object]:
        _audit_hudu_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
        }
    def _audit_hudu_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("hudu.read", read_type, f"{status} count={count}")
    def _itglue_response(
        read_type: str,
        response: ItGlueReadResponse,
    ) -> dict[str, object]:
        _audit_itglue_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
        }
    def _audit_itglue_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("itglue.read", read_type, f"{status} count={count}")
    def _confluence_response(
        read_type: str,
        response: ConfluenceReadResponse,
    ) -> dict[str, object]:
        _audit_confluence_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }
    def _audit_confluence_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("confluence.read", read_type, f"{status} count={count}")
    def _notion_response(read_type: str, response: NotionReadResponse) -> dict[str, object]:
        _audit_notion_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }
    def _notion_data_source_response(read_type: str, response: NotionDataSourceResponse) -> dict[str, object]:
        _audit_notion_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
        }
    def _audit_notion_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("notion.read", read_type, f"{status} count={count}")
    def _sharepoint_response(
        read_type: str,
        response: SharePointReadResponse,
    ) -> dict[str, object]:
        _audit_sharepoint_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }
    def _audit_sharepoint_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("sharepoint.read", read_type, f"{status} count={count}")
    def _scalepad_response(
        read_type: str,
        response: ScalePadClientResponse,
    ) -> dict[str, object]:
        _audit_scalepad_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(asdict(item))) for item in response.items],
            "next_cursor": response.next_cursor,
        }
    def _scalepad_risk_summary_response(
        read_type: str,
        response: ScalePadRiskSummaryResponse,
    ) -> dict[str, object]:
        _audit_scalepad_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(item)) for item in response.items],
            "next_cursor": response.next_cursor,
            "total_count": response.total_count,
        }
    def _scalepad_compliance_health_response(
        read_type: str,
        response: ScalePadComplianceHealthResponse,
    ) -> dict[str, object]:
        _audit_scalepad_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "item": redact_value(response.item) if response.item is not None else None,
        }
    def _scalepad_goal_response(
        read_type: str,
        response: ScalePadGoalResponse,
    ) -> dict[str, object]:
        _audit_scalepad_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(item)) for item in response.items],
            "next_cursor": response.next_cursor,
            "total_count": response.total_count,
        }
    def _scalepad_assessment_response(
        read_type: str,
        response: ScalePadAssessmentResponse,
    ) -> dict[str, object]:
        _audit_scalepad_read(read_type, response.result.status, response.result.count)
        return {
            "result": asdict(response.result),
            "items": [cast(dict[str, object], redact_value(item)) for item in response.items],
            "next_cursor": response.next_cursor,
            "total_count": response.total_count,
        }
    def _audit_scalepad_read(read_type: str, status: str, count: int) -> None:
        store.add_audit_event("scalepad.read", read_type, f"{status} count={count}")

    @router.get("/connectors/hudu/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = hudu_client.health()
        _audit_hudu_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/hudu/companies")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_companies(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HuduClient, _connector_read_client(request, context, "hudu", hudu_client, requested_client_id=client_id)
        )
        response = client.list_companies(page=page, page_size=page_size)
        return _hudu_response("companies.list", response)

    @router.get("/connectors/hudu/articles")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_articles(
        request: Request,
        context: ViewerAccess,
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HuduClient, _connector_read_client(request, context, "hudu", hudu_client, requested_client_id=client_id)
        )
        response = client.list_articles(
            company_id=company_id,
            page=page,
            page_size=page_size,
        )
        return _hudu_response("articles.list", response)

    @router.get("/connectors/hudu/articles/{article_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_article(
        article_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HuduClient, _connector_read_client(request, context, "hudu", hudu_client, requested_client_id=client_id)
        )
        response = client.get_article(article_id)
        return _hudu_response("articles.get", response)

    @router.get("/connectors/hudu/folders")
    @limiter.limit(active_settings.rate_limit_connector)
    def hudu_folders(
        request: Request,
        context: ViewerAccess,
        company_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            HuduClient, _connector_read_client(request, context, "hudu", hudu_client, requested_client_id=client_id)
        )
        response = client.list_folders(
            company_id=company_id,
            page=page,
            page_size=page_size,
        )
        return _hudu_response("folders.list", response)

    @router.get("/connectors/itglue/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = itglue_client.health()
        _audit_itglue_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/itglue/organizations")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_organizations(
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ItGlueClient,
            _connector_read_client(request, context, "itglue", itglue_client, requested_client_id=client_id),
        )
        response = client.list_organizations(
            page=page,
            page_size=(page_size if page_size is not None else active_settings.itglue_page_size),
        )
        return _itglue_response("organizations.list", response)

    @router.get("/connectors/itglue/organizations/{organization_id}/documents")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_documents(
        organization_id: str,
        request: Request,
        context: ViewerAccess,
        folder_id: str | None = None,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ItGlueClient,
            _connector_read_client(request, context, "itglue", itglue_client, requested_client_id=client_id),
        )
        response = client.list_documents(
            organization_id,
            folder_id=folder_id,
            page=page,
            page_size=(page_size if page_size is not None else active_settings.itglue_page_size),
        )
        return _itglue_response("documents.list", response)

    @router.get("/connectors/itglue/documents/{document_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_document(
        document_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ItGlueClient,
            _connector_read_client(request, context, "itglue", itglue_client, requested_client_id=client_id),
        )
        response = client.get_document(document_id)
        return _itglue_response("documents.get", response)

    @router.get("/connectors/itglue/organizations/{organization_id}/folders")
    @limiter.limit(active_settings.rate_limit_connector)
    def itglue_folders(
        organization_id: str,
        request: Request,
        context: ViewerAccess,
        page: int = 1,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ItGlueClient,
            _connector_read_client(request, context, "itglue", itglue_client, requested_client_id=client_id),
        )
        response = client.list_folders(
            organization_id,
            page=page,
            page_size=(page_size if page_size is not None else active_settings.itglue_page_size),
        )
        return _itglue_response("folders.list", response)

    @router.get("/connectors/confluence/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def confluence_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = confluence_client.health()
        _audit_confluence_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/confluence/pages")
    @limiter.limit(active_settings.rate_limit_connector)
    def confluence_pages(
        request: Request,
        context: ViewerAccess,
        space_id: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ConfluenceClient,
            _connector_read_client(request, context, "confluence", confluence_client, requested_client_id=client_id),
        )
        response = client.list_pages(
            space_id=space_id,
            title=title,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.confluence_page_size),
        )
        return _confluence_response("pages.list", response)

    @router.get("/connectors/confluence/pages/{page_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def confluence_page(
        page_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            ConfluenceClient,
            _connector_read_client(request, context, "confluence", confluence_client, requested_client_id=client_id),
        )
        response = client.get_page(page_id)
        return _confluence_response("pages.get", response)

    @router.get("/connectors/notion/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = notion_client.health()
        _audit_notion_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/notion/pages")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_pages(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        query: str = "",
        page_size: int | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="Notion reads require a tenant scope")
        response = notion_client.search_pages(
            client_id=scoped_client_id,
            query=query,
            page_size=page_size if page_size is not None else active_settings.notion_page_size,
        )
        return _notion_response("pages.search", response)

    @router.get("/connectors/notion/pages/{page_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_page(
        page_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="Notion reads require a tenant scope")
        response = notion_client.get_page(page_id, client_id=scoped_client_id)
        return _notion_response("pages.get", response)

    @router.get("/connectors/notion/data-sources/{data_source_id}/pages")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_data_source_pages(
        data_source_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        start_cursor: str = "",
        page_size: int | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="Notion data-source reads require a tenant scope")
        response = notion_client.query_data_source(
            data_source_id,
            client_id=scoped_client_id,
            page_size=page_size if page_size is not None else active_settings.notion_page_size,
            start_cursor=start_cursor,
        )
        return _notion_response("data-sources.query", response)

    @router.get("/connectors/notion/data-sources/{data_source_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def notion_data_source(
        data_source_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="Notion data-source reads require a tenant scope")
        response = notion_client.get_data_source(data_source_id, client_id=scoped_client_id)
        return _notion_data_source_response("data-sources.get", response)

    @router.get("/connectors/sharepoint/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = sharepoint_client.health()
        _audit_sharepoint_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/sharepoint/sites")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_sites(
        request: Request,
        context: ViewerAccess,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SharePointClient,
            _connector_read_client(request, context, "sharepoint", sharepoint_client, requested_client_id=client_id),
        )
        response = client.list_sites(
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.sharepoint_page_size),
        )
        return _sharepoint_response("sites.list", response)

    @router.get("/connectors/sharepoint/sites/{site_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_site(
        site_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SharePointClient,
            _connector_read_client(request, context, "sharepoint", sharepoint_client, requested_client_id=client_id),
        )
        response = client.get_site(site_id)
        return _sharepoint_response("sites.get", response)

    @router.get("/connectors/sharepoint/sites/{site_id}/documents")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_documents(
        site_id: str,
        request: Request,
        context: ViewerAccess,
        parent_item_id: str | None = None,
        cursor: str | None = None,
        page_size: int | None = None,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SharePointClient,
            _connector_read_client(request, context, "sharepoint", sharepoint_client, requested_client_id=client_id),
        )
        response = client.list_documents(
            site_id,
            parent_item_id=parent_item_id,
            cursor=cursor,
            page_size=(page_size if page_size is not None else active_settings.sharepoint_page_size),
        )
        return _sharepoint_response("documents.list", response)

    @router.get("/connectors/sharepoint/sites/{site_id}/documents/{item_id}")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_document(
        site_id: str,
        item_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SharePointClient,
            _connector_read_client(request, context, "sharepoint", sharepoint_client, requested_client_id=client_id),
        )
        response = client.get_document(site_id, item_id)
        return _sharepoint_response("documents.get", response)

    @router.get("/connectors/sharepoint/sites/{site_id}/documents/{item_id}/content")
    @limiter.limit(active_settings.rate_limit_connector)
    def sharepoint_document_content(
        site_id: str,
        item_id: str,
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        client = cast(
            SharePointClient,
            _connector_read_client(request, context, "sharepoint", sharepoint_client, requested_client_id=client_id),
        )
        response = client.get_document_content(site_id, item_id)
        return _sharepoint_response("documents.content", response)

    @router.get("/connectors/scalepad/health")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_health(request: Request, _: ViewerAccess) -> dict[str, object]:
        result = scalepad_client.health()
        _audit_scalepad_read("health", result.status, result.count)
        return asdict(result)

    @router.get("/connectors/scalepad/clients")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_client_lookup(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="ScalePad reads require a tenant scope")
        response = scalepad_client.get_client(client_id=scoped_client_id)
        return _scalepad_response("clients.get", response)

    @router.get("/connectors/scalepad/risk-summaries")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_risk_summaries(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(
                status_code=403,
                detail="ScalePad risk-summary reads require a tenant scope",
            )
        response = scalepad_client.get_risk_summary(client_id=scoped_client_id)
        return _scalepad_risk_summary_response("clients.risks-summary", response)

    @router.get("/connectors/scalepad/compliance-health")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_compliance_health(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(
                status_code=403,
                detail="ScalePad compliance-health reads require a tenant scope",
            )
        response = scalepad_client.get_compliance_health(client_id=scoped_client_id)
        return _scalepad_compliance_health_response("clients.health", response)

    @router.get("/connectors/scalepad/goals")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_goals(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        status: str | None = None,
        title: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(
                status_code=403,
                detail="ScalePad Lifecycle goal reads require a tenant scope",
            )
        response = scalepad_client.get_goals(
            client_id=scoped_client_id,
            status=status,
            title=title,
            cursor=cursor,
        )
        return _scalepad_goal_response("lifecycle-manager.goals", response)

    @router.get("/connectors/scalepad/assessments")
    @limiter.limit(active_settings.rate_limit_connector)
    def scalepad_assessments(
        request: Request,
        context: ViewerAccess,
        client_id: str | None = None,
        status: str | None = None,
        assessment_template_id: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, requested_client_from(request, client_id)).client_id
        if scoped_client_id is None:
            raise HTTPException(
                status_code=403,
                detail="ScalePad Lifecycle assessment reads require a tenant scope",
            )
        response = scalepad_client.get_assessments(
            client_id=scoped_client_id,
            status=status,
            assessment_template_id=assessment_template_id,
            cursor=cursor,
        )
        return _scalepad_assessment_response("lifecycle-manager.assessments", response)

    return router


__all__ = ["create_documentation_connectors_router"]
