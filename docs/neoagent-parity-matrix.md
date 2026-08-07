# NeoAgent parity matrix

This is a clean-room capability matrix. It compares publicly documented
capability classes with the behavior verified in this repository; it is not a
claim of source, API, wording, or implementation compatibility. The public
NeoAgent documentation is used only as a feature-class reference.

| Capability class | WAIT already has | Partial | Missing | Smallest next implementation |
| --- | --- | --- | --- | --- |
| Bounded agent runtime | Explicit tool allowlists, eight-step cap, timeout, approval pause, redaction, tenant scope, persisted runs | Event context now reaches the same executor | Unrestricted planning and chat | Add narrowly scoped context selection and final-result presentation |
| Tool catalog | Existing smart actions exposed with schemas, risk, role, approval, and access mode | Connector/collector capabilities are not all catalog entries | Complete connector tool coverage | Wrap one existing read capability at a time |
| Agent definitions | SQLite definitions with enable/disable, trigger, filters, tools, steps, scope, version counter, immutable revision snapshots, and restore-as-new-version | `manual`, `scheduled`, and `event` triggers | Execution windows and run-to-version links | Add execution windows and link runs to revision snapshots |
| Event triggers | Authenticated ticket event ingestion, deterministic filters, idempotency, audit, run-once-per-entity | Supported event vocabulary is intentionally small | Vendor-native webhook adapters and retry queue | Add source validation and bounded retry policy |
| Scheduled workflows | SQLite + APScheduler, cron schedules, pause/resume/delete, workflow and agent targets | Five-field cron only | Interval, one-time, reschedule, execution windows/timezones | Extend the existing schedule record and trigger abstraction |
| Dependencies/chaining | Existing workflow and agent run records | No dependency records | Wait-for-completion and workflow-finished chaining | Add one dependency relation with cycle prevention |
| Templates | Fixed public workflow catalog and editable agent definitions | No gallery persistence | Provenance-bearing template gallery | Persist reviewed local template copies |
| MSP intelligence | Triage, summary, resolution suggestion, similarity, dispatch suggestion, stale/follow-up workflow primitives | QA, sentiment, SLA, merge, onboarding/offboarding are not unified tools | Broader MSP action catalog | Wrap existing deterministic capabilities before adding models |
| Human approval | Preview, edit, approve/reject, approver identity, gated HaloPSA writes, audit | Expiration and per-agent policy are incomplete | General approval policy editor | Add expiry and policy fields to existing approval records |
| PSA | HaloPSA reads and approval-gated writes | Shared connector patterns exist | ConnectWise, Autotask, Syncro, ServiceNow | Prove a thin read-only adapter with fakes |
| RMM | Local endpoint collectors | No RMM adapter | NinjaOne, Datto, ConnectWise, N-able, ScreenConnect, Kaseya | Define a read-only RMM interface and one adapter |
| Documentation | Local knowledge ingestion/search and Hudu reads | Company scoping exists in local records | IT Glue, Confluence, SharePoint adapters | Add one read-only adapter behind existing provider patterns |
| Microsoft 365 | Code-level adapter groundwork | Not exposed as operator tools | Identity, groups, licenses, mailbox, Intune actions | Expose read-only identity lookup first |
| Communication | Approval-gated connector drafts and ticket actions | No common outbound communication interface | Email, Teams, Slack, SMS adapters | Define preview-first message capability |
| Technician teammate | Run-now APIs, tool catalog, execution and approval history | No conversational surface | Technician chat | Reuse runtime through a bounded command surface |
| End-user support | Tenant and approval primitives | No end-user mode | White-label end-user agent | Add after technician surface and safe-tool policy |
| Backfills | Normal execution records can be reused | No preflight or batch controller | Count, pause/resume/cancel, failed-item reruns | Add a bounded backfill record and sequential worker |
| Versioning | Agent `version` increments on update; redacted revision history and restore-as-new-version are API-accessible | No revision diff or run-to-version link | Revision diff and run identity linked to the exact snapshot | Add explainable diff and run-to-version links |
| Observability | Runs, steps, artifacts, approvals, audit, redaction, analytics foundations | Trigger context is still compact | Provider metadata and richer retry/cancel history | Extend existing execution records, not a new engine |
| Analytics | Local execution counts, outcomes, duration, estimated time saved, client filters | Workflow/agent activity can be joined but is not a dedicated dashboard | Tickets resolved, approval rate, per-workflow views | Add explainable aggregates to existing analytics |
| API | FastAPI CRUD, run, approval, execution, tools, schedules, event deliveries | Retry/cancel/backfill/version APIs incomplete | Full parity API surface | Add each capability with tenant/RBAC tests |
| Voice/phone | None by design | None | Voice adapter and caller validation | Defer until core agent and connector paths are stable |

The matrix intentionally keeps missing functionality visible. A row moves to
“already has” only when an operator can exercise it through the public API,
CLI, or dashboard and tests cover the relevant safety boundaries.
