from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

import wait_local_agent.api.app as app_module
from tests.api_helpers import _hudu_response
from wait_local_agent.api.app import create_app
from wait_local_agent.confluence import ConfluencePage, ConfluenceReadResponse
from wait_local_agent.itglue import (
    ItGlueDocument,
    ItGlueFolder,
    ItGlueOrganization,
    ItGlueReadResponse,
)
from wait_local_agent.models import (
    ConnectorReadResult,
    HaloReadResult,
    HuduArticle,
    HuduCompany,
    HuduFolder,
)
from wait_local_agent.notion import NotionDataSource, NotionDataSourceResponse, NotionPage, NotionReadResponse
from wait_local_agent.sharepoint import SharePointDocument, SharePointReadResponse, SharePointSite


def test_hudu_api_surfaces_blocked_and_mocked_reads(settings, monkeypatch) -> None:
    class FakeHuduClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return HaloReadResult("ready", "ok", 0)

        def list_companies(self, page: int = 1, page_size: int | None = None):
            return _hudu_response([HuduCompany("C-1", "Contoso", False)])

        def list_articles(
            self,
            company_id: str | None = None,
            page: int = 1,
            page_size: int | None = None,
        ):
            return _hudu_response([
                HuduArticle("A-1", "Runbook", "C-1", "F-1", "", "", "token=secret"),
            ])

        def get_article(self, article_id: str):
            return _hudu_response([
                HuduArticle(article_id, "Runbook", "C-1", "F-1", "", "", "token=secret"),
            ])

        def list_folders(
            self,
            company_id: str | None = None,
            page: int = 1,
            page_size: int | None = None,
        ):
            return _hudu_response([HuduFolder("F-1", "Ops", "C-1", "")])

    blocked = TestClient(create_app(settings)).get("/connectors/hudu/health")
    monkeypatch.setattr(app_module, "HuduClient", FakeHuduClient)
    client = TestClient(app_module.create_app(settings))

    health = client.get("/connectors/hudu/health")
    companies = client.get("/connectors/hudu/companies")
    articles = client.get("/connectors/hudu/articles")
    article = client.get("/connectors/hudu/articles/A-1")
    folders = client.get("/connectors/hudu/folders")
    audit = client.get("/audit")

    assert blocked.json()["status"] == "blocked"
    assert health.json()["status"] == "ready"
    assert companies.json()["items"][0]["name"] == "Contoso"
    assert articles.json()["items"][0]["name"] == "Runbook"
    assert articles.json()["items"][0]["content"] == "token=[redacted]"
    assert article.json()["items"][0]["id"] == "A-1"
    assert article.json()["items"][0]["content"] == "token=[redacted]"
    assert folders.json()["items"][0]["name"] == "Ops"
    assert any(event["event_type"] == "hudu.read" for event in audit.json())

def test_itglue_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeItGlueClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "IT Glue ready", 0)

        def list_organizations(self, **kwargs):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ItGlueOrganization("1", "Contoso", "active")],
            )

        def list_documents(self, organization_id, **kwargs):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ItGlueDocument("9", "Runbook", organization_id, "7", "today", "https://docs.test/9", "token=secret")],
            )

        def get_document(self, document_id):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", "document ready", 1),
                [ItGlueDocument(document_id, "Runbook", "1", "7", "today", "https://docs.test/9", "token=secret")],
            )

        def list_folders(self, organization_id, **kwargs):
            return ItGlueReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ItGlueFolder("7", "Ops", organization_id, "0")],
            )

    monkeypatch.setattr(app_module, "ItGlueClient", FakeItGlueClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/itglue/health")
    organizations = client.get("/connectors/itglue/organizations")
    documents = client.get(
        "/connectors/itglue/organizations/1/documents",
        params={"folder_id": "7"},
    )
    document = client.get("/connectors/itglue/documents/9")
    folders = client.get("/connectors/itglue/organizations/1/folders")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert organizations.json()["items"][0]["name"] == "Contoso"
    assert documents.json()["items"][0]["name"] == "Runbook"
    assert documents.json()["items"][0]["content"] == "token=[redacted]"
    assert document.json()["items"][0]["id"] == "9"
    assert document.json()["items"][0]["content"] == "token=[redacted]"
    assert folders.json()["items"][0]["name"] == "Ops"
    assert any(connector["id"] == "itglue" for connector in connectors.json())
    assert any(event["event_type"] == "itglue.read" for event in audit.json())

def test_itglue_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/itglue/health")
    assert response.status_code == 401

def test_confluence_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeConfluenceClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Confluence ready", 0)

        def list_pages(self, **kwargs):
            return ConfluenceReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [ConfluencePage("9", "Runbook", "42", "current", "3", "today", "/page/9", "token=secret")],
            )

        def get_page(self, page_id):
            return ConfluenceReadResponse(
                ConnectorReadResult("ready", "page ready", 1),
                [ConfluencePage(page_id, "Runbook", "42", "current", "3", "today", "/page/9", "token=secret")],
            )

    monkeypatch.setattr(app_module, "ConfluenceClient", FakeConfluenceClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/confluence/health")
    pages = client.get(
        "/connectors/confluence/pages",
        params={"space_id": "42", "title": "Runbook", "cursor": "next", "page_size": 2},
    )
    page = client.get("/connectors/confluence/pages/9")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert pages.json()["items"][0]["title"] == "Runbook"
    assert pages.json()["items"][0]["body"] == "token=[redacted]"
    assert page.json()["items"][0]["id"] == "9"
    assert page.json()["items"][0]["body"] == "token=[redacted]"
    assert any(connector["id"] == "confluence" for connector in connectors.json())
    assert any(event["event_type"] == "confluence.read" for event in audit.json())

def test_confluence_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/confluence/health")
    assert response.status_code == 401

def test_notion_connector_routes_are_tenant_scoped_and_audited(settings, monkeypatch) -> None:
    class FakeNotionClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "Notion ready", 0)

        def search_pages(self, **kwargs):
            return NotionReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [NotionPage("11111111-2222-3333-4444-555555555555", "MFA", "/mfa", "today", False, "body")],
            )

        def get_page(self, page_id, *, client_id):
            return NotionReadResponse(
                ConnectorReadResult("ready", "page ready", 1),
                [NotionPage(page_id, "MFA", "/mfa", "today", False, "token=secret")],
            )

        def query_data_source(self, data_source_id, *, client_id, page_size, start_cursor):
            return NotionReadResponse(
                ConnectorReadResult("ready", str(data_source_id), 1),
                [NotionPage("11111111-2222-3333-4444-555555555555", "MFA", "/mfa", "today", False, "")],
                "next-cursor",
            )

        def get_data_source(self, data_source_id, *, client_id):
            return NotionDataSourceResponse(
                ConnectorReadResult("ready", str(data_source_id), 1),
                [NotionDataSource(data_source_id, {"Name": "title"})],
            )

    monkeypatch.setattr(app_module, "NotionClient", FakeNotionClient)
    client = TestClient(create_app(settings))

    missing_scope = client.get("/connectors/notion/pages", params={"query": "MFA"})
    missing_data_source_scope = client.get(
        "/connectors/notion/data-sources/66666666-7777-8888-9999-000000000000"
    )
    health = client.get("/connectors/notion/health")
    pages = client.get(
        "/connectors/notion/pages",
        params={"client_id": "acme", "query": "MFA", "page_size": 2},
    )
    page = client.get(
        "/connectors/notion/pages/11111111-2222-3333-4444-555555555555",
        params={"client_id": "acme"},
    )
    data_source_pages = client.get(
        "/connectors/notion/data-sources/66666666-7777-8888-9999-000000000000/pages",
        params={"client_id": "acme", "page_size": 2, "start_cursor": "cursor"},
    )
    data_source = client.get(
        "/connectors/notion/data-sources/66666666-7777-8888-9999-000000000000",
        params={"client_id": "acme"},
    )
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert missing_scope.status_code == 403
    assert missing_data_source_scope.status_code == 403
    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert pages.json()["items"][0]["title"] == "MFA"
    assert page.json()["items"][0]["markdown"] == "token=[redacted]"
    assert data_source_pages.status_code == 200
    assert data_source_pages.json()["next_cursor"] == "next-cursor"
    assert data_source.status_code == 200
    assert data_source.json()["items"][0]["properties"] == {"Name": "title"}
    assert any(connector["id"] == "notion" for connector in connectors.json())
    assert any(event["event_type"] == "notion.read" for event in audit.json())

