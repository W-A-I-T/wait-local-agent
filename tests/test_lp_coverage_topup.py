from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import httpx
import pytest
import typer
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from typer.testing import CliRunner

import wait_local_agent.api.founder as founder_module
import wait_local_agent.cli as cli_module
import wait_local_agent.lp_client as lp_client_module
from wait_local_agent.api.founder import FounderPackContractError, create_router
from wait_local_agent.api.packs.loader import LoadedPack
from wait_local_agent.lp_client import (
    LaunchPassportClient,
    LaunchPassportError,
    LaunchPassportForbidden,
    LaunchPassportInsufficientCredits,
    LaunchPassportRateLimited,
    LaunchPassportRequestError,
    LaunchPassportUnauthorized,
)
from wait_local_agent.lp_polling import PollOutcome, poll_scan, poll_scan_once
from wait_local_agent.rbac import Role
from wait_local_agent.scheduler import SchedulerManager
from wait_local_agent.store import Store
from wait_local_agent.update_channel import UpdateStatus


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class PollClient:
    def __init__(self, scans: list[object], report: object = None) -> None:
        self.scans = list(scans)
        self.report = report if report is not None else {"id": "report-1"}
        self.scan_calls = 0
        self.report_calls = 0

    def get_scan(self, scan_id: str) -> dict[str, Any]:
        self.scan_calls += 1
        response = self.scans.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, dict)
        return response

    def latest_report(self, project_id: str) -> dict[str, Any] | list[Any]:
        self.report_calls += 1
        if isinstance(self.report, BaseException):
            raise self.report
        assert isinstance(self.report, (dict, list))
        return self.report


def poll(client: PollClient, clock: Clock, **kwargs: Any):
    return poll_scan(
        client,
        "project-1",
        "scan-1",
        clock=clock.clock,
        sleep=clock.sleep,
        **kwargs,
    )


@pytest.mark.parametrize("terminal", ["completed", "failed", "canceled"])
def test_poll_returns_all_terminal_states_and_only_fetches_report_for_completed(terminal: str) -> None:
    clock = Clock()
    client = PollClient([{"state": terminal}], report=[{"id": "r-1"}])

    outcome = poll(client, clock)

    assert outcome.status == terminal
    assert client.scan_calls == 1
    assert client.report_calls == (1 if terminal == "completed" else 0)
    assert outcome.report == ([{"id": "r-1"}] if terminal == "completed" else None)


@pytest.mark.parametrize(
    ("error", "status", "message"),
    [
        (LaunchPassportUnauthorized("token"), "not_authorized", "not authorized"),
        (LaunchPassportForbidden("token"), "not_authorized", "not authorized"),
        (LaunchPassportInsufficientCredits("credits"), "unavailable", "insufficient"),
        (LaunchPassportError("remote"), "unavailable", "request failed"),
        (RuntimeError("local"), "unavailable", "polling failed"),
    ],
)
def test_poll_never_leaks_remote_or_unexpected_errors(error: Exception, status: str, message: str) -> None:
    outcome = poll(PollClient([error]), Clock())

    assert outcome.status == status
    assert outcome.error is not None and message in outcome.error
    assert "token" not in str(outcome.as_dict())


def test_poll_rate_limit_updates_backoff_and_preserves_retry_metadata() -> None:
    clock = Clock()
    client = PollClient(
        [
            LaunchPassportRateLimited("secret", retry_after=75),
            {"status": "unknown"},
            {"status": "completed"},
        ]
    )

    outcome = poll(client, clock, initial_delay=10, max_delay=100)

    assert outcome.status == "completed"
    assert clock.sleeps == [10, 75, 100]
    assert outcome.retry_after == 75


def test_poll_duration_is_bounded_before_request_and_attempts_are_bounded() -> None:
    clock = Clock()
    outcome = poll(PollClient([{"status": "running"}] * 5), clock, max_duration=5, max_attempts=10)
    assert outcome.status == "timed_out"
    assert outcome.attempts == 0
    assert clock.sleeps == [5]

    clock = Clock()
    outcome = poll(PollClient([{"status": "running"}] * 3), clock, max_attempts=2)
    assert outcome.status == "timed_out"
    assert outcome.attempts == 2


