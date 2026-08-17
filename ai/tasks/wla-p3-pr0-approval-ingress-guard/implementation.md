# Implementation — approval ingress guard

Implemented the narrow `_approval_completed` ingress guard at the start of
`SmartActionService.invoke`. Caller-supplied authority fields are rejected
before action lookup or provider execution, while other underscore-prefixed
payload fields remain allowed for the agent runtime.

The smart-action invoke API now maps `ValueError` to HTTP 400. Added regression
coverage for rejected payloads, provider-write suppression, the genuine
approval-completion write path, the HTTP response, and benign payloads.

## Files changed

- `src/wait_local_agent/smart_actions.py`
- `src/wait_local_agent/api/app.py`
- `tests/test_smart_actions.py`
- `CHANGELOG.md`
- `ai/tasks/wla-p3-pr0-approval-ingress-guard/implementation.md`
- `ai/tasks/wla-p3-pr0-approval-ingress-guard/review.md`
- `ai/tasks/wla-p3-pr0-approval-ingress-guard/status.json`

No files under `src/wait_local_agent/agents.py`,
`src/wait_local_agent/workflows.py`, or `ui/` were changed. No commit or push
was made.

## Validation

- Focused unit regressions:

  ```text
  PYTHONPATH=src /home/josephp/wait-local-agent/.venv/bin/python -m pytest tests/test_smart_actions.py -q -p no:cacheprovider -k 'invoke_rejects_approval_completed or invoke_accepts_benign_payload'
  ..                                                                       [100%]
  ```

  Passed: 2 tests. The output included one existing FastAPI/httpx deprecation
  warning.
- The HTTP regression was started separately but reproduced the repository's
  known TestClient/lifespan hang and was interrupted with exit 130; no pytest
  result was emitted for that test.
- `/home/josephp/wait-local-agent/.venv/bin/mypy src tests`: passed, no issues
  found in 227 source files.
- `/home/josephp/wait-local-agent/.venv/bin/ruff check .`: passed.
- `/home/josephp/wait-local-agent/.venv/bin/bandit -r src`: passed, no issues
  identified; 0 issues at every severity and confidence level. Bandit emitted
  existing informational warnings about ignored test-comment words and
  `nosec` annotations.
- `git diff --check`: passed.

The full suite and coverage gate remain Claude's final-gate responsibility per
the task contract.
