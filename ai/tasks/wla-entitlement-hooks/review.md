# Review

## Changed Files

- Backend: `license_v2.py`, pack loader, config, app routes, models, store migration/CRUD.
- Contract/docs: `.env.example`, surface coverage, Community/commercial legal note, migration pins.
- UI: entitlement context/types, Clients activation controls, focused UI test.
- Tests: focused license, loader/entitlement, activation, isolation, audit, and migration-pin coverage.

## Risk Areas

- Ed25519 verification is strict and fail-closed; canonical payload ordering and unpadded base64url parsing must remain aligned with the proprietary pack signer.
- The loader intentionally falls back from v2 to legacy HMAC and then false. The public runtime passes the verified payload through the private-pack hook and does not enforce client limits.
- Migration 12 is tenant-scoped through the existing client scope predicate. Activation is idempotent and preserves the original activation metadata on repeat activation.
- API route behavior is covered by tests but not executed because pytest was prohibited; direct `create_app` smoke was blocked by environment mismatch/timeout.
- The pre-existing worker lock metadata is untracked and was not included in the implementation changes.

## Version & Compatibility Evidence

- No dependency or external API version was changed; the implementation uses the repository's existing FastAPI/cryptography interfaces and adds no package.
- Verified available runtime/tool versions: FastAPI 0.139.0, cryptography 48.0.1 in the repository venv, Node v24.16.0, npm 11.13.0, Vite 8.2.2, and Vitest 4.1.11. The cryptography environment is older than the repository declaration, but the implementation uses the compatible Ed25519 `from_public_bytes` API; no newer package was required.
- `npm ls --depth=0` reported pre-existing invalid installed versions for `@types/react-dom` and `lucide-react`; package manifests were not changed because this task has no dependency upgrade.
- `uv lock --check` could not complete because the configured uv cache was read-only; no lockfile was modified.

## Open Questions

- Confirm proprietary-pack integration supplies `entitlement_status_factory` and `pack_enabled_v2` with the agreed canonical payload/signature format.
- Run the repository's full backend/UI gates in a complete task-approved environment before merge.

## Test Results

- Passed: compileall, JSON parse, `git diff --check`, Ruff, mypy, Bandit exit status, focused Vitest, UI build, and pure license/store plus loader/entitlement smoke checks.
- Not run: pytest and Playwright, explicitly prohibited by the plan.
- Blocked: direct API app smoke due missing `itsdangerous` in one venv and a `create_app` timeout in the alternate complete venv.

## Diff Summary

- The public runtime now exposes neutral commercial status and activation bookkeeping while preserving Community behavior. It supports offline Ed25519 license-v2 verification as an optional pack hook, retains legacy HMAC compatibility, and does not count or enforce Managed Client limits.

## Requested Review Focus

- Verify no public-runtime path branches on `max_managed_clients` or activation count, and confirm the zero-effect tests express that contract.
- Verify migration 12 scope/isolation, admin/demo gating, audit events, route manifest entries, and strict license fail-closed behavior.
- Verify no private-key material or credential-looking fixtures were added.

## Claude Final Gate — Review & Validation (2026-09-01)

Verdict: APPROVED — the cleanest slice of the pipeline (zero fix round-trips).

AGPL-neutrality contract verified three ways: (1) grep-level — max_managed_clients
never reaches public-runtime logic outside the verification passthrough;
(2) test_entitlement_and_activation_routes_are_neutral_and_audited proves
/clients responses are byte-identical before/after commercial activation and
GET /entitlement returns {"commercial": null} with no pack; (3) docs restate
Community rights unaffected, counsel review flagged for EULA language.

Ed25519 verification mirrors update_channel.py's pinned-pubkey pattern;
rejection matrix parametrized (bad sig / tamper / expiry / malformed /
unknown version / missing key / rotation). No private-key material anywhere
(test keys generated in-test). Loader ladder: v2 -> legacy HMAC -> locked.

Gates: backend 95.06% (local, above the CI-verified threshold band); mypy
clean (322 files); ruff/bandit clean; UI 469/470 (the one failure is the
known Sidebar coverage-instrumentation flake, 10/10 in isolation); build ok;
migration-12 pins updated.
