# Hard-coded truth inventory

Reviewed against `origin/main` as checked out for `wla-post60-t07` on 2026-09-03.
The inventory covers the task's required searches and the hard-coded status,
boolean, count, and fallback literals visible on operator-facing surfaces.
`keep` means the value is an input example, an empty/loading presentation, or a
local UI state whose producer is the UI itself; it is not a claim about a
backend-computed result.

## Fix

| Location | Literal | Computed source that replaces it |
| --- | --- | --- |
| `src/wait_local_agent/employee_onboarding_demo.py:233` | `"deployable_source"` | `deployable_package["package_status"]` |
| `src/wait_local_agent/employee_onboarding_demo.py:256-257` | `True`, `"deployable_source"` | package existence and `deployable_package["package_status"]`; expose the package's computed deployability separately |
| `src/wait_local_agent/power_platform_package.py:188-195` | artifact-less/degraded package readiness derived from base classes | artifact component classes plus withheld entity/relationship classes; unsupported artifacts remain separately reported and make an unsupported-only package non-deployable |
| `src/wait_local_agent/power_platform_package.py:452` | `"deployable": True` | validated package `deployable` |
| `src/wait_local_agent/power_platform_package.py:453-454` | missing package readiness/open-item fields | validated package `package_status`, `design_only_components`, and `unsupported_components` |
| `src/wait_local_agent/delivery_plan.py:118-122` | deployable package status is not propagated at plan level | validated package status, deployability, and component lists |
| `src/wait_local_agent/power_platform_package.py:861,997-1044` | dropped entity is absent from readiness accounting | `withheld_entity` component class |
| `src/wait_local_agent/power_platform_package.py:902-927,1068-1147,1166-1179` | dropped lookup/relationship is absent from readiness accounting | `withheld_relationship` component class |
| `ui/src/screens/SolutionDelivery.tsx:459` | `deployable: true · execution_started: false · deployment_started: false` | validation response `deployable`, `package_status`, and component-list counts |
| `ui/src/screens/Consultant.tsx:1274` | `StatusChip status="evidence_partial"` | delivery bundle manifest `deployable` and `bundle_status` |
| `ui/src/app/DashboardContext.tsx:601` | role-only write authorization | `/auth/role.allow_write_actions` and role, including `end_user` |
| `ui/src/api/types.ts:2054` | role union excludes `end_user` | backend role contract |
| `src/wait_local_agent/power_platform_deployment.py:86` | `Build and solution checker` | actual build command: `Build (pac solution pack)` |
| `docs/consultant/consultant-power-platform-deployment.md:11` | `pac solution init`, `pack`, and `check` | current pack-only plan |
| `docs/consultant/power-platform-connectors.md:46-47` | `init`, `pack`, and `check` | current pack-only plan |

## Keep with reason

### Status chips

| Location | Literal | Reason |
| --- | --- | --- |
| `ui/src/screens/Consultant.tsx:1218,1239,1519` | `completed` | Rendered only when the corresponding response object exists; this is a local completion state, not a copied backend result |
| `ui/src/screens/Consultant.tsx:1882,2005` | `review_only` | These artifacts' producers define the surfaces as review-only and no alternate status is returned |
| `ui/src/screens/McpIntegration.tsx:161` | `available` | Static endpoint-publication capability state; no per-response status is exposed by this route |
| `ui/src/screens/McpIntegration.tsx:233` | `pending_approval`, `not_required` | Derived directly from each tool's `approval_required` boolean |
| `ui/src/screens/Settings.tsx:306` | `not_configured` | Fallback for an optional connection absent from the response |
| `ui/src/screens/ConnectorInstances.tsx:1103` | `verified` | Rendered only from the row's `verified === 1` producer value |
| `ui/src/screens/Clients.tsx:513` | `verified` | Rendered only from the mapping's verified value |
| `ui/src/screens/AzureLighthouse.tsx:187` | `blocked` | Local status while the capability response is unavailable; the loaded response uses its own status |

