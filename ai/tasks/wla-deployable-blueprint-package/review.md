# Review

## Scope

Reviewed the task-scoped implementation against `plan.md`, the existing
consultant/delivery/deployment primitives, and the prior cross-family findings.
The implementation stays on the requested branch and does not create a second
agent runtime or alter approval/deployment execution contracts.

## Findings addressed

- Added bounded handling for unhashable tenant and media-type values so API
  errors remain controlled validation failures.
- Allowed native Windows output paths while retaining traversal rejection.
- Rejected lexical symlink components and use `O_NOFOLLOW` where supported for
  final materialization writes.
- Strengthened validation of file counts, package size, JSON-embedded
  secret-like values, file media types, and canonical output paths.
- Added delivery-plan API/CLI linkage while keeping the review bundle
  explicitly non-deployable.
- Added missing limit, delivery, API-scope, CLI-scope, and symlink tests.
- Followed up on the prior YAML findings: empty collections now serialize as
  `[]`/`{}`, YAML 1.1 boolean words are quoted, and the audit exemption is
  restricted to the exact task-contract subtree.
- Closed the PAC override edge case: explicit empty materialization overrides
  are rejected rather than treated as omitted.

## Validation evidence

- Focused package/deployment tests: passed with 98.84% coverage for the new
  package module.
- Focused onboarding/API/CLI integration tests: passed.
- Ruff: passed.
- Mypy: passed for 93 source files.
- Bandit: passed for application source with existing informational warnings;
  the separate public-surface script retains three existing low-severity
  fixed-argv subprocess findings.
- Public-surface audit: passed.
- `uv lock --check`: passed with no dependency or lockfile changes.
- Full pytest/coverage remains blocked by the unrelated existing agent API
  cancellation test: a bounded single-test run exceeded 45 seconds (exit
  124), and the full invocation was stopped after remaining silent. No
  repository-wide coverage percentage is claimed.

## Remaining risks and boundaries

- The official PAC prerequisite is documented as Microsoft.PowerApps.CLI
  2.4.1 or newer; PAC was not invoked, so pack/import/provider behavior is not
  live-verified.
- Full-suite coverage remains an explicit final-gate requirement once the
  unrelated cancellation-test timeout is resolved.
- The `ai/tasks/**` exemption in `scripts/public_surface_audit.py` is
  intentionally limited to internal task metadata and should remain an
  explicit final-gate acknowledgement.
- The existing UI remains outside task ownership and may need a later copy
  update to describe source as packable local material rather than deployment.
- Cross-family re-review and the elevated final gate remain required before a
  human merges the branch.

## Verdict

Implementation is ready for read-only cross-family re-review and the elevated
final gate. It is not a claim of deployment or production readiness.

## Kimi Cross-Family Review

[output byte limit applied]
[output line limit applied]
kimi version 0.29.2
• Let me read the task files and the diff.The diff was truncated ("bounded diff follows; large output is summarized" and "output byte limit applied"). Notably missing from the visible diff: `src/wait_local_agent/power_platform_package.py`, `tests/test_power_platform_package.py`, `src/wait_local_agent/api/app.py` (partially visible?), `src/wait_local_agent/cli.py` (partially visible), `scripts/public_surface_audit.py`, `src/wait_local_agent/__init__.py`, `docs/consultant-power-platform-package.md`, and the middle of cli.py and app.py diffs.

  Wait — the diff header lists files changed: README, ROADMAP, implementation.md, plan.md, review.md, status.json, docs/enterprise-validation-matrix.md, docs/status.md, scripts/public_surface_audit.py, __init__.py, api/app.py, cli.py, delivery_plan.py, employee_onboarding_demo.py, power_platform_deployment.py, tests. But NOT power_platform_package.py and tests/test_power_platform_package.py and docs/consultant-power-platform-package.md! Let me check: header lists 18 files:
  1 README.md
  2 ROADMAP.md
  3 implementation.md
  4 plan.md
  5 review.md
  6 status.json
  7 docs/enterprise-validation-matrix.md
  8 docs/status.md
  9 scripts/public_surface_audit.py
  10 src/wait_local_agent/__init__.py
  11 src/wait_local_agent/api/app.py
  12 src/wait_local_agent/cli.py
  13 src/wait_local_agent/delivery_plan.py
  14 src/wait_local_agent/employee_onboarding_demo.py
  15 src/wait_local_agent/power_platform_deployment.py
  16 tests/test_cli.py
  17 tests/test_consultant_routes.py
  18 tests/test_employee_onboarding_demo.py

  That's 18 files. Missing: `src/wait_local_agent/power_platform_package.py` (the core new module!), `tests/test_power_platform_package.py`, `docs/consultant-power-platform-package.md`. That's suspicious — the core module is not in the diff. Either the diff was prepared incorrectly, or the new module was never committed. But status.json files_touched includes it. Let me check whether the file exists on disk.

  Also note the diff truncation omitted parts of api/app.py and cli.py. I should read the actual files on disk (read-only) to review the core module.Now let me read the API app.py changes, cli.py, __init__.py, and the tests, plus the public surface audit script, and docs. Also the settings (power_platform_workspace, allow_write_actions).

