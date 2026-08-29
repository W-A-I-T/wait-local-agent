from __future__ import annotations

from typing import cast

import httpx
import pytest

from packs.azure_lighthouse.client import AzureLighthouseClient
from packs.azure_lighthouse.models import (
    MAX_PAGES,
    AzureLighthouseAuthorizationError,
    AzureLighthouseBlockedError,
    AzureLighthouseProviderError,
    AzureLighthouseValidationError,
)
from packs.azure_lighthouse.normalizers import (
    aggregate_status,
    definition_scope,
    normalized_optional_uuid,
    resource_group_from_id,
    scope_from_assignment_id,
    validate_definition_id,
)
from packs.azure_lighthouse.transport import initial_url, validated_next_link
from tests.azure_lighthouse_support import (
    ASSIGNMENT_ID,
    CUSTOMER_TENANT_ID,
    DEFINITION_ID,
    MANAGING_TENANT_ID,
    OTHER_TENANT_ID,
    SUBSCRIPTION_ID,
    FakeCredential,
    configured_settings,
    subscription_payload,
)


@pytest.mark.parametrize(
    ("subscription_payload_override", "expected"),
    [
        (None, "not accessible"),
        (subscription_payload(customer_tenant_id=OTHER_TENANT_ID), "different customer tenant"),
        (subscription_payload(managing_tenant_id=OTHER_TENANT_ID), "not projected"),
    ],
)
def test_inventory_rejects_unverified_subscription_mapping(
    settings,
    subscription_payload_override: dict[str, object] | None,
    expected: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        values = [] if subscription_payload_override is None else [subscription_payload_override]
        return httpx.Response(200, json={"value": values})

    client = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AzureLighthouseAuthorizationError, match=expected):
        client.inventory(
            client_id="client-contoso",
            managing_tenant_id=MANAGING_TENANT_ID,
            expected_customer_tenant_id=CUSTOMER_TENANT_ID,
            subscription_id=SUBSCRIPTION_ID,
        )


def test_inventory_rejects_missing_assignment_and_invalid_limits(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/subscriptions":
            return httpx.Response(200, json={"value": [subscription_payload()]})
        return httpx.Response(200, json={"value": []})

    client = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(AzureLighthouseAuthorizationError, match="not verified"):
        client.inventory(
            client_id="client-contoso",
            managing_tenant_id=MANAGING_TENANT_ID,
            expected_customer_tenant_id=CUSTOMER_TENANT_ID,
            subscription_id=SUBSCRIPTION_ID,
        )
    for invalid in (0, 501, True):
        with pytest.raises(AzureLighthouseValidationError, match="limit"):
            client.inventory(
                client_id="client-contoso",
                managing_tenant_id=MANAGING_TENANT_ID,
                expected_customer_tenant_id=CUSTOMER_TENANT_ID,
                subscription_id=SUBSCRIPTION_ID,
                limit=cast(int, invalid),
            )


def test_client_blocks_live_reads_and_sanitizes_auth_provider_and_json_errors(settings) -> None:
    blocked = AzureLighthouseClient(settings, FakeCredential())
    with pytest.raises(AzureLighthouseBlockedError, match="WAIT_ALLOW_HTTP_PROBING"):
        blocked.discover(
            client_id="client",
            managing_tenant_id=MANAGING_TENANT_ID,
            expected_customer_tenant_id=CUSTOMER_TENANT_ID,
        )

    for status_code, error_type in [
        (401, AzureLighthouseAuthorizationError),
        (403, AzureLighthouseAuthorizationError),
        (500, AzureLighthouseProviderError),
    ]:
        client = AzureLighthouseClient(
            configured_settings(settings),
            FakeCredential(),
            transport=httpx.MockTransport(
                lambda request, code=status_code: httpx.Response(
                    code,
                    json={"error": {"message": "provider-secret"}},
                )
            ),
        )
        with pytest.raises(error_type) as provider_error:
            client.discover(
                client_id="client",
                managing_tenant_id=MANAGING_TENANT_ID,
                expected_customer_tenant_id=CUSTOMER_TENANT_ID,
            )
        assert "provider-secret" not in str(provider_error.value)

    malformed = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"{")),
    )
    with pytest.raises(AzureLighthouseProviderError, match="malformed JSON"):
        malformed.discover(
            client_id="client",
            managing_tenant_id=MANAGING_TENANT_ID,
            expected_customer_tenant_id=CUSTOMER_TENANT_ID,
        )

    payload_cases: list[tuple[object, str]] = [
        ([], "invalid collection"),
        ({}, "missing a value"),
    ]
    for payload, message in payload_cases:
        client = AzureLighthouseClient(
            configured_settings(settings),
            FakeCredential(),
            transport=httpx.MockTransport(lambda request, value=payload: httpx.Response(200, json=value)),
        )
        with pytest.raises(AzureLighthouseProviderError, match=message):
            client.discover(
                client_id="client",
                managing_tenant_id=MANAGING_TENANT_ID,
                expected_customer_tenant_id=CUSTOMER_TENANT_ID,
            )


