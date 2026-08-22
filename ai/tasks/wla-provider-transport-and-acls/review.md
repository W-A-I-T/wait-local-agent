# Review

## Changed Files

- Shared URL policy and settings are changed in `net_security.py`,
  `config.py`, `.env.example`, and `CHANGELOG.md`.
- Provider adapters and direct clients are updated for NinjaOne, TimeZest,
  Autotask, Confluence, Datto RMM, IT Glue, Kaseya, Microsoft Graph,
  N-central, Notion, N-sight, ScreenConnect, ServiceNow, SharePoint, Syncro,
  Teams Graph, communication webhooks, Launch Passport, HaloPSA, Hudu, and
  ConnectWise.
- `reports/hardening_checks.py`, `fs_permissions.py`, the Windows workflow,
  and the Tauri desktop token implementation are changed for permission-model
  and ACL behavior.
- Regression tests and the three task artifacts are updated.

## Risk Areas

- The Windows DACL path is target-gated and uses raw Win32 APIs. It must be
  compiled on the Windows x86 target and exercised with a real token file.
- Existing Windows vault, state, and artifact directories remain
  existence-only. Retroactively applying a protected DACL can strip inherited
  access from pre-existing files and lock the owner out; the runtime therefore
  protects only directories and files it creates. A future Windows-aware
  hardening check should report over-permissive existing directories without
  changing them.
- ACL application is intentionally nonfatal to preserve startup/token creation;
  Windows validation must confirm that failures are visible in logs and do not
  leave an unprotected artifact in an unexpected location.
- The insecure transport switch is global across in-scope provider origins and
  defaults to false. Loopback HTTP remains available to support local operators.
- The pinned connector factory was deliberately left strict HTTPS so enabling
  the compatibility switch cannot weaken DNS-pinned provider requests.
- No UI, migration, secret, or blocked-path changes were made.

## Version & Compatibility Evidence

- Added Windows-only `windows-sys = 0.61.2` with the minimal feature set:
  `Win32_Foundation`, `Win32_Security`, `Win32_Security_Authorization`, and
  `Win32_System_Threading`.
- Revalidated on 2026-08-22: `windows-sys 0.61.2` remains the latest stable
  crate version in the current docs.rs release list. Its published manifest
  lists Rust MSRV `1.71`; the Tauri workspace requires Rust `1.85.0`, so the
  dependency is compatible. Evidence:
  [crate manifest](https://docs.rs/crate/windows-sys/0.61.2/source/Cargo.toml.orig)
  and [authorization API surface](https://docs.rs/windows-sys/0.61.2/windows_sys/Win32/Security/Authorization/index.html).
- The cached crate source confirms the selected feature gates expose the
  token, SID, security-descriptor, DACL, and process-token APIs used here.
- Local Linux/macOS behavior remains unchanged by the target-gated dependency;
  Unix private-file creation uses `0600`. No lockfile or Python dependency
  change was required.
- Remaining compatibility risk: the local environment has no Rust toolchain,
  so the Windows compile and runtime evidence is still required.
- The latest docs.rs release listing still identifies `windows-sys 0.61.2` as
  the newest stable release checked on 2026-08-22. The 0.61.2 source confirms
  `LocalFree` in `Win32_Foundation`, the security-descriptor and DACL APIs in
  `Win32_Security` / `Win32_Security_Authorization`, and process-token APIs in
  `Win32_System_Threading`; these match the target-gated feature list.

## Open Questions

- Confirm the Windows x86 CI build and dynamic-port test on a real Windows
  runner.
- Keep the Windows x86 build and dynamic-port/runtime validation as the release
  gate for the target-specific ACL code.
- The aggregate local pytest run still reaches a pre-existing API integration
  test hang; the focused task suite and static/security checks pass.
- PR #405's first Windows run exposed three legacy SQLite migration tests that
  failed when parent-directory ACL repair removed inherited access. This task
  now removes that retroactive repair entirely; the regression suite covers
  pre-existing database migration and existing-directory no-op behavior.

## Test Results

- Passed: focused transport/connector/configuration/filesystem/hardening suite,
  Ruff, mypy, Bandit, compileall, public-surface audit, and
  platform/store/vault/backup permission tests.
- Passed on rerun: `pip-audit` reported no known vulnerabilities.
- Latest local `pip-audit` could not query PyPI because outbound DNS is
  unavailable in the sandbox; this is an infrastructure limitation, not a
  dependency finding.
- Incomplete locally: aggregate pytest coverage was stopped by the existing
  API-test hang; Windows Rust compilation was unavailable.
- AST audit of `reports/hardening_checks.py` found none of the forbidden
  remediation identifiers (`subprocess`, `shutil`, `write_text`,
  `write_bytes`, `unlink`, `chmod`).

## Diff Summary

- Provider-origin policy is centralized without changing provider-specific
  endpoint normalization. The explicit compatibility flag is threaded only at
  provider call sites, while the pinned transport remains strict.
- POSIX permission checks now self-identify their permission model and do not
  report false failures on non-POSIX systems.
- Desktop token protection is applied before writing secret bytes, with
  protected current-user-only DACL semantics on Windows.

## Requested Review Focus

- Verify every listed provider call site passes the explicit opt-in flag.
- Verify Windows API imports/features and the x86 target build.
- Verify no hardening check performs forbidden remediation or reports POSIX
  mode bits on Windows.
- Verify the strict factory path remains unaffected by the global opt-in.