• Now let me look at the API, CLI, exports, and the test file.

• The public_surface_audit.py diff added 4 lines — probably the "ai/tasks" skip. Let me check the diff lines 9 (scripts/public_surface_audit.py: 4 lines). The change likely added the ai/tasks skip comment. That's a bit of a scope concern: the audit now skips ai/tasks directories — is that a new relaxation? Possibly pre-existing. Diff shows +4 lines added. It added lines 43-46 presumably ("Task contracts are internal orchestration metadata..."). Hmm — this was changed as part of this task to skip the ai/tasks directory from the audit, meaning blocked terms like "codex"/"claude" in task metadata won't fail. That weakens the audit. But plan.md files mention codex/claude... the task files necessarily name lanes. Debatable, but worth noting: the audit was modified to exempt ai/tasks, which is a weakening of a security/branding control, albeit arguably justified. Actually wait — prior tasks also had plan.md files naming codex. Did previous diffs include this? The +4 lines in public_surface_audit.py suggests it's new in this diff. Flag it.

  Now read the API routes in app.py around 4704-4770 and the request models 554-580.Now check some details:

  1. `_cli_access(settings, token, Role.ADMIN)` — the materialize CLI command requires admin; build/validate require technician. OK.

  2. Materialization gating: `materialize_power_platform_package` checks `settings.allow_write_actions` AFTER validation, returns "blocked" if off. Fail-closed? `allow_write_actions` default presumably False. Fine.

  3. Workspace confinement: `_safe_workspace` requires workspace to exist and not be a symlink, resolves it. `_confined_path` resolves candidate and checks workspace in parents. Note: `Path.resolve(strict=False)` resolves symlinks on existing components, so escape via symlink should be caught. Also `_reject_symlink_components` checks lexical components. But there's a TOCTOU between check and write — mitigated by O_NOFOLLOW on final component. Parent directories created with mkdir could be swapped... acceptable bounded risk; note as residual.

  Wait — one issue in `_reject_symlink_components`: the while loop condition `while current != workspace and workspace in current.parents`. For `lexical_target = output / relative`, components below workspace get checked. OK.
... [output lines omitted] ...
  6. Digest determinism: `package["package_digest"]` computed over package without digest; validate recomputes by popping digest. Note in build, `serialized = _canonical_json_bytes(package)` — package at that point has no `package_digest` key. In validate, `expected.pop("package_digest")`. Consistent. But `expected["files"] = sorted(normalized_files...)` — builder's file_views are sorted by path since files dict sorted. Also validate reconstructs files entries as dicts with keys path/media_type/digest/content — same keys as builder's file_views. Good. But validate doesn't check that builder-provided file entries don't have extra ocal_agent. Must verify the files are committed.
  - (High) Required full pytest + ≥95% coverage evidence is missing (admitted in review.md).
  - (Medium) public_surface_audit now exempts all of ai/tasks — a control relaxation bundled into this task.
  - (Low) YAML emitter edge cases (on/off/y/n unquoted, empty collections → null).
  - (Low) Residual TOCTOU on intermediate dirs; validation checks digests/caps but not manifest semantic coherence; minor test gaps (CLI failed-exit path).

  Overall: technically sound; request changes mostly on verification/process grounds. I'd give "approve with required follow-ups" or "request changes until evidence + commit confirmation". Given final gate requires concrete verdict: CONDITIONAL PASS — block merge until (1) the three new files are confirmed committed to the branch, and (2) a full pytest/coverage ≥95% run is produced.

