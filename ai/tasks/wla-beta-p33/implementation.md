# Implementation Notes

## Summary

- Added the Agents screen's History and recovery drawer with revision timestamps,
  version selectors, structured field-level diffs, and confirm-gated restore.
- Restore refreshes the agent/tool definition list and repopulates the selected
  agent form when it was being edited, while preserving save-as-new-revision
  semantics.
- Shared component extraction did not happen. The existing Playbooks drawer
  was used as the mechanical UI pattern, but agent and playbook response models
  and route contracts differ.

## Verified API contract

- `GET /agents/{agent_id}/revisions` returns a list of `{ id, agent_id,
  version, definition, created_at, client_id }` revision views. `definition` is
  a redacted JSON object.
- `GET /agents/{agent_id}/revisions/{version}/diff/{other_version}` returns
  `{ agent_id, from_version, to_version, changed, changes, client_id }`, where
  `changes` contains `{ field, before, after }` entries.
- `POST /agents/{agent_id}/revisions/{version}/restore` returns the normal
  agent definition view, including the new `version`, and accepts `{}` as the
  request body. The UI only sends this request after confirmation.
- Route and response details were verified in `src/wait_local_agent/api/app.py`
  before wiring the UI.

## Commands Run

- `npm ci` (from `ui`) — completed; lockfile install reported 0 vulnerabilities.
- `npm test -- --run tests/Agents.test.tsx` — 20 tests passed.
- `npm test -- --run` — 63 files / 323 tests passed, twice.
- `npm run build` — passed (`tsc -b` and Vite production build).
- `git diff --check` — passed.

The existing Vite warning about `configLoader: native` and the existing
post-minification chunk-size advisory remain; neither is introduced by this
task.

## Files Touched

- `ui/src/screens/Agents.tsx`
- `ui/src/styles.css`
- `ui/tests/Agents.test.tsx`
- `ai/tasks/wla-beta-p33/implementation.md`
- `ai/tasks/wla-beta-p33/review.md`
- `ai/tasks/wla-beta-p33/status.json`

## Follow-Up

- No follow-up implementation was identified.
