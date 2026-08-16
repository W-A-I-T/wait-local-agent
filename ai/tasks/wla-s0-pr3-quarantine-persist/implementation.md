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