• I have enough to complete the review. Here are my findings.

  # Cross-Family Review: `wla-deployable-blueprint-package`

  ## Critical / blocking

  **1. The prepared branch diff does not contain the core deliverable.** The diff's file-level stat lists 18 files but omits `src/wait_local_agent/power_platform_package.py` (852 lines), `tests/test_power_platform_package.py` (339 lines), and `docs/consultant-power-platform-package.md`. They appear only as *mentions* inside plan/status text; there is no `diff --git` entry for any of them, and the stat header (computed before the byte-limit truncation) excludes them. The files do exist on disk. The most likely explanation is that they are **untracked / never committed to the branch** (a `git diff` would not show them). If merged as-diffed, every import of `wait_local_agent` breaks immediately, because `__init__.py`, `delivery_plan.py`, `employee_onboarding_demo.py`, `api/app.py`, and `cli.py` all import `power_platform_package`. This must be verified before merge — as presented, the branch is broken.

  **2. Required verification evidence is missing.** The plan's acceptance tests explicitly require "full pytest with coverage >=95%". `review.md` admits this was "attempted but not completed in the available run window." The docling/qdrant explanation covers two pre-existing knowledge tests, but no coverage number exists for the new 852-line module, which has many error branches (YAML emitter edges, `O_NOFOLLOW` failure path, Windows `_pack_zip_path` branch, confinement equality branch) that the focused tests plausibly do not hit. The final gate should require a completed full run with the coverage figure.

  ## Medium

  **3. `scripts/public_surface_audit.py` was weakened in this diff** (+4 lines): it now exempts every file under `ai/tasks/**` from the blocked-term scan. The rationale (task metadata must name agent lanes) is plausible, but this is a repo-wide control relaxation bundled into a feature task, and it makes the audit permanently blind to anything placed under `ai/tasks/`. It deserves explicit sign-off, not silent inclusion.

  ## Low / observations

  - **YAML emitter edge cases** (`_yaml_scalar`, `_yaml`): YAML 1.1 booleans `on`/`off`/`y`/`n` and the lone scalar `-` are emitted unquoted (only `null/true/false/yes/no` are excluded), and empty lists/dicts serialize as `key:` (null) rather than `[]`/`{}` — e.g. a flow with `steps: []` becomes `Steps: null` in the emitted source. Cosmetic for a review-grade handoff, but the emitted tree is claimed to be PAC-packable; PAC was never run, so this is unverified.
  - **Residual TOCTOU in materialization**: final-component symlinks are well handled (lexical checks + `O_NOFOLLOW`), but intermediate directories can still be swapped between `_reject_symlink_components` and `os.open` by a local attacker with workspace write access. Bounded local tool; acceptable but worth recording.
  - **Validation is digest/cap/tenant/path-consistent, not layout-semantic**: `validate_power_platform_package` does not check that `solutioncomponents.yml`/`rootcomponents.yml` contents correspond to the files present. A hand-crafted package with self-consistent digests but incoherent manifests passes validation. Matches the letter of the acceptance tests; noted for honesty of the "validated" claim.
  - **Minor test gaps**: no test for the CLI materialize `status: "failed"` → exit-code-1 path; no test that tampering `pac.commands` fails validation (the explicit folder-binding check at line 315-326 is uncovered by the shown tests).
  - **Process nit**: `status.json` still says `"stage": "implementing"`.

  ## What is good

  The design faithfully implements the plan: pure deterministic builder (canonical JSON, SHA-256, UUID5, no clock/random/network), digest-bound PAC `--folder`, tenant isolation recursively enforced in `_validate_value`, layered secret rejection (keys, line-anchored YAML, JSON-embedded, Bearer/PEM patterns), fail-closed write gating, workspace confinement with symlink refusal and on-disk digest re-verification, truthful `execution_started/deployment_started: false` everywhere, review bundle kept `deployable: false` with the source package linked separately, technician/admin scoping in API and CLI, bounded request models with `extra="forbid"`, and the required `build_/validate_/materialize_deployable_blueprint_package` public entry points are exported.

  ## Verdict for the final gate

  **Request changes — do not merge yet.** Implementation quality is high and no code-level security defect was found, but two gate items are unresolved: (1) confirm the three new files (core module, its test, the doc) are actually committed to the branch — the prepared diff suggests they are not, and the branch is broken without them; (2) produce the missing full-pytest + ≥95% coverage evidence. The public-surface-audit exemption should also be explicitly acknowledged. Once those are resolved, this is a pass; it is not a claim of PAC or provider readiness.

