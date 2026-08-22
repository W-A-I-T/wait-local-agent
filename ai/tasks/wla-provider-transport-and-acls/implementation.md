# Implementation Notes

## Summary

- Added `validate_operator_url` as the shared operator-configured URL policy:
  bounded HTTP(S) URLs, no embedded credentials, loopback support, and secure
  non-loopback transport by default. Existing provider-specific URL/path
  normalization remains in each connector.
- Added the default-off `WAIT_ALLOW_INSECURE_PROVIDER_TRANSPORT` setting and
  propagated it through the provider adapters, including the direct HaloPSA,
  Hudu, ConnectWise, communication webhooks, and Launch Passport clients. The
  pinned connector factory remains strict HTTPS and retains its allowlist.
- Made hardening permission checks explicitly POSIX-only. Non-POSIX results are
  `not_applicable` with `permission_model: windows-acl` and no remediation.
  Filesystem permission helpers now dispatch the Windows backend immediately
  after opening newly-created private files and when creating directories.
- Added Windows desktop token protection using a protected DACL with the
  current user SID (`D:PAI(A;;FA;;;SID)`), applied after open and before token
  bytes are written. Unix creation uses mode `0600`; ACL failures are logged
  without hiding the usable token path.
- Kept existing-directory permission helpers existence-only. Runtime-created
  files and directories are protected, but pre-existing directories are never
  retroactively re-permissioned because a protected DACL can remove inherited
  access from unrelated files.
- Added regression coverage for URL policy, all in-scope provider validators,
  settings defaults/opt-in, hardening behavior, and filesystem backend wiring.

## Commands Run

- `pwd`, `git remote -v`, `git status --short --branch`: verified
  `W-A-I-T/wait-local-agent` on `codex/wla-provider-transport-and-acls`.
- `python -m compileall -q src tests`: passed using the task audit virtualenv.
- Focused pytest covering transport, connector factory, configuration,
  filesystem permissions, hardening, and provider transport: passed.
- `ruff check .`: passed.
- `mypy src tests`: passed.
- `bandit -r src`: passed with no findings; existing `#nosec` and comment
  warnings remain informational.
- `scripts/public_surface_audit.py`: passed.
- Focused platform/store/vault/backup permission tests: passed.
- `scripts/validate_release.sh`: Ruff, mypy, Bandit, and `pip-audit` passed;
  the aggregate pytest phase reached the existing API-test hang and was
  stopped before the release script could complete.
- Aggregate pytest with coverage: stopped by the existing
  `tests/test_agents.py::test_agent_api_can_cancel_pending_run...` API-test
  hang before completion. The communication API test shows the same local
  integration-test behavior; focused communication transport coverage passes.
- Rust target compilation was not available locally (`rustc`/`cargo` are not
  installed). Cached `windows-sys 0.61.2` source was inspected for the exact
  APIs and feature gates; Windows CI remains required for compile/runtime
  confirmation.

## Files Touched

- `.env.example`, `CHANGELOG.md`, `.github/workflows/test.yml`
- `desktop/src-tauri/Cargo.toml`, `desktop/src-tauri/src/main.rs`
- Provider and platform modules under `src/wait_local_agent/`, including
  `net_security.py`, `config.py`, `fs_permissions.py`, `store.py`, `vault.py`, and
  `reports/hardening_checks.py`
- `tests/conftest.py`, `tests/test_config.py`, `tests/test_fs_permissions.py`,
  `tests/test_hardening_checks.py`, `tests/test_net_security.py`,
  `tests/test_provider_transport.py`
- Task artifacts: `implementation.md`, `review.md`, and `status.json`

## Follow-Up

- Run the Windows desktop x86 build and dynamic-port/runtime validation in CI
  or on a Windows host.
- Add a future Windows-aware hardening check that reports over-permissive
  pre-existing directories without modifying their ACLs.
- Complete the required independent review and final human merge gate.

## Validation Refresh — 2026-08-22

- Reconfirmed checkout identity: `W-A-I-T/wait-local-agent`, branch
  `codex/wla-provider-transport-and-acls`, HEAD `875bae9`.
- Focused transport, connector-factory, configuration, hardening, filesystem,
  store/platform, and provider regression suites passed in `.venv`.
- `ruff check .`, `mypy src tests`, `bandit -r src`, Python compileall, and
  `scripts/public_surface_audit.py` passed. Bandit emitted only the existing
  informational `#nosec`/comment warnings.
- `scripts/validate_release.sh` reached `pip-audit` but could not complete
  because this sandbox cannot resolve `pypi.org`; the earlier aggregate run
  also remains unable to complete past the existing API integration-test hang.
- No Rust toolchain is installed locally, so the target-gated Windows desktop
  compile and real ACL/dynamic-port validation remain open CI/Windows-host
  gates.
- Removed the unsafe retroactive directory-ACL repair exposed by PR #405's
  legacy SQLite migration failures. Existing stores now retain their original
  access model; newly-created state paths remain protected before first write.
  The hardening path-evidence test derives its expected permission model from
  the platform capability.