def test_notion_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/notion/health")
    assert response.status_code == 401

def test_sharepoint_connector_read_routes_and_audit(settings, monkeypatch) -> None:
    class FakeSharePointClient:
        def __init__(self, _settings) -> None:
            pass

        def health(self):
            return ConnectorReadResult("ready", "SharePoint ready", 0)

        def list_sites(self, **kwargs):
            return SharePointReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [SharePointSite("site-1", "ops", "Operations", "https://sharepoint.test/ops")],
            )

        def get_site(self, site_id):
            return SharePointReadResponse(
                ConnectorReadResult("ready", "site ready", 1),
                [SharePointSite(site_id, "ops", "Operations", "https://sharepoint.test/ops")],
            )

        def list_documents(self, site_id, **kwargs):
            return SharePointReadResponse(
                ConnectorReadResult("ready", str(kwargs), 1),
                [SharePointDocument("file-1", "MFA.md", site_id, "root", 42, "today", "/mfa", False)],
            )

        def get_document(self, site_id, item_id):
            return SharePointReadResponse(
                ConnectorReadResult("ready", "document ready", 1),
                [SharePointDocument(item_id, "MFA.md", site_id, "root", 42, "today", "/mfa", False)],
            )

        def get_document_content(self, site_id, item_id):
            return SharePointReadResponse(
                ConnectorReadResult("ready", "content ready", 1),
                [SharePointDocument(
                    item_id, "MFA.md", site_id, "root", 42, "today", "/mfa", False, True,
                    "token=secret",
                )],
            )

    monkeypatch.setattr(app_module, "SharePointClient", FakeSharePointClient)
    client = TestClient(create_app(settings))

    health = client.get("/connectors/sharepoint/health")
    sites = client.get("/connectors/sharepoint/sites")
    site = client.get("/connectors/sharepoint/sites/site-1")
    documents = client.get("/connectors/sharepoint/sites/site-1/documents")
    document = client.get("/connectors/sharepoint/sites/site-1/documents/file-1")
    content = client.get("/connectors/sharepoint/sites/site-1/documents/file-1/content")
    connectors = client.get("/connectors")
    audit = client.get("/audit")

    assert health.status_code == 200
    assert health.json()["status"] == "ready"
    assert sites.json()["items"][0]["display_name"] == "Operations"
    assert site.json()["items"][0]["id"] == "site-1"
    assert documents.json()["items"][0]["name"] == "MFA.md"
    assert document.json()["items"][0]["id"] == "file-1"
    assert content.json()["items"][0]["content"] == "token=[redacted]"
    assert any(connector["id"] == "sharepoint" for connector in connectors.json())
    assert any(event["event_type"] == "sharepoint.read" for event in audit.json())

def test_sharepoint_routes_keep_viewer_auth_boundary(settings) -> None:
    settings = replace(settings, demo_mode=False, admin_token="admin-token", viewer_token="viewer-secret")
    response = TestClient(create_app(settings)).get("/connectors/sharepoint/health")
    assert response.status_code == 401