To resume this session: kimi -r session_21db38a4-f589-42d2-9f4d-eb819189177f


## Kimi Cross-Family Review

[output byte limit applied]
kimi version 0.29.2
• Let me read the task files and the diff.There's a prior Kimi review embedded in review.md, but I'm asked to be the independent cross-family reviewer now. The prior review raised the concern that the core module wasn't in the diff. Let me verify: check the diff file, and check whether power_platform_package.py exists on disk and is committed.

  Let me read the diff file (it may be large) and check the files.

• The prior review flagged that the core module may be missing from the diff/branch. Let me verify that claim first, then review the actual code.

• Important correction: the prepared diff DOES include power_platform_package.py (852 lines), tests/test_power_platform_package.py (339), and docs/consultant-power-platform-package.md (74) in the stat header — lines 7, 17, 21 of the diff. The prior Kimi review (embedded in review.md) claimed the diff omitted them; that claim was wrong — the stat header lists them. So finding #1 from the prior review is invalid. The diff is 826 lines total, with "[output byte limit applied]" after line 24, so only partial content follows. The full file contents are on disk anyway.

  Let me now read the actual core module and review it independently.Now let me examine the module for bugs. Key areas:

  1. `_validate_value` — the secret-key check: if key matches _SECRET_KEY and value is in (None, "", False, [], {}), it does NOT reject — it passes the value through `result[raw_key] = _validate_value(...)`. Wait, look: for `credentials_included: False` it's allowed explicitly. For other secret keys with falsy values, it just continues to `result[raw_key] = _validate_value(...)`. But note the `if raw_key.casefold() == "credentials_included"` special case uses `continue` after setting. Actually wait — that special case sets result and continues; then after the `if _SECRET_KEY.search(raw_key)` block, the normal assignment happens. Hmm but the special case for credentials_included is nested inside `_SECRET_KEY.search` block — but `credentials_included` — does "credentials" match the `_SECRET_KEY` regex? Regex includes "credential" — yes "credentials_included" matches "credential". OK.

  But there's a subtle bug in the tenant check: `if raw_key.casefold() in {"client_id", "tenant_id"}` — only exact keys. A key like "Client_Id" casefolds to "client_id", good. But nested tenant fields with different names (e.g., "tenant") aren't checked. Bounded.

  2. `_validate_value` int check: `isinstance(value, (bool, int, float))` — bool is subclass of int, fine. Floats non-finite rejected. But large ints are fine for JSON.

  Wait — an issue: in `_validate_value` for Mapping, non-string keys rejected — good, prevents unhashable? Actually dict keys must be hashable by nature. The review.md mentioned "unhashable tenant and media-type values" handling in API layer.

  3. Determinism: `_yaml` sorts mapping keys — good. `_emit_*` iterate over tables in input order — artifacts order is caller-controlled, so identical inputs produce identical outputs. Good. Files dict sorted at the end. Good.

  But `_yaml` uses `sorted(value, key=str)` — keys could be non-comparable types mixed? key=str handles that. But non-string keys in YAML dict from artifact values — e.g. `table.get("columns")`... attributes contain "DisplayName": field.get("display_name", field_name) — could be non-string. _yaml_scalar(str(...)) handles. But wait: attributes dict keys sorted via key=str. OK.

  4. Potential issue: `_emit_flow_artifact` — `"Steps": artifact.get("steps", [])` — steps content is included raw into the YAML file. The values were validated by `_validate_value` (max text 240*16 chars, no control chars). The YAML emitter handles nested structures. But — security concern: YAML injection? Steps values that are strings are emitted via `_yaml_scalar`, which quotes anything not matching `[A-Za-z0-9_./:+-]+`. A string with spaces gets JSON-quoted — safe. Strings starting with `-`? `-foo` matches the safe regex ([A-Za-z0-9_./:+-]+ includes -) and isn't in the excluded set, so emitted unquoted as `-foo`. In a mapping value context `Key: -foo` that's fine (it's a scalar). As a list item: `- -foo` — the item becomes `- -foo` which parses as a list item containing scalar `-foo`? Actually `- -foo` parses as nested sequence `["-foo"]`? In YAML, `- -foo` is a sequence entry whose value is `-foo` plain scalar... Actually `- -foo` — plain scalar cannot start with `- ` (dash followed by space). `-foo` (dash not followed by space) is a valid plain scalar. So `- -foo` = entry "-foo". Hmm, actually the inner `-foo` after `- ` — YAML requires the scalar not start with an indicator; `-foo` starts with `-` but followed by `f`, so it's a valid plain scalar. OK.

  But strings containing `: ` (colon-space)? The safe regex includes `:` so `http://x` fine. `a: b` wouldn't match because of space, so quoted. OK.

  What about a plain scalar like `2024-01-01`? numeric_string regex: `[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?` — "2024-01-01" doesn't fullmatch, so emitted unquoted → YAML parses as timestamp. Cosmetic.

  Multiline strings in steps? `_CONTROL` rejects control chars but newline (0x0a) is allowed in source content per comment — `_CONTROL` is `[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]` which excludes \n (0x0a) and \t (0x09). So a string with a newline passes `_validate_value`, then `_yaml_scalar` — newline doesn't match safe regex → json.dumps quotes it with \n escape. Good, JSON quoting escapes newlines. OK.

  5. `validate_power_platform_package` — a discrepancy: builder computes digest over package containing `file_views` sorted, each entry dict {path, media_type, digest, content}. Validator reconstructs normalized_files with same keys sorted by path. `expected = dict(package)` — keeps other keys. Then pops package_digest. But note: builder's `package` at serialization time did NOT have "package_digest" — consistent. However: builder serialnvocation anywhere: grep subprocess in power_platform_package — none (no subprocess import). power_platform_deployment has subprocess for stage execution (pre-existing).

  Also confirm `_cli_access` is existing helper. Fine.

  Verdict: The prior "critical #1" is stale — the current prepared diff includes all three files. The one remaining hard gate item is missing full-pytest/coverage evidence. I'd give: PASS conditionally — approve code, but require the full pytest + coverage ≥95% evidence before merge; explicitly acknowledge the audit exemption. No code-level security defects found.

• I have completed my independent cross-family review. I read the plan, review, the full prepared diff, and the actual on-disk sources for the core module, API, CLI, delivery plan, onboarding fixture, deployment helper, audit script, and tests.

  # Cross-Family Review: `wla-deployable-blueprint-package`

  ## Correction to the embedded prior review

  **The prior review's "Critical #1" is stale and should be disregarded.** It claimed the prepared diff omitted `src/wait_local_agent/power_platform_package.py`, `tests/test_power_platform_package.py`, and `docs/consultant-power-platform-package.md`. The current prepared diff's stat header (lines 7, 17, 21) lists all three (+852, +339, +74 lines respectively) among 21 changed files, and the files exist on disk with content consistent with the integrations that import them. The branch is not broken in the way that review feared.

  ## Blocking / gate item

  **1. Full pytest + ≥95% coverage evidence is still missing** — plan acceptance tests explicitly require "full pytest with coverage >=95%"; `review.md` and `implementation.md` admit the run was "attempted but not completed in the available run window." The docling/qdrant explanation covers two pre-existing knowledge tests, but there is no coverage number for the new 852-line module. Branches plausibly uncovered: the YAML emitter empty-collection/scalar edges, the `O_NOFOLLOW` failure path, the Windows `_pack_zip_path` branch, the `_confined_path` equality branch, and the explicit `pac.commands` folder-binding check (lines 314–326) — the digest check fires first on naive tampering, so this defense-in-depth branch is only reachable by a digest-consistent forgery, which no shown test exercises.

  ## Medium

  **2. `scripts/public_surface_audit.py` was relaxed in this diff** (+4 lines): `is_text_file` now returns `False` for any tracked file whose path contains both `ai` and `tasks` parts, exempting all of `ai/tasks/**` from the blocked-term scan. The rationale (task metadata must name agent lanes/models) is legitimate, but this is a repo-wide branding/control relaxation bundled silently into a feature task, and the substring-based part match is broader than `ai/tasks/**` literally. It should receive explicit sign-off at the gate.

  ## Low / observations

  - **YAML emitter edge cases**: empty lists/dicts serialize as `key:` + blank line (i.e., `null`, not `[]`/`{}`) — a flow with `steps: []` emits `Steps:` null; `missingdependencies.yml` is a single blank line. YAML 1.1 booleans (`on`/`off`/`y`/`n`) and date-like strings are emitted unquoted. The tree is claimed PAC-packable but PAC was never run; this is documented as unverified, so it's a truthfulness caveat, not a defect.
  - **Validation is digest/cap/tenant/path-consistent, not manifest-semantic**: `validate_power_platform_package` does not verify `solutioncomponents.yml`/`rootcomponents.yml` contents correspond to the files present. A self-consistent but incoherent hand-built package passes. Matches the letter of the acceptance tests.
  - **Path edge case**: `_safe_relative_path(".")` normalizes to `""` (empty path parts) and passes validation; materialization would fail closed (`os.open` on a directory), so no write risk, but validation could reject it earlier.
  - **Residual TOCTOU**: final-component symlinks are well handled (lexical checks + `O_NOFOLLOW` + post-write digest), but intermediate directories can be swapped by a local attacker with workspace write access between check and open. Bounded local tool; acceptable.
  - **Test gap**: no test for the CLI materialize `status: "failed"` → exit-code-1 path (only blocked/succeeded are covered).

  ## What is good

  The implementation faithfully executes the plan: pure deterministic builder (canonical JSON, SHA-256, UUID5, no clock/random/network/PAC), digest-bound PAC `--folder` with override rejection, recursive tenant isolation and layered secret rejection (keys, line-anchored YAML, JSON-embedded, Bearer/PEM patterns), fail-closed write gating returning `blocked` without touching the filesystem, pre-created-workspace confinement with symlink refusal and on-disk digest re-verification, truthful `execution_started/deployment_started: false` everywhere, review bundle kept `deployable: false` with the source package linked separately, technician scoping for build/validate and admin + write-gate for materialize in both API and CLI, bounded request models with `extra="forbid"`, and the exact required public entry points exported from `__init__.py`. Error paths are bounded; API materialize failure maps to 422 with the validation message.

  ## Verdict for Claude's final gate

  **Conditional pass — approve the code, block merge on one evidence item.** No code-level security defect or regression was found, and the prior review's "broken branch" critical is stale (the current diff includes all deliverables). Before merge: (1) produce the required full-pytest run with the ≥95% coverage figure, and (2) explicitly acknowledge the `public_surface_audit` `ai/tasks` exemption. The YAML emitter edge cases and the manifest-semantic validation gap are acceptable as documented limitations of a review-grade, never-PAC-tested source handoff; this approval is not a claim of PAC, provider, or deployment readiness.

To resume this session: kimi -r session_b937c56b-0799-42e6-8393-127a95554319

## CI follow-up review evidence

- The previously failing GitHub backend job reported 2,359 passed and 94.72%
  coverage. The follow-up adds focused defensive tests and reaches 95.01%
  locally across the full suite.
- The local run still reports only the two known optional-dependency mismatch
  tests (`docling` and `qdrant` installed while absence is expected); no package
  test fails.
- Kimi’s earlier conditional pass remains applicable to the scoped design; a
  fresh cross-family review is required for these follow-up code changes.
