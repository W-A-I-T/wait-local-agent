from __future__ import annotations

import pytest

from wait_local_agent import (
    autotask,
    communication,
    confluence,
    connectwise,
    dattormm,
    halopsa,
    hudu,
    itglue,
    kaseya,
    lp_client,
    m365_graph,
    ncentral,
    ninjaone,
    notion,
    nsight,
    screenconnect,
    servicenow,
    sharepoint,
    syncro,
    teams_graph,
    timezest,
)

_VALIDATORS = (
    ("NinjaOne", lambda allow: ninjaone._safe_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    (
        "TimeZest",
        lambda allow: timezest._endpoint_url(
            "http://provider.example.test", "v1/scheduling_requests", allow_insecure_transport=allow
        ),
    ),
    ("Autotask", lambda allow: autotask._safe_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    (
        "Confluence",
        lambda allow: confluence._safe_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "Datto RMM",
        lambda allow: dattormm._safe_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    ("IT Glue", lambda allow: itglue._safe_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    ("Kaseya", lambda allow: kaseya._safe_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    (
        "Microsoft Graph",
        lambda allow: m365_graph._api_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "N-central",
        lambda allow: ncentral._safe_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    ("Notion", lambda allow: notion._api_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    ("N-sight", lambda allow: nsight._api_url("http://provider.example.test", allow_insecure_transport=allow)),
    (
        "ScreenConnect base",
        lambda allow: screenconnect._safe_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "ScreenConnect origin",
        lambda allow: screenconnect._safe_origin("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "ServiceNow",
        lambda allow: servicenow._safe_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "SharePoint",
        lambda allow: sharepoint._safe_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    ("Syncro", lambda allow: syncro._safe_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    (
        "Teams Graph",
        lambda allow: teams_graph._api_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "Communication",
        lambda allow: communication._safe_http_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
    (
        "Launch Passport",
        lambda allow: lp_client.validate_launch_passport_base_url(
            "http://provider.example.test", allow_insecure_transport=allow
        ),
    ),
    ("HaloPSA", lambda allow: halopsa._api_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    ("Hudu", lambda allow: hudu._api_base_url("http://provider.example.test", allow_insecure_transport=allow)),
    (
        "ConnectWise",
        lambda allow: connectwise._api_base_url("http://provider.example.test", allow_insecure_transport=allow),
    ),
)


@pytest.mark.parametrize(("provider", "validator"), _VALIDATORS)
def test_non_loopback_plain_http_is_rejected_with_provider_guidance(provider, validator) -> None:
    with pytest.raises(Exception, match="WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT") as error:
        validator(False)
    assert "NetSecurityError" not in type(error.value).__name__
    assert provider


@pytest.mark.parametrize(("provider", "validator"), _VALIDATORS)
def test_insecure_transport_opt_in_reaches_every_provider_validator(provider, validator) -> None:
    validator(True)
    assert provider
