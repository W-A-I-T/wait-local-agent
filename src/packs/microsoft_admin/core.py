"""Public facade for the Microsoft administrator pack implementation."""

from .client import MicrosoftAdminGraphClient
from .insights import build_dashboard, diagnose_access, remediation_catalog
from .models import (
    DEFAULT_PAGE_SIZE,
    MAX_CURSOR_LENGTH,
    MAX_IDENTITY_LENGTH,
    MAX_PAGE_SIZE,
    MAX_RECORDS_PER_SURFACE,
    MicrosoftAdminDiagnostic,
    MicrosoftAdminError,
    MicrosoftAdminFinding,
    MicrosoftAdminProvider,
    MicrosoftAdminReadResponse,
)

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_CURSOR_LENGTH",
    "MAX_IDENTITY_LENGTH",
    "MAX_PAGE_SIZE",
    "MAX_RECORDS_PER_SURFACE",
    "MicrosoftAdminDiagnostic",
    "MicrosoftAdminError",
    "MicrosoftAdminFinding",
    "MicrosoftAdminGraphClient",
    "MicrosoftAdminProvider",
    "MicrosoftAdminReadResponse",
    "build_dashboard",
    "diagnose_access",
    "remediation_catalog",
]
