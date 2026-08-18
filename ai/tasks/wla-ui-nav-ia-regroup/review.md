# Review: Sidebar IA regroup

## Findings

- All current sidebar destinations remain represented with their original
  `to` values.
- The only navigation label change is `Consultant` to `Solutions Architect`;
  `/consultant` is unchanged.
- Admin-only destinations remain individually protected by `RoleGate` with
  `allowed={["admin"]}`.
- The advanced drawer uses native `<details>/<summary>` behavior, is closed
  by default, requires no JavaScript, and retains keyboard toggling.
- The new test covers group labels, every destination path, the renamed link,
  collapsed drawer behavior, and viewer/admin visibility.

## Security and edge-case review

- No auth, role resolution, route, API, data, secret, or persistence code was
  changed.
- Viewer rendering omits all five admin-only links while retaining the six
  non-admin advanced links.
- The root link keeps `end` matching so `/` does not remain active on every
  route; all other active-link behavior is unchanged.
- The drawer content remains in the document while collapsed, allowing native
  browser disclosure behavior without state or redirect logic.

## Remaining risk

The requested browser-level visual sign-off has not been performed in this
implementation session. The owner should expand System / Advanced and inspect
the rendered nav before merge, as requested by the plan.
