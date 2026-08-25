"""Public facade for governed Microsoft administrator PowerShell runbooks."""

from .runbook_catalog import (
    build_runbook_plan,
    create_runbook_approval,
    runbook_catalog,
    validate_runbook_plan,
)
from .runbook_execution import (
    execute_approved_runbook,
    execute_runbook_plan,
    resolve_powershell_executable,
    runbook_runtime_status,
)
from .runbook_types import (
    RUNBOOK_ACTION_TYPE,
    ExecutableResolver,
    PlatformPredicate,
    RunbookApprovalError,
    RunbookError,
    RunbookExecutionResult,
    RunbookRunner,
    RunbookRuntimeStatus,
)

__all__ = [
    "RUNBOOK_ACTION_TYPE",
    "ExecutableResolver",
    "PlatformPredicate",
    "RunbookApprovalError",
    "RunbookError",
    "RunbookExecutionResult",
    "RunbookRunner",
    "RunbookRuntimeStatus",
    "build_runbook_plan",
    "create_runbook_approval",
    "execute_approved_runbook",
    "execute_runbook_plan",
    "resolve_powershell_executable",
    "runbook_catalog",
    "runbook_runtime_status",
    "validate_runbook_plan",
]
