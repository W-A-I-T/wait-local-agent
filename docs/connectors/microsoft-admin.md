# Microsoft Cloud and Endpoint Administrator pack

The built-in `microsoft-admin` pack adds bounded Microsoft 365, Entra, Intune,
and Microsoft Defender read, diagnostic, and approval-bound endpoint runbook
capabilities to the MSP / IT Operations stream. It mounts automatically at
`/packs/microsoft-admin` and adds a `microsoft-admin` CLI group.

The pack reuses the existing Microsoft Graph configuration and safety boundary:

```text
WAIT_M365_GRAPH_BASE_URL=https://graph.microsoft.com/v1.0
WAIT_M365_ACCESS_TOKEN=
WAIT_M365_PAGE_SIZE=25
WAIT_ALLOW_HTTP_PROBING=true
```

`WAIT_ALLOW_HTTP_PROBING` remains off by default. The pack does not acquire or
refresh tokens, store tenant credentials, or execute arbitrary Graph paths.
Production requests use the shared DNS-pinned outbound transport. Graph paths,
selected fields where supported, page sizes, and pagination keys are
allowlisted. Defender incidents and alerts use only their documented bounded
list parameters.

## Microsoft Graph read surfaces

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
can recommend an existing core action, but it cannot bypass the core approval
and write-gate path.

## Governed PowerShell runbooks

The pack also contains a fixed-script PowerShell runbook engine for local
Windows endpoint operations. This is not an arbitrary shell or script runner.
An operator can select only a versioned runbook in the compiled catalog and can
supply only its schema-validated parameters.

The initial catalog contains:

| Runbook ID | Effect | Risk | Scope |
| --- | --- | ---: | --- |
| `windows.endpoint_health` | Read | 1 | Windows/OS, selected service state, BitLocker posture without recovery keys, TPM state, pending reboot indicators, and bounded critical/error event metadata without event messages |
| `windows.service_restart` | Write | 3 | Restart and verify only `IntuneManagementExtension`, `wuauserv`, or `BITS` |

Both runbooks require a stored approval. The read runbook is also
approval-bound because it executes local PowerShell and can collect endpoint
operational evidence. Execution additionally requires:

```text
WAIT_ALLOW_WRITE_ACTIONS=true
```

The runtime then requires all of the following before invoking PowerShell:

1. Non-demo mode.
2. A Windows host.
3. A locally resolved absolute `pwsh.exe` or `powershell.exe` regular file.
4. One explicit tenant scope.
5. An approved, unexecuted WAIT approval whose stored payload exactly matches
   the current runbook definition.
6. Matching plan and embedded-script SHA-256 digests.
7. Private, per-execution script and input files under the appliance data
   directory.

The subprocess receives a fixed argument vector with `shell=False`. Callers
cannot provide script text, a script path, an executable path, command-line
switches, environment variables, or credentials. Only a small host-environment
allowlist is inherited. Standard output and error are bounded and redacted, the
result must be JSON with the approved runbook identity and target, and the
execution result is persisted into the approval audit trail. Temporary files
are removed after execution.

Runbook API routes:

```text
GET  /packs/microsoft-admin/runbooks
GET  /packs/microsoft-admin/runbooks/status
POST /packs/microsoft-admin/runbooks/plan
POST /packs/microsoft-admin/runbooks/drafts
POST /packs/microsoft-admin/runbooks/approvals/{request_id}/execute
```

`plan` and `drafts` require technician access. Execution requires administrator
access and an approval that has already been approved through the shared WAIT
approval surface. An approval is single-use. A blocked or missing runtime
prerequisite does not consume the approval; an attempted provider execution is
recorded as succeeded or failed with bounded evidence.

The CLI provides catalog, prerequisite-status, and plan-generation commands.
It deliberately does not provide a bypass that directly executes a runbook.

## Least-privilege Microsoft permissions

Grant only the permissions needed for the Graph surfaces enabled in a
deployment. The existing per-user license-detail lookup requires a delegated
token; when an app-only token is used, that source remains explicitly
failed/partial rather than being treated as empty evidence.

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

Recommendations point to existing approval-gated actions such as Intune sync,
session revocation, license change, authentication-method removal, user
disable, and device retirement. The operator still creates and approves the
corresponding core action through the existing WAIT workflow.

## Explicit boundaries

This increment has fixture/mock validation but does **not** claim live Microsoft
tenant or live Windows fleet verification. It does not add:

- arbitrary PowerShell, caller-supplied scripts, or general shell execution;
- Exchange Online or Purview runbook catalogs;
- automatic Conditional Access modification;
- device wipe;
- arbitrary Intune application upload or assignment;
- Defender containment mutations;
- Azure Contributor operations;
- Windows Server, AD, GPO, DNS, DHCP, PKI, firewall, VPN, or backup writes.

Those capabilities require separate allowlisted contracts, approval policy,
rollback evidence, tenant-scoped credentials, and live-provider validation
before they can be represented as shipped.
