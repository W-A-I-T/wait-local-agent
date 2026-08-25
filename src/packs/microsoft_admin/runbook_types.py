"""Contracts for approval-bound Microsoft administrator PowerShell runbooks."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

RUNBOOK_ACTION_TYPE = "microsoft_admin.powershell_runbook"
RUNBOOK_PLAN_FORMAT = "wait.microsoft-admin.powershell-runbook/v1"
MAX_RUNBOOK_OUTPUT_CHARS = 32_768
MAX_CLIENT_ID_LENGTH = 128
MAX_PARAMETER_COUNT = 16
MAX_STRING_PARAMETER_LENGTH = 128

RunbookEffect = Literal["read", "write"]
RunbookParameterKind = Literal["boolean", "integer", "choice"]
RunbookExecutionStatus = Literal["ready", "blocked", "not_configured", "succeeded", "failed"]


class CompletedProcessLike(Protocol):
    """Read-only subprocess result contract used by injectable runbook runners."""

    @property
    def returncode(self) -> int: ...

    @property
    def stdout(self) -> str | None: ...

    @property
    def stderr(self) -> str | None: ...


RunbookRunner = Callable[
    [list[str], Path, float, Mapping[str, str]],
    CompletedProcessLike,
]
ExecutableResolver = Callable[[], str | None]
PlatformPredicate = Callable[[], bool]


class RunbookError(RuntimeError):
    """A runbook definition, plan, or execution failed a deterministic boundary."""


class RunbookApprovalError(RunbookError):
    """A stored runbook approval is missing, stale, or outside the expected tenant."""


@dataclass(frozen=True)
class RunbookParameter:
    name: str
    kind: RunbookParameterKind
    description: str
    default: bool | int | str
    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RunbookDefinition:
    runbook_id: str
    version: str
    title: str
    description: str
    effect: RunbookEffect
    risk_level: int
    timeout_seconds: int
    script: str
    script_sha256: str
    parameters: tuple[RunbookParameter, ...]

    def catalog_view(self) -> dict[str, object]:
        return {
            "runbook_id": self.runbook_id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "effect": self.effect,
            "risk_level": self.risk_level,
            "timeout_seconds": self.timeout_seconds,
            "approval_required": True,
            "script_sha256": f"sha256:{self.script_sha256}",
            "parameters": [parameter.to_dict() for parameter in self.parameters],
        }


@dataclass(frozen=True)
class RunbookRuntimeStatus:
    status: Literal["ready", "blocked", "not_configured"]
    message: str
    executable: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RunbookExecutionResult:
    status: RunbookExecutionStatus
    message: str
    runbook_id: str
    runbook_version: str
    effect: RunbookEffect
    risk_level: int
    plan_digest: str
    script_sha256: str
    exit_code: int | None = None
    output: object = None
    stderr: str = ""
    stdout_truncated: bool = False
    stderr_truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
