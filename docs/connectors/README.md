# Connector Matrix

This matrix is derived from the 14 `ConnectorStatus` entries returned by
`src/wait_local_agent/connectors.py`. Fixture status means repository tests or
mocked transport exercise the bounded contract. Live status means a real
provider was verified in this repository; no live provider verification is
claimed for this matrix.

| ID / connector | Read surface | Approval-gated writes | Verification |
| --- | --- | --- | --- |
| `halopsa` / HaloPSA | tickets, notes, clients, assets, categories | ticket notes/status/assignment/allowlisted fields | fixture: covered; live: not verified |
| `hudu` / Hudu | companies, articles, folders | none | fixture: covered; live: not verified |
| `itglue` / IT Glue | organizations, documents, folders, bounded content | none | fixture: covered; live: not verified |
| `confluence` / Confluence Cloud | bounded page listing and detail | none | fixture: covered; live: not verified |
| `notion` / Notion | mapped pages, Markdown, data-source metadata/rows | bounded page comment | fixture: covered; live: not verified |
| `sharepoint` / SharePoint | sites, document-library metadata, bounded content | none | fixture: covered; live: not verified |
| `connectwise` / ConnectWise PSA | tickets and companies | allowlisted ticket updates | fixture: covered; live: not verified |
| `syncro` / Syncro | tickets, comments, customers | one tenant-scoped ticket note | fixture: covered; live: not verified |
| `servicenow` / ServiceNow | incidents and companies | work note, state, assignment, resolution metadata | fixture: covered; live: not verified |
| `autotask` / Autotask PSA | tickets and companies | notes, time entries, status, resolution, assignment | fixture: covered; live: not verified |
| `m365` / Microsoft 365 / Entra | users, groups, licenses, mail metadata, managed devices | allowlisted identity, mailbox, message, group, license, session, and device actions | fixture: covered; live: not verified |
| `timezest` / TimeZest | mapped scheduling requests | documented scheduling-request create | fixture: covered; live: not verified |
| `scalepad` / ScalePad | mapped Core, risk, compliance, lifecycle reads | none | fixture: covered; live: not verified |
| `rmm` / configured RMM adapter | configured NinjaOne, Datto, N-central, N-sight, Kaseya, or ScreenConnect bounded surfaces | adapter-specific approved actions; local RMM remains blocked | fixture: covered; live: not verified |

All outbound calls require `WAIT_ALLOW_HTTP_PROBING=true`. Mutations also
require `WAIT_ALLOW_WRITE_ACTIONS=true` and the applicable approval flow.
The default Power Platform output is a credential-free source package for a
later operator-run `pac solution pack`. Provider import and rollback are
available only when both `WAIT_ALLOW_WRITE_ACTIONS` and
`WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT` are enabled and an approved stage
request exists; see the [Power Platform deployment stages](../consultant/consultant-power-platform-deployment.md)
documentation.

Provider setup pages: [HaloPSA](halopsa.md), [NinjaOne](ninjaone.md),
[Datto](datto-rmm.md), [N-central](ncentral.md), [N-sight](nsight.md),
[TimeZest](timezest.md), [ScalePad](scalepad.md), [Kaseya](kaseya-vsa-x.md),
[ScreenConnect](screenconnect.md), [Hudu](hudu.md), [IT Glue](itglue.md),
[Confluence](confluence.md), [Notion](notion.md), [SharePoint](sharepoint.md),
[Microsoft 365](m365.md), [ConnectWise](connectwise.md), [Syncro](syncro.md),
[ServiceNow](servicenow.md), and [Autotask](autotask.md).