### Nullish fallbacks

| Location | Literal | Reason |
| --- | --- | --- |
| `ui/src/screens/DiagnosticsSupport.tsx:129,229` | `Not recorded`, `Not loaded` | Honest empty/loading display values, not claims about a computed result |
| `ui/src/screens/MicrosoftAdminAccess.tsx:239` | `global` | Display fallback for an unscoped capability grant |
| `ui/src/screens/AgentPlatform.tsx:187,617` | `Selected client`, `unknown` | Label and unavailable-workload fallbacks |
| `ui/src/screens/Playbooks.tsx:506` | `Started` | Run result is absent; the surrounding row already indicates no detailed result |
| `ui/src/screens/Tickets.tsx:79,326,352,367` | `add_note`, `tab`, `entity`, `link` | Input/key defaults needed to keep the local form and graph rendering usable |
| `ui/src/screens/ApplianceHealth.tsx:209,222,278` | `unknown`, `—`, `Not loaded` | Honest missing health/backup values |
| `ui/src/screens/Workflows.tsx:146,151` | `workflow-inputs`, `input` | Stable local form DOM identifiers |
| `ui/src/screens/SolutionDelivery.tsx:451,526` | `digest pending`, `required version` | Empty package digest and unavailable CLI minimum-version display; validation truth is handled separately |
| `ui/src/screens/ScheduledJobs.tsx:204` | `UTC` | Form timezone default when the producer omitted a timezone |
| `ui/src/screens/Agents.tsx:163-196,416,512-517` | form defaults and `unknown`/review labels | Local draft defaults and explicit unavailable/review displays; no producer truth is overwritten |
| `ui/src/screens/McpIntegration.tsx:182` | `Not reported` | Honest absent tool metadata value |
| `ui/src/screens/Settings.tsx:260,264,316-317` | cost/project fallbacks | Optional settings fields are absent; these do not claim a configured value |
| `ui/src/screens/Schedules.tsx:239,242,245,250` | `Not provided` | Honest absent schedule fields |
| `ui/src/screens/Consultant.tsx:687,1699` | request/review fallbacks | Local draft/status presentation when optional producer fields are absent |
| `ui/src/screens/AzureLighthouse.tsx:203,219` | `loading`, `Select a WAIT client` | Local loading and form guidance states |
| `ui/src/screens/MicrosoftAdmin.tsx:920` | `Not recorded` | Honest absent evidence value |
| `ui/src/screens/Overview.tsx:36` | `0` | Empty metric default before the summary response provides a count |

### Other required search hits

| Location | Literal | Reason |
| --- | --- | --- |
| `ui/src/screens/DiagnosticsSupport.tsx:193` | `Support upload is not available in this edition` | Rendered only when `support_upload.available === false`; it describes the producer's explicit capability value |
| `ui/src/screens/ApplianceHealth.tsx:198` | `Update status is not available yet` | Rendered only when the update response is absent; it is an honest unavailable state |
| `ui/src/screens/Consultant.tsx:1222` | `Blueprint detail is not available yet` | Rendered only for the local `empty` load state |
| `ui/src/screens/*` input `placeholder` values | examples and operator guidance | Input examples are not status/count/boolean claims; retain them unless a producer-backed value is being shown |
| `ui/src/components/AutomationDiscoveryPanel.tsx:301`, `ui/src/screens/Analytics.tsx:120` | estimate disclaimers | These explicitly distinguish estimates from measured values |

## Guard scope

`ui/lint/status-literals-allowlist.json` records the retained source literals
with a reason and expected occurrence count. `ui/lint/status-literals.test.ts`
fails for a new `StatusChip status="..."` or `?? "..."` literal in a screen
source file, while allowing the documented local states above. The deliberate
guard test uses `StatusChip status="deliberate_unlisted_status"`; it is not in
the application tree or the allowlist.