def test_token_and_transport_failures_are_sanitized(settings) -> None:
    for credential in (FakeCredential(error=RuntimeError("token-secret")), FakeCredential(token="")):
        client = AzureLighthouseClient(
            configured_settings(settings),
            credential,
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"value": []})),
        )
        with pytest.raises(AzureLighthouseAuthorizationError) as auth_error:
            client.discover(
                client_id="client",
                managing_tenant_id=MANAGING_TENANT_ID,
                expected_customer_tenant_id=CUSTOMER_TENANT_ID,
            )
        assert "token-secret" not in str(auth_error.value)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection-secret", request=request)

    client = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(timeout),
    )
    with pytest.raises(AzureLighthouseProviderError, match="before receiving") as transport_error:
        client.discover(
            client_id="client",
            managing_tenant_id=MANAGING_TENANT_ID,
            expected_customer_tenant_id=CUSTOMER_TENANT_ID,
        )
    assert "connection-secret" not in str(transport_error.value)


def test_pagination_is_bounded_and_rejects_untrusted_next_links(settings) -> None:
    page_two = (
        "https://management.azure.com/subscriptions?api-version=2022-12-01&$skiptoken=next"
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if request.url.params.get("$skiptoken") == "next":
            return httpx.Response(200, json={"value": []})
        return httpx.Response(200, json={"value": [], "nextLink": page_two})

    result = AzureLighthouseClient(
        configured_settings(settings),
        FakeCredential(),
        transport=httpx.MockTransport(handler),
    ).discover(
        client_id="client",
        managing_tenant_id=MANAGING_TENANT_ID,
        expected_customer_tenant_id=CUSTOMER_TENANT_ID,
    )
    assert result.status == "ready"
    assert calls == 2

    for next_link in (
        "https://evil.example/subscriptions?api-version=x",
        "http://management.azure.com/subscriptions?api-version=x",
        "https://user:pass@management.azure.com/subscriptions?api-version=x",
        "https://management.azure.com:444/subscriptions?api-version=x",
        "https://management.azure.com/tenants?api-version=x",
        "https://management.azure.com/subscriptions?api-version=x#fragment",
        "https://management.azure.com:invalid/subscriptions?api-version=x",
    ):
        client = AzureLighthouseClient(
            configured_settings(settings),
            FakeCredential(),
            transport=httpx.MockTransport(
                lambda request, link=next_link: httpx.Response(
                    200,
                    json={"value": [], "nextLink": link},
                )
            ),
        )
        with pytest.raises(AzureLighthouseProviderError):
            client.discover(
                client_id="client",
                managing_tenant_id=MANAGING_TENANT_ID,
                expected_customer_tenant_id=CUSTOMER_TENANT_ID,
            )

    looping_credential = FakeCredential()
    looping = AzureLighthouseClient(
        configured_settings(settings),
        looping_credential,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"value": [], "nextLink": page_two},
            )
        ),
    )
    with pytest.raises(AzureLighthouseProviderError, match="page limit"):
        looping.discover(
            client_id="client",
            managing_tenant_id=MANAGING_TENANT_ID,
            expected_customer_tenant_id=CUSTOMER_TENANT_ID,
        )
    assert len(looping_credential.scopes) == MAX_PAGES


def test_internal_scope_helpers_fail_closed() -> None:
    assert initial_url("/subscriptions", {"api-version": "1"}).startswith(
        "https://management.azure.com/subscriptions?"
    )
    for path in ("subscriptions", "/tenants", "/subscriptions?x=1", "/subscriptions\\x"):
        with pytest.raises(AzureLighthouseProviderError):
            initial_url(path, {"api-version": "1"})

    definition = (
        f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.ManagedServices/"
        f"registrationDefinitions/{DEFINITION_ID}"
    )
    assert validate_definition_id(definition) == definition
    assert definition_scope(definition) == f"/subscriptions/{SUBSCRIPTION_ID}"
    group_definition = (
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/app-rg/providers/"
        f"Microsoft.ManagedServices/registrationDefinitions/{DEFINITION_ID}"
    )
    assert validate_definition_id(group_definition) == group_definition
    for invalid in (
        "not-a-path",
        f"/subscriptions/{SUBSCRIPTION_ID}/providers/Other/registrationDefinitions/{DEFINITION_ID}",
        f"/subscriptions/not-guid/providers/Microsoft.ManagedServices/registrationDefinitions/{DEFINITION_ID}",
        (
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/bad./providers/"
            f"Microsoft.ManagedServices/registrationDefinitions/{DEFINITION_ID}"
        ),
        f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.ManagedServices/registrationDefinitions/not-guid",
    ):
        with pytest.raises((AzureLighthouseProviderError, AzureLighthouseValidationError)):
            validate_definition_id(invalid)

    assignment = (
        f"/subscriptions/{SUBSCRIPTION_ID}/providers/Microsoft.ManagedServices/"
        f"registrationAssignments/{ASSIGNMENT_ID}"
    )
    assert scope_from_assignment_id(assignment) == f"/subscriptions/{SUBSCRIPTION_ID}"
    assert scope_from_assignment_id("unrelated") == ""
    assert resource_group_from_id(
        f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/app-rg/providers/X/y"
    ) == "app-rg"
    assert resource_group_from_id("/subscriptions/x/providers/X/y") == ""
    assert normalized_optional_uuid(SUBSCRIPTION_ID.upper()) == SUBSCRIPTION_ID
    assert normalized_optional_uuid(3) == ""
    assert normalized_optional_uuid("invalid") == ""
    assert aggregate_status(True, []) == "ready"
    assert aggregate_status(True, [{"code": "x"}]) == "partial"
    assert aggregate_status(False, [{"code": "x"}]) == "failed"
    assert aggregate_status(False, []) == "ready"
    assert validated_next_link(
        "https://management.azure.com/subscriptions?api-version=1&$skiptoken=a+b"
    ).startswith("https://management.azure.com/subscriptions?")
