from __future__ import annotations

import json
from dataclasses import replace

import httpx

from wait_local_agent.teams_graph import TeamsGraphClient


def _configured(settings, *, allow_http_probing: bool = True):
    return replace(
        settings,
        allow_http_probing=allow_http_probing,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="access-token",
        m365_page_size=25,
    )


def test_teams_reads_are_bounded_and_normalized(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer access-token"
        if request.url.path.endswith("/me/joinedTeams"):
            return httpx.Response(200, json={"value": [{"id": "team-1", "displayName": "Operations"}]})
        if request.url.path.endswith("/teams/team-1/channels"):
            return httpx.Response(
                200, json={"value": [{"id": "channel-1", "displayName": "General", "membershipType": "standard"}]}
            )
        return httpx.Response(
            200,
            json={
                "value": [
                    {
                        "id": "message-1",
                        "body": {"content": "MFA reset token=secret"},
                        "from": {"user": {"displayName": "Adele"}},
                    }
                ]
            },
        )

    client = TeamsGraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    teams = client.list_teams()
    channels = client.list_channels("team-1")
    messages = client.list_messages("team-1", "channel-1")

    assert teams.items[0].display_name == "Operations"
    assert channels.items[0].membership_type == "standard"
    assert messages.items[0].body == "MFA reset token=[redacted]"


def test_teams_send_requires_write_flags_and_does_not_leak_body(settings) -> None:
    blocked = TeamsGraphClient(_configured(settings)).send_message(
        team_id="team-1", channel_id="channel-1", body="secret"
    )
    assert blocked.status == "blocked"

    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = json.loads(request.content)
        return httpx.Response(201, json={"id": "message-2"})

    client = TeamsGraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(handler),
    )
    result = client.send_message(team_id="team-1", channel_id="channel-1", body="approved update")

    assert result.status == "succeeded"
    assert result.remote_id == "message-2"
    assert seen["payload"] == {"body": {"contentType": "text", "content": "approved update"}}


def test_teams_reads_default_to_blocked(settings) -> None:
    assert TeamsGraphClient(settings).list_teams().result.status == "blocked"


def test_teams_validation_configuration_and_remote_failure_paths(settings) -> None:
    client = TeamsGraphClient(_configured(settings), transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    assert client.list_teams(page_size=0).result.status == "failed"
    assert client.list_teams(cursor=" ").result.status == "failed"
    assert client.list_channels(" ").result.status == "failed"
    assert client.list_messages("team", " ").result.status == "failed"
    assert client.list_teams().result.status == "failed"

    missing = TeamsGraphClient(replace(settings, allow_http_probing=True))
    assert missing.list_teams().result.status == "not_configured"
    assert (
        TeamsGraphClient(replace(missing.settings, allow_write_actions=True)).write_health().status
        == "not_configured"
    )
    assert TeamsGraphClient(replace(_configured(settings), allow_write_actions=True)).write_health().status == "ready"


def test_teams_handles_malformed_payloads_missing_message_identity_and_http_errors(settings) -> None:
    def malformed(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    client = TeamsGraphClient(_configured(settings), transport=httpx.MockTransport(malformed))
    assert client.list_teams().result.status == "failed"

    def no_identity(_: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={})

    sender = TeamsGraphClient(
        replace(_configured(settings), allow_write_actions=True),
        transport=httpx.MockTransport(no_identity),
    )
    assert sender.send_message(team_id="team", channel_id="channel", body="hello").status == "failed"
    assert sender.send_message(team_id="team", channel_id="channel", body=" ").status == "failed"


def test_teams_pagination_and_connection_failure_are_bounded(settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/joinedTeams"):
            return httpx.Response(
                200,
                json={
                    "value": [{"id": "team", "displayName": "Team"}, {"displayName": "ignored"}],
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/joinedTeams?$skiptoken=next",
                },
            )
        return httpx.Response(200, json={"value": []})

    client = TeamsGraphClient(_configured(settings), transport=httpx.MockTransport(handler))
    result = client.list_teams(page_size=500)
    assert result.next_cursor == "next"
    assert result.result.count == 1

    def disconnected(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")

    broken = TeamsGraphClient(_configured(settings), transport=httpx.MockTransport(disconnected))
    assert broken.list_teams().result.status == "failed"
