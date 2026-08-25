"""Shared fixtures for the Microsoft administrator pack tests."""

from __future__ import annotations

from dataclasses import replace

from packs.microsoft_admin.core import MicrosoftAdminReadResponse
from wait_local_agent.m365_graph import (
    M365GraphLicenseDetail,
    M365GraphLicenseDetailReadResponse,
    M365GraphManagedDevice,
    M365GraphManagedDeviceReadResponse,
    M365GraphReadResponse,
    M365GraphServicePlan,
    M365GraphUser,
)
from wait_local_agent.models import ConnectorReadResult


def _configured(settings, *, probing: bool = True):
    return replace(
        settings,
        allow_http_probing=probing,
        m365_graph_base_url="https://graph.microsoft.com/v1.0",
        m365_access_token="access-token",
        m365_page_size=25,
    )


def _response(
    items: list[dict[str, object]] | None = None,
    *,
    status: str = "ready",
) -> MicrosoftAdminReadResponse:
    records = items or []
    return MicrosoftAdminReadResponse(
        ConnectorReadResult(status, f"{status} response", len(records)),
        records,
    )


class FakeMicrosoftAdminProvider:
    def __init__(self, responses: dict[str, MicrosoftAdminReadResponse]) -> None:
        self.responses = responses

    def _response(self, name: str) -> MicrosoftAdminReadResponse:
        return self.responses.get(name, _response())

    def list_service_health(self, *, cursor=None, page_size=25):
        return self._response("service_health")

    def list_service_issues(self, *, cursor=None, page_size=25):
        return self._response("service_issues")

    def list_secure_scores(self, *, cursor=None, page_size=1):
        return self._response("secure_scores")

    def list_sign_ins(self, *, identity=None, cursor=None, page_size=25):
        return self._response("sign_ins")

    def list_conditional_access_policies(self, *, cursor=None, page_size=25):
        return self._response("conditional_access")

    def list_risky_users(self, *, cursor=None, page_size=25):
        return self._response("risky_users")

    def list_intune_apps(self, *, cursor=None, page_size=25):
        return self._response("intune_apps")

    def list_compliance_policies(self, *, cursor=None, page_size=25):
        return self._response("compliance_policies")

    def list_autopilot_devices(self, *, cursor=None, page_size=25):
        return self._response("autopilot_devices")

    def list_defender_incidents(self, *, cursor=None, page_size=25):
        return self._response("defender_incidents")

    def list_defender_alerts(self, *, cursor=None, page_size=25):
        return self._response("defender_alerts")


class FakeM365Core:
    def __init__(
        self,
        *,
        users: M365GraphReadResponse | None = None,
        licenses: M365GraphLicenseDetailReadResponse | None = None,
        devices: M365GraphManagedDeviceReadResponse | None = None,
    ) -> None:
        ready = ConnectorReadResult("ready", "ready", 0)
        self.users = users or M365GraphReadResponse(ready, [])
        self.licenses = licenses or M365GraphLicenseDetailReadResponse(ready, [])
        self.devices = devices or M365GraphManagedDeviceReadResponse(ready, [])

    def list_users(self, *, identity=None, cursor=None, page_size=25):
        return self.users

    def list_license_details(self, *, identity, cursor=None, page_size=25):
        return self.licenses

    def list_managed_devices(self, *, cursor=None, page_size=25):
        return self.devices


def _user(*, enabled: bool = True) -> M365GraphUser:
    return M365GraphUser(
        id="user-1",
        display_name="Adele Vance",
        user_principal_name="adele@example.test",
        mail="adele@example.test",
        account_enabled=enabled,
        job_title="Administrator",
        department="IT",
    )


def _license() -> M365GraphLicenseDetail:
    return M365GraphLicenseDetail(
        id="license-1",
        sku_id="11111111-1111-1111-1111-111111111111",
        sku_part_number="ENTERPRISEPACK",
        service_plans=(
            M365GraphServicePlan(
                service_plan_id="plan-1",
                service_plan_name="EXCHANGE_S_ENTERPRISE",
                provisioning_status="Success",
                applies_to="User",
            ),
        ),
    )


def _device(
    *,
    compliance: str = "compliant",
    encrypted: bool | None = True,
    last_sync: str = "2026-08-24T12:00:00Z",
) -> M365GraphManagedDevice:
    return M365GraphManagedDevice(
        id="device-1",
        user_id="user-1",
        device_name="LAPTOP-001",
        owner_type="company",
        enrolled_date_time="2026-01-01T00:00:00Z",
        last_sync_date_time=last_sync,
        operating_system="Windows",
        compliance_state=compliance,
        management_agent="mdm",
        os_version="10.0.26100",
        azure_ad_registered=True,
        device_registration_state="registered",
        is_encrypted=encrypted,
        user_principal_name="adele@example.test",
        user_display_name="Adele Vance",
        model="Latitude",
        manufacturer="Dell",
    )
