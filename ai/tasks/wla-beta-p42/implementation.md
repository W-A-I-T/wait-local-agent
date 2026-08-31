# Implementation Notes

## Summary

- Added the routed `Solution delivery` screen and Solutions navigation entry.
- Exposed the existing Power Platform pipeline as Package -> Validate ->
  Materialize -> Deployment approvals -> Rollback approval. The screen keeps
  package, validation, materialization, plan, and approval responses visible
  without starting provider work itself.
- Added both Power Platform approval execute mappings and backend
  `block_reason` hints in the shared Approvals card. The old no-manual-execute
  note is therefore shown only for genuinely unmapped action types.
- Added Solutions Architect and Approvals cross-links, plus focused tests for
  endpoint mapping, block-reason rendering, request bodies, gate rendering,
  confirmation flows, and rollback evidence.

## Verified request models

- `POST /consultant/power-platform/package`: `client_id`, `solution_name`,
  `publisher_name`, `publisher_prefix`, `output_directory`, `artifacts`, and
  `connector_artifacts`.
- `POST /consultant/power-platform/package/validate` and
  `POST /consultant/power-platform/package/materialize`: optional
  `client_id` plus the complete `package` object. Materialization is
  admin-only; its response reports `status`, `message`, `package_digest`,
  `materialization_directory`, `files`, `file_count`, and `pac_plan` on
  success, with `execution_started: false` and `deployment_started: false`.
- `POST /consultant/solutions/deployment-approvals`: `client_id`,
  `solution_name`, `publisher_name`, `publisher_prefix`, `output_directory`,
  ordered `deployment_targets` objects containing `name` and
  `environment_url`, `stage` (`build|dev|test|prod`), and
  `promotion_evidence`. The response contains `approval` and `plan`.
- `POST /consultant/solutions/rollback-approvals`: `client_id`, solution and
  publisher fields, `output_directory`, ordered `deployment_targets`, stage
  (`dev|test|prod`), `rollback_artifact_path`, and
  `rollback_evidence` containing `available`, `strategy`, and
  `artifact_digest`. The response contains `approval` and `plan`.
- Execute paths are `/consultant/solutions/deployment-approvals/{id}/execute`
  and `/consultant/solutions/rollback-approvals/{id}/execute`; the approval
  feed action types are `power_platform.solution_stage` and
  `power_platform.solution_rollback`.

## Commands Run

- `npm ci` (from `ui`): passed; 141 packages installed, audit found 0
  vulnerabilities.
- `npm test -- --run src/app/__tests__/executeEndpointFor.test.ts
  src/screens/__tests__/Approvals.test.tsx
  src/screens/SolutionDelivery.test.tsx`: passed, 3 files / 24 tests.
- `npm test -- --run` (from `ui`): passed twice, 65 files / 342 tests each
  run.
- `npm run build` (from `ui`): passed with the existing Vite config-native
  warning and existing large-chunk warning.
- `git diff --check`: passed.
- `npm ls --depth=0`: verified the lockfile-installed compatible toolchain,
  including Vite 8.2.2, React 19.2.8, React Router 7.18.2, TypeScript 7.0.2,
  Vitest 4.1.11, and Playwright 1.62.1. `npm outdated --json` could not
  complete against the registry in this environment; no dependency or API
  version was changed, and `ui/package-lock.json` remains unchanged.

## Files Touched

- `ui/src/screens/SolutionDelivery.tsx`
- `ui/src/screens/SolutionDelivery.test.tsx`
- `ui/src/app/DashboardContext.tsx`
- `ui/src/screens/Approvals.tsx`
- `ui/src/api/types.ts`
- `ui/src/routes.tsx`
- `ui/src/app/Sidebar.tsx` and its navigation test
- `ui/src/app/__tests__/executeEndpointFor.test.ts`
- `ui/src/screens/__tests__/Approvals.test.tsx`
- `ui/src/screens/Consultant.tsx`
- `ui/src/styles.css`

## Follow-Up

- Browser/desktop verification was not run in this headless task. The screen
  is intentionally inert on machines without the required flags, a local
  `pac`, and a pre-created workspace; browser coverage verifies gate banners,
  backend block-reason rendering, request bodies, and confirmations only.
- Human/Claude read-only review and merge authority remain outstanding.
