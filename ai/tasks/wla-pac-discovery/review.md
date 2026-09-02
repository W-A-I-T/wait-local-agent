# Review — wla-pac-discovery

Status: ready for required reviews.

## Codex implementation review

- All four production resolution sites use `resolve_pac_executable`; the only
  remaining `shutil.which("pac")` is inside that resolver's unset-setting PATH
  fallback.
- An explicit `WAIT_PAC_PATH` is expanded and resolved only after checks for
  non-symlink, regular-file, and executable status. Invalid explicit paths
  return `None` and never consult PATH.
- Stage and rollback check availability first, then require a parseable version
  at or above imported `PAC_YAML_MINIMUM_VERSION`; probe failure/unparseable
  output blocks distinctly.
- Version ordering uses integer tuples, so `2.10.0` is greater than `2.9.0`.
- Acceptance tests assert the command runner remains uncalled for below-floor
  and unknown-version blocks. All version probes in tests are fakes.
- Approval, write/deployment flags, evidence, digest, promotion, artifact, and
  rollback sequencing remain unchanged apart from the requested binary/version
  behavior.
- Security review: probe and deployment use fixed argv with `shell=False`, the
  configured executable is validated, no secrets are added or emitted, and
  untrusted version output is reduced to a bounded numeric version string.

## Cross-family review (kimi, read-only)

Pending orchestrator handoff.

## Final gate (claude)

Pending. Required confirmations are listed above and must include live final
head CI/status before merge.
