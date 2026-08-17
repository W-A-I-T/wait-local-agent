# Implementation — `wla-s0-pr3-quarantine-persist` S0-PR3b

## Delivered contract

S0-PR3b items 1–2 are implemented as pre-activation hardening:

- `_QUARANTINE_CLIENT_ID` is the single reserved tenant identifier. Status
  changes, principal client roles, connector-instance creation/rebinding, and
  client-connector mapping creation reject `__quarantine__` with the existing
  reserved-client `ValueError` style.
- Startup integrity checks log one warning per pre-existing role,
  connector-instance, or mapping bound to `__quarantine__`; they do not repair,
  reclassify, or fail startup on upgraded databases.
- `_quarantine_exclusion_predicate` centralizes the parameterized
  `client_id <> ?` filter. AllClients `list_tickets` and `get_ticket` exclude
  quarantine by default, while `include_quarantine=True` and explicit
  `__quarantine__` scope remain available. Ticket analytics apply the same
  exclusion, including both ticket-resolution branches and lifecycle metrics.
- The summary, agent, event-dispatch, and playbook paths were verified to reach
  ticket reads through `get_ticket`; no direct ticket query was added to those
  modules. Provider-ticket ingestion, persistence, and re-tenant behavior are
  unchanged and remain assigned to later PRs.

## Files

- `src/wait_local_agent/store.py`
- `tests/test_wla_s0_quarantine_reserve.py`
- `CHANGELOG.md`
- `ai/tasks/wla-s0-pr3-quarantine-persist/implementation.md`

## S0-PR3c — block operations while quarantined

S0-PR3c items 3–4 are implemented as additive defense-in-depth. No schema or
migration changed, and `ingest_provider_tickets` was not modified.

### Typed error and API mapping

- `Store._require_ticket_not_quarantined(connection, ticket_id)` reads the
  current ticket owner on the transaction connection and raises the exported
  `QuarantinedTicketError(ValueError)` when the owner is the reserved
  `_QUARANTINE_CLIENT_ID` (`__quarantine__`).
- FastAPI registers an explicit `QuarantinedTicketError` handler returning HTTP
  409 with the controlled pending-client-mapping detail. Routes that already
  catch `ValueError` branch on the typed exception first, including technician
  chat session creation, approval payload updates, and approval completion.

### Store guarded-site inventory

The guard runs on the same connection immediately before the dependent write:

- ticket notes;
- technician-chat session creation, session ticket rebinding, session close,
  and message inserts (the session's attached ticket is checked when the
  message omits an explicit ticket). This checkout has no technician-chat
  attachment table or write method, so there is no additional attachment site;
- end-user requester/support message inserts and end-user escalation status
  changes;
- legacy per-ticket approvals;
- ticket-backed approval request creation, approval updates/payload edits, and
  approval execution result writes, resolving the ticket from the persisted
  approval payload where present;
- event-delivery inserts for ticket entities;
- workflow-run inserts;
- agent backfill inserts (all entity IDs) and agent-run inserts;
- pending smart-action approval/run creation when its stored payload contains a
  ticket ID;
- ticket-targeted scheduled-job inserts for workflow/playbook params and agent
  entity IDs.

The guard is intentionally not added to provider-ticket ingestion or any
quarantine persistence/re-tenant path reserved for S0-PR3d.

### Orchestration guarded-site inventory

Each entry loads the target with `include_quarantine=True` before a model,
tool, provider, dispatch, claim, run, or approval side effect:

- `run_workflow_template`: returns an unpersisted `WorkflowRun` with `id=None`;
- approved `SmartActionService.complete_approval` and
  `SmartActionService.update_approval`: resolve the ticket ID from the stored
  original approval payload, including nested smart-action payloads; completion
  returns `None` and does not call `_safe_run`;
- `AgentService.resume`: returns the existing run result before approval
  update/completion;
- HaloPSA, ConnectWise, and M365 approval executors: resolve the ticket ID
  from the stored approval payload (or stored subject fallback) before any
  provider write; API executor routes map the typed error to HTTP 409;
- `EventDispatcher.dispatch`: returns an ephemeral empty result with no
  delivery insert;
- `EventDispatcher.retry`: checks before claiming the delivery and returns
  empty lists while leaving the failed delivery unclaimed;
- `TicketIntelligenceService.summarize`: returns an empty summary before
  retrieval/provider calls;
- `run_msp_playbook`: returns an empty skipped result before audit/run/tool
  work;
- `SchedulerManager` workflow, playbook, and agent jobs: log a warning and
  return before dispatching or executing the target.

Normal-client behavior remains unchanged. Focused coverage is in
`tests/test_wla_s0_block_ops.py`; full `tests/` execution and coverage remain
the responsibility of the release gate.
