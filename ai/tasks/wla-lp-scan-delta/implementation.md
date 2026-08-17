# Implementation — wla-lp-scan-delta

Implemented the backend-only deterministic founder scan delta. The pure
`compute_bundle_delta` function compares production dependency presence,
manifest hashes, and file hashes from `hashes`; `open_founder_scan` derives the
immediately preceding persisted artifact after saving and returns its identity
alongside the delta. First scans are explicitly empty deltas, and unavailable
current modules report `unknown` instead of removal.

No UI, founder pack, results route, store code, schema, migration, dependency,
commit, or push was changed.

## Files

- `src/wait_local_agent/founder_bundle.py`
- `src/wait_local_agent/api/founder.py`
- `tests/test_founder_surface.py`
- `CHANGELOG.md`
- `docs/concepts/architecture.md`
- `ai/tasks/wla-lp-scan-delta/implementation.md`
- `ai/tasks/wla-lp-scan-delta/review.md`
- `ai/tasks/wla-lp-scan-delta/status.json`
