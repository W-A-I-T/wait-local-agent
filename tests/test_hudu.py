from __future__ import annotations

from dataclasses import replace

import httpx

from wait_local_agent.hudu import (
    HuduClient,
    _api_base_url,
    _normalize_article,
    _normalize_company,
    _normalize_folder,
    _payload_rows,
    _safe_endpoint,
)


def test_hudu_reads_block_without_http_flag(settings) -> None:
    requests: list[httpx.Request] = []
    active_settings = replace(
        settings,
        hudu_base_url="https://hudu.example.test",
        hudu_api_key="api-key",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    client = HuduClient(
        active_settings,
        transport=httpx.MockTransport(handler),
    )

    health = client.health()
    companies = client.list_companies()

    assert health.status == "blocked"
    assert companies.result.status == "blocked"
    assert requests == []


def test_hudu_reads_report_missing_credentials(settings) -> None:
    active_settings = replace(settings, allow_http_probing=True, hudu_base_url="https://hudu.test")
    client = HuduClient(
        active_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
    )

    response = client.list_articles()

    assert response.result.status == "not_configured"
    assert "WAIT_HUDU_API_KEY" in response.result.message


def test_hudu_reads_send_api_key_and_normalize_payloads(settings) -> None:
    requests: list[httpx.Request] = []
    active_settings = replace(
        settings,
        allow_http_probing=True,
        hudu_base_url="https://hudu.example.test",
        hudu_api_key="api-key",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/companies"):
            return httpx.Response(200, json={"companies": [{"id": 1, "name": "Contoso"}]})
        if request.url.path.endswith("/articles/7"):
            return httpx.Response(
                200,
                json={"id": 7, "name": "Runbook", "company_id": 1, "folder_id": 2},
            )
        return httpx.Response(200, json={"folders": [{"id": 2, "name": "Ops"}]})

    client = HuduClient(active_settings, transport=httpx.MockTransport(handler))

    companies = client.list_companies(page=2, page_size=5)
    article = client.get_article("7")
    folders = client.list_folders(company_id="1")

    assert companies.items[0].name == "Contoso"
    assert article.items[0].id == "7"
    assert folders.items[0].name == "Ops"
    assert requests[0].headers["x-api-key"] == "api-key"
    assert requests[0].url.path == "/api/v1/companies"
    assert requests[0].url.params["page"] == "2"
    assert requests[0].url.params["page_size"] == "5"


def test_hudu_read_errors_are_redacted(settings) -> None:
    active_settings = replace(
        settings,
        allow_http_probing=True,
        hudu_base_url="https://hudu.example.test",
        hudu_api_key="secret-api-key",
    )
    client = HuduClient(
        active_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"secret": "x"})),
    )

    response = client.list_companies()

    assert response.result.status == "failed"
    assert "secret-api-key" not in response.result.message


def test_hudu_health_ready_and_failure_paths(settings) -> None:
    ready_settings = replace(
        settings,
        allow_http_probing=True,
        hudu_base_url="https://hudu.example.test",
        hudu_api_key="api-key",
    )
    ready = HuduClient(
        ready_settings,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"companies": []})
        ),
    ).health()
    failed = HuduClient(
        ready_settings,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"nope")),
    ).health()

    assert ready.status == "ready"
    assert failed.status == "failed"


def test_hudu_timeout_and_helper_edges(settings) -> None:
    active_settings = replace(
        settings,
        allow_http_probing=True,
        hudu_base_url="https://hudu.example.test/api",
        hudu_api_key="api-key",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    response = HuduClient(active_settings, transport=httpx.MockTransport(handler)).list_folders(
        company_id="C-1"
    )

    assert response.result.status == "failed"
    assert _api_base_url("https://hudu.test/api/v1") == "https://hudu.test/api/v1"
    assert _api_base_url("https://hudu.test/api") == "https://hudu.test/api/v1"
    assert _safe_endpoint("/articles/1") == "articles/1"
    try:
        _safe_endpoint("https://evil.test")
    except Exception as exc:
        assert "relative paths" in str(exc)
    assert _payload_rows([{"id": 1}]) == [{"id": 1}]
    assert _payload_rows("bad") == []
    company = _normalize_company({"id": 1, "archived": "true"})
    assert _normalize_company({}) is None
    assert company is not None
    assert company.archived is True
    assert _normalize_article({}) is None
    assert _normalize_folder({}) is None
