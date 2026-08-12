from __future__ import annotations

from typing import cast

import pytest

from wait_local_agent.power_platform import (
    PowerPlatformConnectorError,
    build_power_platform_connector,
)


def _spec(*, security: dict[str, object] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "swagger": "2.0",
        "info": {
            "title": "WAIT Ticket API",
            "version": "1.0.0",
            "description": "Local ticket API token=not-a-secret",
        },
        "host": "api.example.test",
        "basePath": "/v1/",
        "schemes": ["https"],
        "paths": {
            "/tickets/{ticketId}": {
                "get": {
                    "operationId": "GetTicket",
                    "summary": "Get a ticket",
                    "parameters": [
                        {"name": "ticketId", "in": "path", "required": True, "type": "string"}
                    ],
                    "responses": {"200": {"description": "A ticket"}},
                }
            }
        },
    }
    if security is not None:
        payload["securityDefinitions"] = security
    return payload


def test_factory_generates_redacted_api_key_artifacts() -> None:
    bundle = build_power_platform_connector(
        {
            **_spec(
                security={
                    "api_key": {
                        "type": "apiKey",
                        "name": "X-Api-Key",
                        "in": "header",
                        "description": "token=secret-value",
                    },
                    "secondary": {"type": "basic"},
                }
            ),
            "x-secret": "token=do-not-echo",
        },
        name="WAIT Connector",
        publisher="WAIT Technologies",
        stack_owner="WAIT",
    )

    properties = cast(dict[str, object], bundle["api_properties"])["properties"]
    connection_parameters = cast(dict[str, object], cast(dict[str, object], properties)["connectionParameters"])
    assert bundle["format"] == "wait-local-agent.power-platform-connector"
    assert bundle["auth_type"] == "apiKey"
    assert bundle["operation_count"] == 1
    assert "api_key" in connection_parameters
    assert "secondary" in " ".join(cast(list[str], bundle["warnings"]))
    api_definition = cast(dict[str, object], bundle["api_definition"])
    assert api_definition["basePath"] == "/v1"
    assert api_definition["x-secret"] == "[redacted]"
    assert cast(dict[str, object], api_definition["info"])["description"] == (
        "Local ticket API token=[redacted]"
    )


def test_factory_generates_basic_oauth_and_no_auth_properties() -> None:
    basic = build_power_platform_connector(
        _spec(security={"basic_auth": {"type": "basic"}})
    )
    basic_properties = cast(dict[str, object], cast(dict[str, object], basic["api_properties"])["properties"])
    basic_parameters = cast(dict[str, object], basic_properties["connectionParameters"])
    assert set(basic_parameters) == {"username", "password"}

    oauth = build_power_platform_connector(
        _spec(
            security={
                "entra": {
                    "type": "oauth2",
                    "flow": "accessCode",
                    "authorizationUrl": "https://login.example.test/authorize",
                    "tokenUrl": "https://login.example.test/token",
                    "scopes": {"api.read": "Read API"},
                }
            }
        )
    )
    oauth_properties = cast(dict[str, object], cast(dict[str, object], oauth["api_properties"])["properties"])
    oauth_parameters = cast(dict[str, object], oauth_properties["connectionParameters"])
    oauth_setting = cast(dict[str, object], oauth_parameters["entra"])
    assert oauth["auth_type"] == "oauth2"
    assert cast(dict[str, object], oauth_setting["oAuthSettings"])["clientSecret"] == ""
    assert any("client ID" in warning for warning in cast(list[str], oauth["warnings"]))

    no_auth = build_power_platform_connector(_spec())
    no_auth_properties = cast(dict[str, object], cast(dict[str, object], no_auth["api_properties"])["properties"])
    assert cast(dict[str, object], no_auth_properties["connectionParameters"]) == {}
    assert cast(list[str], no_auth["warnings"])


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda spec: spec.update({"swagger": "3.0"}), "OpenAPI 2.0"),
        (lambda spec: spec.update({"schemes": ["http"]}), "HTTPS only"),
        (lambda spec: spec.update({"host": "https://user:pass@example.test"}), "host"),
        (lambda spec: spec.update({"paths": {}}), "paths must not be empty"),
        (
            lambda spec: spec.update(
                {"paths": {"/tickets": {"get": {"operationId": "GetTicket", "responses": {}}}}}
            ),
            "must define a response",
        ),
        (
            lambda spec: spec.update({"paths": {
                "/tickets": {"get": {"operationId": "not-valid", "responses": {"200": {"description": "ok"}}}}
            }}),
            "operationId is invalid",
        ),
        (
            lambda spec: spec.update({"paths": {
                "/tickets": {
                    "get": {"operationId": "GetTicket", "responses": {"200": {"description": "ok"}}},
                    "post": {"operationId": "GetTicket", "responses": {"200": {"description": "ok"}}},
                }
            }}),
            "operationIds must be unique",
        ),
        (
            lambda spec: spec.update(
                {
                    "paths": {
                        "tickets": {
                            "get": {
                                "operationId": "GetTicket",
                                "responses": {"200": {"description": "ok"}},
                            }
                        }
                    }
                }
            ),
            "path keys",
        ),
        (
            lambda spec: spec.update({"securityDefinitions": {"oauth": {"type": "oauth2", "flow": "application"}}}),
            "application flow",
        ),
        (
            lambda spec: spec.update(
                {
                    "securityDefinitions": {
                        "oauth": {
                            "type": "oauth2",
                            "flow": "implicit",
                            "authorizationUrl": "http://login.example.test",
                        }
                    }
                }
            ),
            "HTTPS URL",
        ),
        (
            lambda spec: spec.update({"securityDefinitions": {"api": {"type": "apiKey", "in": "cookie", "name": "x"}}}),
            "location",
        ),
        (
            lambda spec: spec.update({"$ref": "https://example.test/openapi.json"}),
            "local #/",
        ),
        (lambda spec: spec.update({"info": {"title": "", "version": "1"}}), "info.title"),
        (lambda spec: spec.update({"basePath": "v1"}), "basePath"),
        (lambda spec: spec.update({"paths": {"/x": {"trace": {}}}}), "unsupported method"),
    ],
)
def test_factory_rejects_unsafe_or_unsupported_openapi(mutate, message: str) -> None:
    spec = _spec()
    mutate(spec)

    with pytest.raises(PowerPlatformConnectorError, match=message):
        build_power_platform_connector(spec)


