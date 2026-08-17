# Implementation: `wla-fix-opportunity-report`

Implemented the decision-complete contract in `reports/msp.py` and
`tests/test_msp_reports.py`.

- Added documented opportunity thresholds:
  - `AUTOMATION_OPPORTUNITY_MIN_ATTEMPTS = 5`
  - `AUTOMATION_OPPORTUNITY_MIN_SUCCESSES = 3`
  - `AUTOMATION_OPPORTUNITY_MIN_SUCCESS_RATE = 0.80`
  - `AUTOMATION_OPPORTUNITY_MIN_WINDOW_DAYS = 30`
  - `AUTOMATION_OPPORTUNITY_MAX_WINDOW_DAYS = 90`
  - `AUTOMATION_OPPORTUNITY_MAX_CANDIDATES = 20`
- Added `_automation_opportunity_candidates`, which counts all in-window
  statuses and reports attempts, successes, failures, success rate, approval
  burden, and declared estimated savings.
- Kept `_successful_action_candidates` count semantics for QBR and relabeled
  its reason/recommendation so a single success is not called repeated.
- Added fail-closed `window_out_of_range` metadata for periods outside the
  inclusive 30–90 day window.
- Added controlled-date direct SQLite fixtures for qualifying, threshold,
  window, and approval-burden coverage.

No execution path, caller signature, store code, or hot file was changed.
