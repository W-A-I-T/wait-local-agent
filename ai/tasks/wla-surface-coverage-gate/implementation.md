# Implementation Notes

## Summary

- Expanded `enumerate_fastapi_routes` through FastAPI's effective route contexts so lazy `_IncludedRouter` markers and nested prefixes are inventoried without changing application routing.
- Preserved accumulated prefixes while recursively walking Starlette `Mount` routes, and intentionally excludes WebSocket routes from the HTTP surface manifest.
- Added deterministic `scripts/regenerate_surface_coverage.py` output and regenerated the manifest with the eight `/founder/*` routes. Existing class labels are retained; new entries default to `exposed`, and invalid classes fail regeneration.
- Added the nested-prefix regression test, two-decimal coverage precision, `packs` coverage scope, tolerant PyInstaller pack hidden imports, and a non-vacuous desktop workflow assertion when the pack tree exists.
- Changed the pack-loader teardown to call `sync_pack_cli()` with real discovery, preventing test-order cleanup from permanently removing discovered CLI groups from the process-global command tree.
- Added meaningful round-4 regression coverage for all 26 selected reachable lines named by the plan, without changing product code or coverage exclusions.

## Validation

- Demo app inventory: all 8 expected `/founder/*` routes reported.
- `.venv/bin/python -m pytest tests/test_spine_p0.py -q --cov=wait_local_agent.surface_coverage --cov-report=term-missing --cov-fail-under=0`: 7 passed; `surface_coverage.py` reached 100.00%.
- Targeted round-4 regression set: 19 passed; all 26 selected plan lines were covered in the term-missing report.
- Regenerator run twice: identical manifest SHA-256; no generated drift.
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/mypy src tests`: passed with no issues in 235 source files.
- `.venv/bin/bandit -r src`: passed with no issues.
- `.venv/bin/python scripts/public_surface_audit.py`: passed.
- `PATH="/home/josephp/wla-fix/gate/.venv/bin:$PATH" scripts/validate_local_first.sh`: passed.
- `UV_CACHE_DIR=/tmp/wla-surface-uv-cache uv lock --check`: passed.
- `.venv/bin/python -m compileall -q src tests scripts`: passed.
- Installed versions verified: FastAPI 0.141.1, Starlette 1.6.0, Pydantic 2.13.4, pytest 9.1.1, pytest-cov 7.1.0, coverage 7.15.4, and httpx 0.28.1. No dependency was added, removed, or repinned.

## Execution Notes

- The full-suite 95.00% result and ordered pack-loader/spine result are not claimed here; round 3 assigns those confirmations to the orchestrator's compatible environment. No coverage exclusions, threshold changes, skipped tests, or weakened assertions were added.
- `bash packaging/build-sidecar.sh` and the built-binary `/packs/status` assertion were not run because this base checkout intentionally has no `src/packs/**`, and Rust/PyInstaller are unavailable.

## Files Touched

- `.github/workflows/test.yml`
- `docs/ai-workflow/surface-coverage.json`
- `packaging/server.spec`
- `pyproject.toml`
- `scripts/regenerate_surface_coverage.py`
- `src/wait_local_agent/surface_coverage.py`
- `tests/test_pack_loader.py`
- `tests/test_spine_p0.py`
- Targeted behavior tests in `tests/test_config.py`, `tests/test_knowledge.py`, `tests/test_security_vault.py`, `tests/test_communication.py`, `tests/test_rmm.py`, `tests/test_runtime_scope.py`, `tests/test_monitoring.py`, `tests/test_reports.py`, `tests/test_lp_polling.py`, `tests/test_power_automate.py`, `tests/test_technician_chat.py`, `tests/test_environment.py`, and `tests/test_syncro.py`

## Follow-Up

- Run the ordered pack-loader/full-suite coverage gates in the orchestrator or CI-resolved test-client environment and confirm the final 95.00% result on the stacked pack branch.
- Run the desktop sidecar build and `/packs/status` smoke assertion on the stacked capability-pack branch or a checkout containing `src/packs/**`.
- Obtain the required Kimi cross-family review and Claude final gate before any human merge decision.
