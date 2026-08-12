# Power Platform connector factory verification

## Focused checks

- `uv run ruff check ...`
- `uv run mypy src tests`
- `uv run pytest -q tests/test_power_platform.py`
- API tenant/RBAC and CLI artifact tests
- PAC plan validation, approval binding, missing-PAC, timeout, redaction, and
  no-shell execution tests
- `pnpm exec tsc -b --pretty false`
- Connector Factory and Workflow Designer UI tests

## Required full checks before PR

- Python coverage gate at or above 95%.
- Full backend and UI test suites.
- Bandit, pip-audit, and public-surface audit.
- Production UI build.
