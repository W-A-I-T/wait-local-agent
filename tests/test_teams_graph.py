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