def test_factory_rejects_non_json_and_invalid_metadata() -> None:
    with pytest.raises(PowerPlatformConnectorError, match="must be an object"):
        build_power_platform_connector([])
    with pytest.raises(PowerPlatformConnectorError, match="brand color"):
        build_power_platform_connector(_spec(), icon_brand_color="green")
    with pytest.raises(PowerPlatformConnectorError, match="non-JSON"):
        build_power_platform_connector({**_spec(), "x-value": object()})


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda spec: spec.update({"$ref": "remote"}), "local #/"),
        (lambda spec: spec.update({"x-values": [None] * 513}), "too many items"),
        (lambda spec: spec.update({"x-fields": {str(index): True for index in range(513)}}), "too many fields"),
        (lambda spec: spec.update({"x-text": "x" * 950001}), "too large"),
        (lambda spec: spec.update({"x-nested": _deep_object(26)}), "too deep"),
        (lambda spec: spec.update({"schemes": []}), "non-empty array"),
        (
            lambda spec: spec.update(
                {"paths": {"/tickets": {"parameters": {"unexpected": True}}}}
            ),
            "must be an array",
        ),
        (
            lambda spec: spec.update(
                {
                    "paths": {
                        "/tickets": {
                            "x-note": "extension",
                        }
                    }
                }
            ),
            "at least one operation",
        ),
        (
            lambda spec: spec.update(
                {
                    "paths": {
                        "/tickets": {
                            "get": {
                                "operationId": "GetTicket",
                                "parameters": [{"$ref": "#/parameters/TicketId"}],
                                "responses": {"200": {"$ref": "#/responses/Ticket"}},
                            }
                        }
                    }
                }
            ),
            "",
        ),
        (
            lambda spec: spec.update({"securityDefinitions": {"unsupported": {"type": "cookie"}}}),
            "unsupported auth type",
        ),
        (
            lambda spec: spec.update(
                {
                    "securityDefinitions": {
                        "oauth": {
                            "type": "oauth2",
                            "flow": "implicit",
                            "authorizationUrl": "https://login.example.test/authorize",
                        }
                    }
                }
            ),
            "",
        ),
        (
            lambda spec: spec.update(
                {
                    "securityDefinitions": {
                        "oauth": {
                            "type": "oauth2",
                            "flow": "password",
                            "tokenUrl": "https://login.example.test/token",
                        }
                    }
                }
            ),
            "",
        ),
        (
            lambda spec: spec.update(
                {
                    "securityDefinitions": {
                        "oauth": {"type": "oauth2", "flow": "implicit", "authorizationUrl": "https://login.test"},
                    }
                }
            ),
            "",
        ),
    ],
)
def test_factory_exercises_bounded_defensive_branches(mutate, message: str) -> None:
    spec = _spec()
    mutate(spec)

    if message:
        with pytest.raises(PowerPlatformConnectorError, match=message):
            build_power_platform_connector(spec)
    else:
        bundle = build_power_platform_connector(spec)
        assert bundle["operation_count"] == 1


def _deep_object(depth: int) -> object:
    value: object = True
    for _ in range(depth):
        value = {"child": value}
    return value
