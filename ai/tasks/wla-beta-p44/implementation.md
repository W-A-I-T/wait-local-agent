# Implementation Notes

## Summary

- Replaced the static multi-child supervisor display in the Consultant architecture view with a tenant-scoped plan/run workflow.
- The UI posts the verified `{ client_id, task, child_agent_ids, max_retries }` plan body and renders the returned dependency order, child names, tools, and context policy.
- The UI posts the verified run body with `entity_id`, bounded `input.ticket_id`, `completed_run_ids`, and `max_retries`, then renders each returned child status, run ID, approval state, retry count, and Activity follow-up link.
- Approval-paused runs can continue with returned completed run IDs or cancel the pending child through `cancel_run_id`; failed runs can be retried through the supervisor run endpoint with completed dependencies preserved.
- Added section-scoped loading/error state and explicit copy: "Children run through the approval-gated agent engine against the selected ticket — nothing bypasses review."

## Verified Request Models and Routes

- `POST /consultant/supervisor/plan`: `{ client_id, task, child_agent_ids, max_retries }`.
- `POST /consultant/supervisor/run`: `{ client_id, entity_id, task, child_agent_ids, input, completed_run_ids, max_retries, cancel_run_id }`.
- Cancel/retry are exposed as supervisor run controls, not separate supervisor routes: cancellation uses `cancel_run_id`; bounded retries use `max_retries` and the run response's lineage metadata.
- The backend enforces technician access, tenant-scoped persisted child definitions, one supervisor layer, approval gates, and ticket/entity scope; the UI does not reimplement those decisions.

## Files Touched

- `ui/src/screens/Consultant.tsx`
- `ui/src/api/types.ts`
- `ui/src/styles.css`
- `ui/tests/Consultant.test.tsx`
- `ai/tasks/wla-beta-p44/implementation.md`
- `ai/tasks/wla-beta-p44/review.md`
- `ai/tasks/wla-beta-p44/status.json`

## Follow-Up

- Human/Claude review and merge remain required.
- The existing Vite config-loader and chunk-size warnings remain for a separate maintenance task.
