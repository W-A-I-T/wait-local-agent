# Review: `wla-fix-opportunity-report`

Scope review:

- Changed files are limited to the requested report implementation, report
  tests, changelog, and task documentation.
- `build_automation_opportunity_report(store, estimates, *, client_id,
  period_start, period_end)` is unchanged.
- QBR still uses `_successful_action_candidates` without new thresholds; only
  user-facing wording was relabeled.
- Opportunity generation remains review-only and does not invoke actions,
  workflows, or approvals.
- Non-success smart-action statuses remain visible to opportunity accounting
  as attempts/failures, while approval IDs are counted without exposing any
  approval payload.
- `tests/test_scheduler.py` required no update; its 47 tests pass with the
  unchanged report reference.

Validation note: the five report tests that reach the new implementation pass.
The broader requested test command stalls at the API integration test
`test_report_generation_api_is_client_scoped_and_audited`; a 90-second timeout
ends that run without a report assertion failure.
