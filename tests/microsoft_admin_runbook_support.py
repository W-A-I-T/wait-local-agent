"""Shared fixtures for Microsoft administrator runbook tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from wait_local_agent.models import ApprovalRequest


def _execution_settings(settings, tmp_path: Path):
    return replace(
        settings,
        data_path=tmp_path / "state.db",
        allow_write_actions=True,
        demo_mode=False,
        client_id="client-1",
        admin_token="admin-token",
        tech_token="tech-token",
        viewer_token="viewer-token",
        api_token="",
    )


def _fake_powershell(tmp_path: Path) -> str:
    executable = tmp_path / "pwsh.exe"
    executable.write_bytes(b"fixed-test-executable")
    return str(executable.resolve())


class FakeRunbookStore:
    def __init__(self) -> None:
        self.next_id = 1
        self.approvals: dict[int, ApprovalRequest] = {}
        self.recorded: list[dict[str, object]] = []
        self.audit: list[tuple[str, str, str]] = []

    def create_approval_request(
        self,
        subject_id: str,
        action_type: str,
        payload: dict[str, object],
        *,
        client_id: str | None = None,
        expires_in_seconds: int = 86_400,
    ) -> ApprovalRequest:
        request = ApprovalRequest(
            id=self.next_id,
            subject_id=subject_id,
            action_type=action_type,
            payload_json=json.dumps(payload, sort_keys=True),
            status="pending",
            comment="",
            created_at="2026-08-25T00:00:00+00:00",
            updated_at="2026-08-25T00:00:00+00:00",
            execution_status="not_started",
            execution_message="",
            executed_at="",
            execution_result_json="{}",
            client_id=client_id,
            approver_id=None,
            expires_at="2026-08-26T00:00:00+00:00",
        )
        self.approvals[request.id] = request
        self.next_id += 1
        return request

    def get_approval_request(self, request_id: int) -> ApprovalRequest | None:
        return self.approvals.get(request_id)

    def record_approval_execution(
        self,
        request_id: int,
        *,
        status: str,
        message: str,
        result: dict[str, object],
        audit_event_type: str = "halopsa.write",
    ) -> ApprovalRequest:
        current = self.approvals[request_id]
        updated = replace(
            current,
            execution_status=cast(Any, status),
            execution_message=message,
            executed_at="2026-08-25T01:00:00+00:00",
            execution_result_json=json.dumps(result, sort_keys=True),
            updated_at="2026-08-25T01:00:00+00:00",
        )
        self.approvals[request_id] = updated
        self.recorded.append(
            {
                "status": status,
                "message": message,
                "result": result,
                "audit_event_type": audit_event_type,
            }
        )
        return updated

    def add_audit_event(self, event_type: str, entity_id: str, status: str) -> None:
        self.audit.append((event_type, entity_id, status))