@pytest.mark.parametrize(
    "kwargs",
    [
        {"initial_delay": 0},
        {"max_delay": 0},
        {"max_duration": 0},
        {"max_attempts": 0},
    ],
)
def test_poll_rejects_invalid_bounds(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        poll(PollClient([]), Clock(), **kwargs)


def test_poll_rejects_missing_identifiers_and_reports_unknown_state_on_attempt_limit() -> None:
    with pytest.raises(ValueError, match="project id"):
        poll_scan(PollClient([]), "", "scan-1", clock=Clock().clock, sleep=Clock().sleep)
    with pytest.raises(ValueError, match="scan id"):
        poll_scan(PollClient([]), "project-1", "", clock=Clock().clock, sleep=Clock().sleep)

    clock = Clock()
    outcome = poll(PollClient([{"status": "future"}]), clock, max_attempts=1)
    assert outcome.status == "timed_out"
    assert outcome.error == "Launch Passport returned an unknown scan state"


@pytest.mark.parametrize(
    "error",
    [LaunchPassportUnauthorized("token"), LaunchPassportError("remote"), RuntimeError("local")],
)
def test_poll_report_failures_are_returned_without_raising(error: Exception) -> None:
    client = PollClient([{"status": "completed"}])
    client.report = error
    outcome = poll(client, Clock())
    assert outcome.status == "completed"
    assert outcome.report is None
    expected = (
        "latest report is not authorized"
        if isinstance(error, LaunchPassportUnauthorized)
        else "latest report request failed"
    )
    assert outcome.error == expected


def test_poll_scan_once_rejects_negative_progress() -> None:
    client = PollClient([])
    with pytest.raises(ValueError, match="project id"):
        poll_scan_once(client, "", "scan-1")
    with pytest.raises(ValueError, match="scan id"):
        poll_scan_once(client, "project-1", "")
    with pytest.raises(ValueError, match="must not be negative"):
        poll_scan_once(client, "project-1", "scan-1", attempts=-1)
    with pytest.raises(ValueError, match="must not be negative"):
        poll_scan_once(client, "project-1", "scan-1", elapsed_seconds=-1)


def lp_client(handler):
    return LaunchPassportClient(
        "https://lp.test",
        lambda: "token",
        transport=httpx.MockTransport(handler),
    )


def test_scan_report_and_launch_paths_map_capability_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/scans") and request.method == "GET":
            return httpx.Response(200, json=[{"id": "scan-1"}])
        if request.url.path.endswith("/reports/latest"):
            return httpx.Response(200, json={"reportId": "report-1"})
        return httpx.Response(202, json={"scan": {"scanId": "scan-1", "status": "queued"}})

    with lp_client(handler) as client:
        assert client.list_scans("project-1") == [{"id": "scan-1"}]
        assert client.latest_report("project-1") == {"reportId": "report-1"}
        assert client.launch_scan("project-1")["scan"]["scanId"] == "scan-1"

    for code, expected in [
        (402, "insufficient_credits"),
        (403, "not_authorized"),
        (429, "rate_limited"),
    ]:
        with lp_client(lambda _request, code=code: httpx.Response(code, headers={"Retry-After": "9"})) as client:
            result = client.launch_scan("project-1")
        assert result["status"] == expected
        if code == 429:
            assert result["retry_after"] == 9.0

    with lp_client(lambda _request: httpx.Response(200, json=[])) as client:
        with pytest.raises(LaunchPassportRequestError, match="object payload"):
            client.get_scan("scan-1")
    with pytest.raises(ValueError, match="scan id"):
        LaunchPassportClient._safe_scan_id("bad/scan")


def test_retry_after_accepts_http_date_and_client_maps_post_errors(monkeypatch) -> None:
    retry_at = datetime.now(UTC) + timedelta(seconds=20)
    value = retry_at.strftime("%a, %d %b %Y %H:%M:%S GMT")
    with lp_client(lambda _request: httpx.Response(401)) as client:
        with pytest.raises(LaunchPassportUnauthorized):
            client.launch_scan("project-1")

    with lp_client(lambda _request: httpx.Response(429, headers={"Retry-After": value})) as client:
        with pytest.raises(LaunchPassportRateLimited) as raised:
            client.list_scans("project-1")
    assert raised.value.retry_after is not None and raised.value.retry_after >= 0
    assert lp_client_module._retry_after_seconds(None) is None
    assert lp_client_module._retry_after_seconds("not a date") is None
    assert lp_client_module._retry_after_seconds("Wednesday, 01 Jan 2020 00:00:00") == 0.0
    monkeypatch.setattr("wait_local_agent.lp_client.time.sleep", lambda _seconds: None)


class FakeLP:
    def __init__(self, launch: dict[str, object] | None = None) -> None:
        self.launch = launch or {"scan": {"scanId": "scan-1", "status": "queued"}}

    def __enter__(self) -> FakeLP:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def list_scans(self, project_id: str) -> list[dict[str, str]]:
        return [{"scanId": "scan-1"}]

    def latest_report(self, project_id: str) -> dict[str, str]:
        return {"reportId": "report-1"}

    def status(self) -> dict[str, object]:
        return {"status": "connected", "capabilities": {"launch_scan": False}}

    def launch_scan(self, project_id: str) -> dict[str, object]:
        return self.launch


def configured(settings, tmp_path):
    store = Store(tmp_path / "state.db")
    founder_module.configure_founder(settings, store, "https://lp.test", "project-1", "token")
    return store


def test_founder_results_and_launch_routes_expose_not_authorized_capability(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    monkeypatch.setattr(
        founder_module,
        "_open_client",
        lambda *_args: FakeLP({"status": "not_authorized", "capability": "launch_scan"}),
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.store = store
    router = create_router()
    endpoints = {route.path: route.endpoint for route in router.routes if isinstance(route, APIRoute)}
    request = Request(
        {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "app": app}
    )

    results = endpoints["/founder/results"](request, None)
    launch = endpoints["/founder/launch-scan"](request, None, founder_module.FounderLaunchRequest())

    assert results["capability"]["status"] == "not_authorized"
    assert results["latest_report_reference"] == "report-1"
    assert launch["guidance"].startswith("This token cannot launch")


def test_founder_pack_launch_route_and_remote_error_handler_branches(monkeypatch, settings) -> None:
    module = ModuleType("packs.founder")
    module.launch_scan = lambda: {"status": "pack-launched"}  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(founder_module, "get_pack", lambda _name: pack)
    application = FastAPI()
    application.state.settings = settings
    application.state.store = Store(settings.data_path)
    request = Request(
        {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b"", "app": application}
    )
    endpoints = {route.path: route.endpoint for route in create_router().routes if isinstance(route, APIRoute)}
    endpoint = endpoints["/founder/launch-scan"]
    assert endpoint(request, None, founder_module.FounderLaunchRequest()) == {"status": "pack-launched"}

    for error, code in [
        (LaunchPassportInsufficientCredits("credits"), 402),
        (LaunchPassportRateLimited("slow", retry_after=3), 429),
    ]:
        response = founder_module.launch_passport_error_handler(request, error)
        assert response.status_code == code


def _transport_client(handler) -> LaunchPassportClient:
    return LaunchPassportClient("https://lp.test", lambda: "token", transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("endpoint", "code", "expected"),
    [
        ("scans", 403, {"status": "not_authorized", "capability": "scan_results"}),
        ("reports/latest", 401, {"status": "unavailable", "error": "Launch Passport token was rejected"}),
        ("scans", 402, {"status": "insufficient_credits", "capability": "scan_results"}),
        ("reports/latest", 429, {"status": "rate_limited", "retry_after": 4.0, "capability": "latest_report"}),
        ("scans", 500, {"status": "unavailable", "error": "Launch Passport request failed"}),
    ],
)
def test_founder_results_maps_mocked_transport_errors(monkeypatch, settings, endpoint, code, expected) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(endpoint):
            headers = {"Retry-After": "4"} if code == 429 else {}
            return httpx.Response(code, headers=headers)
        if request.url.path.endswith("/api/health"):
            return httpx.Response(200, json={"capabilities": {"launch_scan": True}})
        return httpx.Response(200, json=[])

    client = _transport_client(handler)
    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: client)
    result = founder_module.open_founder_results(
        settings,
        {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"},
    )
    key = "scans" if endpoint == "scans" else "latest_report"
    assert result[key] == expected
    client.close()


@pytest.mark.parametrize(
    "health_payload",
    [None, {}, {"capabilities": {}}, {"capabilities": {"launch_scan": True}}, {"capabilities": {"launch_scan": False}}],
)
def test_founder_results_reports_each_launch_capability_state(monkeypatch, settings, health_payload) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/health"):
            return httpx.Response(200, json=health_payload if health_payload is not None else [])
        if request.url.path.endswith("/reports/latest"):
            return httpx.Response(200, json={"report": {"id": "report-1"}})
        return httpx.Response(200, json=[{"scanId": "scan-1"}])

    client = _transport_client(handler)
    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: client)
    result = founder_module.open_founder_results(
        settings,
        {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"},
    )
    assert result["latest_report_reference"] == "report-1"
    client.close()


def test_founder_launch_and_watch_persist_remote_state(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    bundle = {"metadata": {"sourceCode": False}}
    store.save_founder_artifact(
        artifact_id="artifact-1", project_id="project-1", bundle_hash="hash", bundle=bundle
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(202, json={"scan": {"scan_id": "scan-1", "state": "queued"}})

    client = _transport_client(handler)
    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: client)
    config = {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"}
    launched = cast(dict[str, object], founder_module.open_founder_launch_scan(settings, store, config, "artifact-1"))
    assert cast(dict[str, object], launched["scan"])["scan_id"] == "scan-1"
    assert store.get_founder_artifact("artifact-1")["remote_scan_id"] == "scan-1"

    outcome = PollOutcome(
        "completed",
        "scan-1",
        1,
        0.1,
        {"scan_id": "scan-1", "state": "completed"},
        {"report": {"id": "r1"}},
    )
    events: list[str] = []

    def advance(*_args: object, **_kwargs: object) -> PollOutcome:
        events.append("advance")
        return outcome

    monkeypatch.setattr(founder_module, "advance_founder_scan_once", advance)
    monkeypatch.setattr(founder_module.time, "sleep", lambda _seconds: events.append("sleep"))
    first_watch = cast(dict[str, object], founder_module.watch_founder_scan(settings, store, config, "scan-1"))
    assert first_watch["status"] == "completed"
    assert events == ["advance"]
    watched = cast(
        dict[str, object],
        founder_module.watch_founder_scan(settings, store, config, "scan-1", artifact_id="artifact-1"),
    )
    assert events == ["advance", "advance"]
    report = cast(dict[str, object], watched["report"])
    assert cast(dict[str, object], report["report"])["id"] == "r1"
    client.close()


def test_founder_watch_advances_before_initial_backoff(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    outcomes = iter(
        [
            PollOutcome("running", "scan-1", 1, 0.1),
            PollOutcome("completed", "scan-1", 2, 0.2),
        ]
    )
    events: list[tuple[str, float | None]] = []

    def advance(*_args: object, **_kwargs: object) -> PollOutcome:
        events.append(("advance", None))
        return next(outcomes)

    monkeypatch.setattr(founder_module, "advance_founder_scan_once", advance)
    monkeypatch.setattr(founder_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    result = founder_module.watch_founder_scan(
        settings,
        store,
        {"lp_project_id": "project-1"},
        "scan-1",
        max_duration=120,
    )

    assert result["status"] == "completed"
    assert events == [("advance", None), ("sleep", 30.0), ("advance", None)]


def test_founder_scheduler_advances_once_and_stops_after_terminal(monkeypatch, settings, tmp_path) -> None:
    runtime_settings = replace(settings, demo_mode=False, scheduler_enabled=True)
    store = Store(tmp_path / "scheduler-founder.db")
    store.save_founder_artifact(
        artifact_id="artifact-1", project_id="project-1", bundle_hash="hash", bundle={"metadata": {}}
    )
    queued_at = datetime.now(UTC).isoformat()
    store.update_founder_artifact_remote(
        "artifact-1",
        scan_id="scan-1",
        polling_status="queued",
        polling_started_at=queued_at,
        next_attempt_at=queued_at,
        polling_attempts=0,
    )

    class PollingClient:
        def __init__(self) -> None:
            self.responses: list[dict[str, object]] = [{"status": "running"}, {"status": "completed"}]
            self.calls = 0

        def __enter__(self) -> PollingClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get_scan(self, scan_id: str) -> dict[str, object]:
            self.calls += 1
            return self.responses.pop(0)

        def latest_report(self, project_id: str) -> dict[str, object]:
            return {"id": "report-1"}

        def status(self) -> dict[str, object]:
            return {"status": "connected", "capabilities": {"launch_scan": True}}

    polling_client = PollingClient()
    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: polling_client)
    monkeypatch.setattr(
        founder_module,
        "resolve_open_config",
        lambda *_args: {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"},
    )
    manager = SchedulerManager(store, enabled=False, settings=runtime_settings)

    manager._run_founder_poll_iteration()  # noqa: SLF001
    artifact = cast(dict[str, object], store.get_founder_artifact("artifact-1"))
    assert artifact["polling_status"] == "running"
    assert artifact["polling_attempts"] == 1

    with store._connect() as connection:  # noqa: SLF001
        connection.execute("update founder_artifacts set next_attempt_at = '' where artifact_id = 'artifact-1'")
    manager._run_founder_poll_iteration()  # noqa: SLF001
    artifact = cast(dict[str, object], store.get_founder_artifact("artifact-1"))
    assert artifact["polling_status"] == "completed"
    assert polling_client.calls == 2
    status = founder_module.open_founder_status(
        runtime_settings,
        {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"},
        store,
    )
    assert status["polling_status"] == "completed"
    assert status["attempts"] == 2
    assert status["last_polled_at"]
    assert status["next_attempt_at"] is None

    monkeypatch.setattr(founder_module.time, "sleep", lambda _seconds: pytest.fail("terminal scans must not wait"))
    watched = founder_module.watch_founder_scan(
        runtime_settings,
        store,
        {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"},
        "scan-1",
        artifact_id="artifact-1",
    )
    assert watched["status"] == "completed"
    assert polling_client.calls == 2

    manager._run_founder_poll_iteration()  # noqa: SLF001
    assert polling_client.calls == 2


def test_founder_watch_retries_claim_contention_and_honors_retry_after(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    outcomes = iter(
        [
            None,
            PollOutcome("retrying", "scan-1", 1, 0.1, retry_after=75),
            PollOutcome("completed", "scan-1", 2, 0.2),
        ]
    )
    events: list[tuple[str, float | None]] = []

    def advance(*_args: object, **_kwargs: object) -> PollOutcome | None:
        events.append(("advance", None))
        return next(outcomes)

    monkeypatch.setattr(founder_module, "advance_founder_scan_once", advance)
    monkeypatch.setattr(founder_module.time, "sleep", lambda seconds: events.append(("sleep", seconds)))

    result = founder_module.watch_founder_scan(
        settings,
        store,
        {"lp_project_id": "project-1"},
        "scan-1",
        max_duration=120,
    )

    assert result["status"] == "completed"
    assert events == [("advance", None), ("sleep", 30.0), ("advance", None), ("sleep", 75), ("advance", None)]


def test_founder_advance_covers_safe_mode_timeout_claim_and_terminal_lookup(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    store.save_founder_artifact(
        artifact_id="artifact-1", project_id="project-1", bundle_hash="hash", bundle={"metadata": {}}
    )
    config = {"lp_project_id": "project-1", "lp_base_url": "https://lp.test", "token_vault_ref": "ref"}

    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: pytest.fail("safe mode must not open a client"))
    safe = founder_module.advance_founder_scan_once(
        replace(settings, demo_mode=True), store, config, "scan-1", artifact_id="artifact-1"
    )
    assert safe is not None and safe.status == "unavailable"
    assert store.get_founder_artifact("artifact-1")["polling_status"] == "unavailable"

    active_settings = replace(settings, demo_mode=False, offline_mode=False)
    store.update_founder_artifact_remote(
        "artifact-1",
        scan_id="scan-1",
        polling_status="queued",
        polling_started_at="not-a-timestamp",
        next_attempt_at="",
        polling_attempts=1,
    )
    timed_out = founder_module.advance_founder_scan_once(
        active_settings, store, config, "scan-1", artifact_id="artifact-1", max_attempts=1
    )
    assert timed_out is not None and timed_out.status == "timed_out"

    store.update_founder_artifact_remote(
        "artifact-1", polling_status="queued", polling_started_at="", polling_attempts=0
    )
    monkeypatch.setattr(store, "claim_founder_artifact_poll", lambda *_args, **_kwargs: False)
    assert founder_module.advance_founder_scan_once(
        active_settings, store, config, "scan-1", artifact_id="artifact-1"
    ) is None

    store.update_founder_artifact_remote(
        "artifact-1",
        polling_status="completed",
        polling_started_at="2026-08-01T00:00:00",
        polling_attempts=4,
        scan={"status": "completed"},
        report=[{"id": "report-1"}],
        polling_error="",
    )
    terminal = founder_module.advance_founder_scan_once(active_settings, store, config, "scan-1")
    assert terminal is not None and terminal.status == "completed"
    assert terminal.attempts == 4
    assert terminal.report == [{"id": "report-1"}]
    assert founder_module._parse_timestamp("2026-08-01T00:00:00") is not None
    assert founder_module._parse_timestamp("2026-08-01T00:00:00+00:00") is not None
    assert founder_module._parse_timestamp("bad") is None
    assert founder_module._optional_timestamp("") is None
    assert founder_module._optional_timestamp("2026-08-01") == "2026-08-01"


def test_founder_advance_marks_timeout_after_final_active_request(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    store.save_founder_artifact(
        artifact_id="artifact-1", project_id="project-1", bundle_hash="hash", bundle={"metadata": {}}
    )
    store.update_founder_artifact_remote(
        "artifact-1", scan_id="scan-1", polling_status="queued", polling_started_at="", polling_attempts=0
    )

    class RunningClient:
        def __enter__(self) -> RunningClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def get_scan(self, _scan_id: str) -> dict[str, object]:
            return {"status": "running"}

    monkeypatch.setattr(founder_module, "_open_client", lambda *_args: RunningClient())
    outcome = founder_module.advance_founder_scan_once(
        replace(settings, demo_mode=False, offline_mode=False),
        store,
        {"lp_project_id": "project-1"},
        "scan-1",
        artifact_id="artifact-1",
        max_attempts=1,
    )
    assert outcome is not None and outcome.status == "timed_out"
    assert store.get_founder_artifact("artifact-1")["polling_status"] == "timed_out"


def test_founder_payload_and_report_helpers_cover_fallback_shapes() -> None:
    assert founder_module._scan_id_from_payload({"scan": {"id": "nested"}}) == "nested"
    assert founder_module._scan_id_from_payload({"scan_id": "top-level"}) == "top-level"
    assert founder_module._scan_status_from_payload({"status": "RUNNING"}) == "running"
    assert founder_module._scan_status_from_payload({"scan": {"state": "DONE"}}) == "done"
    assert founder_module._report_reference(["not-a-dict"]) == ""
    assert founder_module._report_reference({"report": {"id": "nested-report"}}) == "nested-report"
    assert founder_module._launch_capability({"capabilities": {"scan:launch": True}})["status"] == "available"


def test_founder_cli_results_and_launch_watch_paths(monkeypatch, settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    runner = CliRunner()
    monkeypatch.setattr(cli_module, "_founder_pack_or_none", lambda: None)
    monkeypatch.setattr(cli_module, "_open_cli_config", lambda: (settings, store, {"lp_project_id": "project-1"}))
    monkeypatch.setattr(cli_module, "open_founder_results", lambda *_args: {"scans": [{"scanId": "scan-1"}]})
    monkeypatch.setattr(cli_module, "open_founder_launch_scan", lambda *_args: {"scanId": "scan-1"})
    monkeypatch.setattr(cli_module, "watch_founder_scan", lambda *_args, **_kwargs: {"status": "completed"})

    results = runner.invoke(cli_module.app, ["founder", "results", "--watch", "--max-attempts", "2"])
    launch = runner.invoke(cli_module.app, ["founder", "launch-scan", "--watch", "--artifact-id", "a1"])

    assert results.exit_code == 0 and '"status": "completed"' in results.output
    assert launch.exit_code == 0 and '"status": "completed"' in launch.output


def test_founder_cli_error_paths_and_pack_launch(monkeypatch, settings, tmp_path) -> None:
    runner = CliRunner()
    monkeypatch.setattr(
        cli_module,
        "_open_cli_config",
        lambda: (settings, Store(tmp_path / "cli.db"), {"lp_project_id": "p"}),
    )
    monkeypatch.setattr(cli_module, "_founder_pack_or_none", lambda: None)
    monkeypatch.setattr(cli_module, "open_founder_results", lambda *_args: {"scans": []})
    no_result_scan = runner.invoke(cli_module.app, ["founder", "results", "--watch"])
    assert no_result_scan.exit_code != 0 and "no scan id" in no_result_scan.output

    monkeypatch.setattr(cli_module, "open_founder_launch_scan", lambda *_args: {"status": "queued"})
    no_launch_scan = runner.invoke(cli_module.app, ["founder", "launch-scan", "--watch"])
    assert no_launch_scan.exit_code != 0 and "did not return a scan id" in no_launch_scan.output

    module = ModuleType("packs.founder")
    module.launch_scan = lambda: {"status": "pack"}  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(cli_module, "_founder_pack_or_none", lambda: pack)
    packed = runner.invoke(cli_module.app, ["founder", "launch-scan"])
    assert packed.exit_code == 0 and '"status": "pack"' in packed.output
    assert cli_module._scan_id_from_response({"scan": {"scanId": "nested-scan"}}) == "nested-scan"
    assert cli_module._scan_id_from_response({"scan": {"id": "nested-scan"}}) == "nested-scan"


def test_founder_cli_helpers_cover_doctor_and_open_config_errors(monkeypatch, settings, tmp_path) -> None:
    module = ModuleType("packs.founder")
    module.get_lp_status = lambda: {"connected": True}  # type: ignore[attr-defined]
    pack = LoadedPack(manifest={"name": "founder"}, module=module)
    monkeypatch.setattr(cli_module, "_founder_pack_or_none", lambda: pack)
    assert cli_module._doctor_founder_lp_status() == '{"connected": true}'
    monkeypatch.setattr(
        cli_module,
        "invoke_founder",
        lambda *_args: (_ for _ in ()).throw(FounderPackContractError("bad")),
    )
    assert cli_module._doctor_founder_lp_status() == "contract_error"

    monkeypatch.setattr(cli_module, "load_settings", lambda: settings)
    monkeypatch.setattr(cli_module, "_store", lambda: Store(tmp_path / "unconfigured.db"))
    with pytest.raises(typer.Exit):
        cli_module._open_cli_config()


def test_cli_edge_helpers_cover_requested_error_and_format_branches(monkeypatch, settings, tmp_path) -> None:
    monkeypatch.setenv("WAIT_DEMO_MODE", "true")
    # The CLI adapter only translates FastAPI auth failures; use the real exception type for that branch.
    monkeypatch.setattr(
        cli_module,
        "resolve_auth_context",
        lambda *_args: (_ for _ in ()).throw(cli_module.HTTPException(status_code=401, detail="bad token")),
    )
    with pytest.raises(typer.BadParameter):
        cli_module._cli_access(settings, "wrong", Role.ADMIN)
    monkeypatch.setattr(cli_module, "resolve_auth_context", lambda *_args: SimpleNamespace(role=Role.VIEWER))
    with pytest.raises(typer.BadParameter, match="insufficient role"):
        cli_module._cli_access(settings, "token", Role.ADMIN)
    assert cli_module._cli_access(settings, "token", Role.VIEWER).role == Role.VIEWER
    assert cli_module._load_json_config(None) == {}
    config_path = tmp_path / "collector.json"
    config_path.write_text('{"enabled": true}', encoding="utf-8")
    assert cli_module._load_json_config(config_path) == {"enabled": True}
    with pytest.raises(typer.BadParameter, match="JSON object"):
        bad_config = tmp_path / "bad.json"
        bad_config.write_text("[]", encoding="utf-8")
        cli_module._load_json_config(bad_config)
    assert cli_module._load_smart_action_payload(None) == {}
    assert cli_module._load_smart_action_payload('{"action": "safe"}') == {"action": "safe"}
    with pytest.raises(typer.BadParameter, match="payload must be a JSON object or JSON file"):
        cli_module._load_smart_action_payload("not-json")
    with pytest.raises(typer.BadParameter, match="JSON object"):
        cli_module._load_smart_action_payload("[]")

    class Collector:
        def export_report(self, *_args):
            return SimpleNamespace(id="report-1")

    class Report:
        def export_report(self, *_args):
            return "rendered report"

    monkeypatch.setattr(cli_module, "_collector_service", lambda: Collector())
    monkeypatch.setattr(cli_module, "ReportService", lambda *_args: Report())
    monkeypatch.setattr(cli_module, "_store", lambda: Store(tmp_path / "reports.db"))
    with pytest.raises(typer.BadParameter):
        cli_module._export_collector_report(1, "invalid", None, "json")
    cli_module._export_collector_report(1, "collector_bundle", None, "json")
    output = tmp_path / "reports" / "report.md"
    cli_module._export_collector_report(1, "collector_bundle", output, "markdown")
    assert output.read_text(encoding="utf-8") == "rendered report"

    monkeypatch.setattr(Collector, "export_report", lambda *_args: (_ for _ in ()).throw(KeyError("missing")))
    with pytest.raises(typer.BadParameter, match="run not found"):
        cli_module._export_collector_report(1, "collector_bundle", None, "json")

    assert "update_available" in cli_module._format_update_status(
        UpdateStatus("update_available", "1", "now", remote_version="2", notes_url="https://example.test")
    )
    assert "up_to_date" in cli_module._format_update_status(UpdateStatus("up_to_date", "1", "now", remote_version="1"))
    assert "invalid_signature" in cli_module._format_update_status(UpdateStatus("invalid_signature", "1", "now"))
    assert "unknown" in cli_module._format_update_status(UpdateStatus("unknown", "1", "now", detail="offline"))

    served: dict[str, object] = {}
    monkeypatch.setattr(
        cli_module,
        "uvicorn",
        SimpleNamespace(run=lambda *args, **kwargs: served.update(args=args, kwargs=kwargs)),
    )
    cli_module.serve("127.0.0.1", 9999)
    assert cast(dict[str, object], served["kwargs"])["port"] == 9999

    monkeypatch.setattr(
        cli_module,
        "sync_pack_cli",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("discovery")),
    )
    cli_module._sync_pack_cli_on_startup()


def test_store_persists_founder_remote_scan_columns(settings, tmp_path) -> None:
    store = configured(settings, tmp_path)
    store.save_founder_artifact(
        artifact_id="artifact-1",
        project_id="project-1",
        bundle_hash="hash",
        bundle={"metadata": {"sourceCode": False}},
    )
    store.update_founder_artifact_remote(
        "artifact-1",
        scan_id="scan-1",
        scan_status="completed",
        scan={"id": "scan-1", "status": "completed"},
        report_reference="report-1",
        report=[{"id": "report-1"}],
        polling_status="completed",
    )

    artifact = store.get_founder_artifact("artifact-1")
    assert artifact is not None
    assert artifact["remote_scan_id"] == "scan-1"
    assert artifact["remote_scan_status"] == "completed"
    assert artifact["remote_scan"] == {"id": "scan-1", "status": "completed"}
    assert artifact["latest_report_reference"] == "report-1"
    assert artifact["latest_report"] == [{"id": "report-1"}]
    assert artifact["polling_status"] == "completed"
