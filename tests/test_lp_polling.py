from __future__ import annotations

from wait_local_agent.lp_client import LaunchPassportForbidden, LaunchPassportRateLimited
from wait_local_agent.lp_polling import poll_scan


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeClient:
    def __init__(self, responses: list[object], report: object | None = None) -> None:
        self.responses = responses
        self.report = report
        self.calls = 0

    def get_scan(self, scan_id: str) -> dict[str, object]:
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if not isinstance(response, dict):
            raise AssertionError("fake scan response must be an object")
        return response

    def latest_report(self, project_id: str) -> dict[str, object] | list[object]:
        report = self.report if self.report is not None else {"id": "report-1"}
        return report if isinstance(report, (dict, list)) else {"id": "report-1"}


def _poll(
    client: FakeClient,
    clock: FakeClock,
    *,
    max_duration: float = 3600.0,
    max_attempts: int = 120,
):
    return poll_scan(
        client,
        "project-1",
        "scan-1",
        clock=clock.clock,
        sleep=clock.sleep,
        max_duration=max_duration,
        max_attempts=max_attempts,
    )


def test_poll_uses_backoff_and_fetches_report_on_completion() -> None:
    clock = FakeClock()
    client = FakeClient([{"status": "queued"}, {"status": "running"}, {"status": "completed"}])

    outcome = _poll(client, clock)

    assert outcome.status == "completed"
    assert outcome.report == {"id": "report-1"}
    assert clock.sleeps == [30.0, 60.0, 120.0]
    assert client.calls == 3


def test_poll_stops_on_each_terminal_state_without_fetching_report() -> None:
    for terminal in ("completed", "failed", "canceled"):
        clock = FakeClock()
        client = FakeClient([{"status": terminal}])
        outcome = _poll(client, clock)
        assert outcome.status == terminal
        assert client.calls == 1


def test_poll_honors_retry_after_without_leaking_error_details() -> None:
    clock = FakeClock()
    client = FakeClient(
        [
            LaunchPassportRateLimited("Bearer secret-token", retry_after=120.0),
            {"status": "completed"},
        ]
    )

    outcome = _poll(client, clock)

    assert outcome.status == "completed"
    assert clock.sleeps == [30.0, 120.0]
    assert "secret-token" not in str(outcome.as_dict())


def test_poll_maps_forbidden_to_not_authorized() -> None:
    clock = FakeClock()
    outcome = _poll(FakeClient([LaunchPassportForbidden("Bearer secret-token")]), clock)

    assert outcome.status == "not_authorized"
    assert "secret-token" not in str(outcome.as_dict())


def test_poll_has_bounded_attempts_and_duration() -> None:
    clock = FakeClock()
    client = FakeClient([{"status": "unknown"}] * 20)

    outcome = _poll(client, clock, max_duration=95.0, max_attempts=20)

    assert outcome.status == "timed_out"
    assert outcome.attempts == 2
    assert clock.now == 95.0
