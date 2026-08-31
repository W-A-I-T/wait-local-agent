# Implementation Notes

## Summary

- Verification completed before implementation.
- `GET /workflows/templates` returns `asdict(WorkflowTemplate)` from
  `src/wait_local_agent/api/app.py:4677-4679`. `WorkflowTemplate` exposes
  `payload_schema` at `src/wait_local_agent/models.py:479-490`.
- Workflow payload metadata is an object with optional `required` names and
  `properties`; property values are descriptive strings, not typed JSON Schema
  objects. Twelve templates declare payload properties, while twelve remain
  without any declared payload fields. Declared payload fields exist for
  `inactive-ticket-follow-up`,
  `p1-alert`, `documentation-assisted-response`, `ticket-sla-risk-review`,
  `stale-ticket-sweep-review`, `recurring-service-review`, all seven M365
  review/action templates, and `software-inventory-review`; nine of those
  twelve also declare required fields.
- Templates remaining raw-JSON-only because the backend declares no input
  fields are `ticket-triage`, `assign-technician`, `l1-resolution-review`,
  `ticket-quality-review`, `ticket-sentiment-review`,
  `ticket-escalation-review`, `security-alert-review`,
  `similar-ticket-review`, `duplicate-ticket-review`,
  `technician-dispatch-review`, `m365-compliance-review`, and
  `m365-inactive-license-review`. They must retain the no-fields state and
  Advanced raw JSON fallback.
- `MspPlaybookStep.required_inputs` is declared at
  `src/wait_local_agent/msp_playbooks.py:43-52`; report steps provide
  `period_start` and `period_end` at lines 84-97. The playbook endpoint
  serializes complete definitions at `src/wait_local_agent/api/app.py:4681-4683`.
- Aggregated playbook fields are: `stale-sla-review`:
  `stale_after_minutes`, `thresholds_minutes`;
  `m365-onboarding-review`: `user_principal_name`, `display_name`,
  `mail_nickname`, `temporary_vault_name`, `user_id`, `sku_ids`, `operation`;
  `m365-offboarding-review`: `user_identity`, `user_id`;
  `inactive-ticket-follow-up-review`: `stale_after_minutes`, `channel`;
  `m365-password-reset-review`: `user_identity`, `temporary_vault_name`;
  `m365-authentication-method-review`: `user_identity`, `method_type`,
  `method_id`; `m365-license-review`: `user_id`, `sku_ids`, `operation`;
  `software-inventory-review`: `device_id`; and each report-only `qbr-review`,
  `automation-opportunity-review`, and `recurring-service-review`:
  `period_start`, `period_end`.
- The UI implementation will infer a safe field control from the backend's
  descriptive metadata, use `SchemaForm` for labeled fields plus its JSON
  fallback, and preserve the existing request body shape.

## Commands Run

- `pwd`, `git remote -v`, `git status --short --branch` — verified
  `W-A-I-T/wait-local-agent` on `ai/wla-beta-p35-structured-inputs`.
- `sed`/`nl` inspection of the task plan, UI screens, shared form, API types,
  backend workflow/playbook definitions, and existing tests.
- `env PYTHONPATH=src /usr/bin/python3 -c ...` — enumerated live backend
  workflow payload schemas and aggregated playbook required inputs above.
- `cd ui && npm ci --ignore-scripts` installed the existing lockfile without
  changing dependency declarations; audit reported 0 vulnerabilities.
- `cd ui && npm test -- --run tests/Workflows.test.tsx tests/Playbooks.test.tsx
  src/components/__tests__/SchemaForm.test.tsx` — 3 files and 17 tests passed.
- `cd ui && npm run build` — TypeScript and Vite production build passed.
- `cd ui && npm test -- --run` — 63 files and 332 tests passed, twice.
- Both validation runs reported only the pre-existing Vite native-config
  warning and large-chunk advisory.

## Files Touched

- `ui/src/screens/Workflows.tsx` — structured workflow payload controls,
  validation, and raw JSON fallback wiring.
- `ui/src/screens/Playbooks.tsx` — aggregated required-input controls,
  validation, and raw JSON fallback wiring.
- `ui/src/components/SchemaForm.tsx` — configurable labels/empty state,
  two-way JSON synchronization, and raw JSON validity reporting.
- `ui/src/lib/structured-inputs.ts` — conservative backend metadata adapter.
- `ui/tests/Workflows.test.tsx` and `ui/tests/Playbooks.test.tsx` — launcher
  synchronization, request-body, no-field, and required-validation coverage.
- `ai/tasks/wla-beta-p35/implementation.md`, `review.md`, and `status.json` —
  execution records.

## Follow-Up

- No follow-up implementation is required. The descriptive workflow metadata
  is intentionally adapted conservatively; ambiguous/object values remain
  available through Raw JSON (advanced).
