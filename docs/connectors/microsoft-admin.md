# Microsoft Cloud and Endpoint Administrator pack

The built-in `microsoft-admin` pack adds bounded Microsoft 365, Entra, Intune,
and Microsoft Defender **read and diagnostic** capabilities to the MSP / IT
Operations stream. It mounts automatically at `/packs/microsoft-admin` and adds
a `microsoft-admin` CLI group.

The pack reuses the existing Microsoft Graph configuration and safety boundary:

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

`WAIT_ALLOW_HTTP_PROBING` remains off by default. The pack does not acquire or
refresh tokens, store tenant credentials, execute arbitrary Graph paths, or
interpret a successful read as proof that a later remediation succeeded.
Production requests use the shared DNS-pinned outbound transport. Graph paths,
selected fields where the endpoint supports them, page sizes, and pagination
keys are allowlisted. Defender incidents and alerts use only the documented
`$top`, `$skip`, and next-link pagination options.

## Read surfaces

| Area | Microsoft Graph surface | Purpose |
| --- | --- | --- |
| Microsoft 365 | Service health overviews and issues | Correlate outages before tenant-side changes |
| Security | Secure Score | Posture context; never represented as compliance evidence |
| Entra | Sign-ins | Recent bounded authentication and Conditional Access outcomes |
| Entra | Conditional Access policies | Policy inventory and enforcement-state review |
| Entra | Risky users | Identity Protection risk context |
| Intune | Mobile applications | Managed application inventory |
| Intune | Device compliance policies | Compliance-policy inventory |
| Intune | Windows Autopilot identities | Enrollment-state inventory without serial-number output |
| Defender XDR | Incidents and alerts v2 | Active security workload and severity context |
| Existing M365 connector | Users, licenses, and managed devices | Cross-surface access diagnostics |

The API exposes:

```text
GET  /packs/microsoft-admin/status
GET  /packs/microsoft-admin/dashboard
GET  /packs/microsoft-admin/service-health
GET  /packs/microsoft-admin/service-issues
GET  /packs/microsoft-admin/security/secure-score
GET  /packs/microsoft-admin/security/incidents
GET  /packs/microsoft-admin/security/alerts
GET  /packs/microsoft-admin/identity/sign-ins
GET  /packs/microsoft-admin/identity/conditional-access
GET  /packs/microsoft-admin/identity/risky-users
GET  /packs/microsoft-admin/endpoint/apps
GET  /packs/microsoft-admin/endpoint/compliance-policies
GET  /packs/microsoft-admin/endpoint/autopilot
POST /packs/microsoft-admin/diagnostics/access
GET  /packs/microsoft-admin/remediations
```

All pack routes inherit the runtime's viewer-or-higher authentication boundary.
The access diagnostic correlates only evidence returned by authorized reads. It
can recommend an existing core action, but it cannot execute that action.

## Least-privilege application permissions

Grant only the permissions needed for the surfaces enabled in a deployment. The existing per-user license-detail lookup requires a delegated token; when an app-only token is used, that source remains explicitly failed/partial rather than being treated as empty evidence:

| Surface | Least-privilege permission / token requirement |
| --- | --- |
| Service health | `ServiceHealth.Read.All` |
| Secure Score | `SecurityEvents.Read.All` |
| Defender incidents | `SecurityIncident.Read.All` |
| Defender alerts v2 | `SecurityAlert.Read.All` |
| Sign-ins | `AuditLog.Read.All` |
| Conditional Access | `Policy.Read.All` |
| Risky users | `IdentityRiskyUser.Read.All` |
| Intune applications | `DeviceManagementApps.Read.All` |
| Intune compliance policies | `DeviceManagementConfiguration.Read.All` |
| Windows Autopilot | `DeviceManagementServiceConfig.Read.All` |
| Existing managed-device evidence | `DeviceManagementManagedDevices.Read.All` |
| Existing user evidence | `User.Read.All` |
| Existing per-user license-detail evidence | Delegated `LicenseAssignment.Read.All`; application permissions are not supported by this endpoint |

Do not grant `Directory.ReadWrite.All`, Global Administrator, Contributor,
Owner, or role-management permissions for these read surfaces.

## Dashboard and access diagnostic

The dashboard produces deterministic counts and recommendations from service,
identity, endpoint, and Defender evidence. It preserves per-source `ready`,
`partial`, `blocked`, `not_configured`, and `failed` states instead of turning a
missing permission or provider failure into an empty healthy result.

The access diagnostic accepts a user identity and optional device name. It may
identify evidence such as:

- disabled account or missing license details;
- recent sign-in or Conditional Access failure;
- elevated user risk;
- noncompliant or unencrypted managed device;
- a relevant active Microsoft service issue.

Recommendations point to the existing approval-gated actions such as Intune
sync, session revocation, license change, authentication-method removal, user
disable, and device retirement. The operator still creates and approves the
corresponding core action through the existing WAIT workflow.

## Explicit boundaries

This increment does **not** claim live-provider verification and does not add:

- unrestricted PowerShell or shell execution;
- automatic Conditional Access modification;
- device wipe;
- arbitrary Intune application upload or assignment;
- Defender containment mutations;
- Azure Contributor operations;
- Windows Server, AD, GPO, DNS, DHCP, PKI, firewall, VPN, or backup writes.

Those mutations require separate, allowlisted contracts, approval policy,
rollback evidence, tenant-scoped credentials, and live-provider validation
before they can be represented as shipped.
