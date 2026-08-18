# Review Notes

This implementation is intentionally limited to PR1. `ui/`, `agents.py`, and
`rmm.py` were not modified. RMM persistence, additional seeders, graph context
builder wiring, and client-wide graph endpoints remain deferred.

Security/data-boundary checks covered by the focused tests include:

- `None` graph scopes raise instead of acting as wildcards.
- Cross-client refs are invisible through scoped reads.
- Cross-client link writes raise before insertion.
- Traversal is bounded by depth and node caps and uses stable ordering.
- Out-of-scope ticket context returns 404.

The full pytest, mypy, ruff, bandit, and migration-rehearsal gate remains for
the final Claude review.
