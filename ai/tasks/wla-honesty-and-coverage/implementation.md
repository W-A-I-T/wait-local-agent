# Implementation — wla-honesty-and-coverage

Status: implemented; static validation rerun; awaiting review.

## T7 — Copilot Studio handoff

- `employee_onboarding_demo.py` now keeps Power Apps and Power Automate in
  `review_artifacts` and returns the Copilot Studio plan under the top-level
  `design_handoffs` key.
- The Power Platform packager was not changed. A Copilot plan still falls
  through to `unsupported_components` when supplied directly.
- The consultant demo documentation identifies the Copilot output as a maker
  handoff and states that it is CLI/API-only; `Consultant.tsx` has no Copilot
  Studio UI.

## T8 — Operator prerequisites

- Added technician-only `GET /consultant/power-platform/cli-status`.
- The response combines the existing bounded PAC status probe with the
  server-owned minimum-version result, write/deployment flags, and workspace
  directory existence.
- `SolutionDelivery` loads the status on mount, renders the PAC version and
  permanently unchecked `pac auth` profile/environment row, and retains
  approval block-reason fallback for the two write gates.
- Environment discovery now records a requested-but-not-performed probe when
  HTTP probing is disabled without entering the connector health probe path.

## T9 — Coverage

- Added guided discovery session coverage for automatic blueprint promotion
  from complete evidence, persisted `completed` status, active turns, and the
  turn cap. The completion flow follows each API-provided `next_question`,
  derives valid text/list/boolean answers from `_QUESTION_DEFS`, and has a
  bounded failure path.
- The new end-to-end completion walk found a real product defect: discovery
  emitted `complete`, while the store accepts and persists `completed`. The
  turn route now translates the domain spelling explicitly before persistence;
  the response remains `complete` and finished sessions read back as
  `completed` in `session_status`.
- Added the negative no-probe assertion for disabled HTTP probing.
- Added `/consultant` and `/consultant/solution-delivery` to the production
  browser smoke route list; both use the existing authenticated, exact-heading
  smoke check. The smoke test does not assert delivery gate state from the
  final page in the route loop, because that loop ends on `/settings` and gate
  state is environment-dependent on the live compose stack.

## Constraints and validation

- `pytest` was not run: the task contract says this repository's FastAPI
  `TestClient` fixtures hang in the sandbox.
- The full UI suite was not run during the initial implementation because
  `ui/node_modules` was absent; the focused correction test was run after the
  dependencies became available.
- The follow-up test corrections keep the Copilot Studio format assertion tied
  to the public builder, disclose the real unsupported canvas-app component,
  and distinguish the discovery result status `complete` from the persisted
  session status `completed`.
- Permitted static checks and the public-surface audit are recorded below after
  execution.

## Gate results

- `git diff --check`: passed after the follow-up corrections
- `ruff check .`: passed (`All checks passed!`)
- `mypy src tests`: environment limitation; six pre-existing missing
  `slowapi`/`slowapi.*` stubs in `src/wait_local_agent/api/auth_routes.py` and
  `src/wait_local_agent/api/app.py`. No changed-file typing errors were
  reported.
- `python3 scripts/public_surface_audit.py`: passed
- Manifest JSON parsing and the zero-Copilot-marker check for
  `ui/src/screens/Consultant.tsx`: passed
- `pytest`: deliberately not run per the task contract.
- `npx vitest run src/screens/SolutionDelivery.test.tsx`: passed (1 file, 4
  tests) after scoping the gate assertion.
- The browser spec was not run locally because no compose stack is available
  here.
