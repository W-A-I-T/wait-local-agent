# Review

- UI-only change; no Python or backend files were modified.
- `selectedClientId` is a new context field with an empty-string All clients
  default. Existing `clientId` consumers remain unchanged.
- `/clients` is classified as `exposed` in the surface manifest because the
  route uses `ViewerAccess`.
- The new directory excludes `__quarantine__`, keeps archived clients visible,
  and offers the requested loading, empty, and retryable error states.
- Existing screens do not consume the DashboardContext `selectedClientId`; its
  adoption remains deferred by the MVP contract.

Claude gate: pending.
