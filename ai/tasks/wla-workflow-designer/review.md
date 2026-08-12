# Workflow Designer safety review

## Verdict

Approved as a design-only slice, subject to the remaining validation results.

## Safety checks

- Graph input is treated as untrusted data and normalized server-side.
- Node identifiers, labels, tool IDs, configs, edge references, graph shape,
  and serialized size are bounded.
- Secret-like values are redacted through existing report redaction helpers
  before persistence, API response, export, and revision snapshots.
- Existing gallery routes retain technician write and viewer read boundaries,
  including tenant scoping.
- Saving and restoring a design perform no provider calls and do not execute a
  workflow.

## Deferred risks

Runtime node binding, connector authorization, Power Platform/custom connector
export, autonomous execution, and provider failure handling are intentionally
not included. Those capabilities require separate approval, tenancy, and
security-path coverage before they can be enabled.
