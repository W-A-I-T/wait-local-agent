# Review

## Changed Files

- Consultant blueprint domain, persistence, API, CLI, tests, and docs listed
  in `implementation.md`.

## Risk Areas

- Tenant scope must be resolved from authenticated context; caller-supplied
  tenant IDs are only accepted for administrators.
- Blueprint input is validated before SQLite insertion and rejects unknown,
  oversized, duplicate, and credential-like fields.
- The route is design-only and must not gain implicit execution or provider
  calls as later features are added.

## Version & Compatibility Evidence

No version or API changes.

## Open Questions

- Future discovery/architect work should decide whether blueprint revisions
  need immutable version records before adding update or rollback behavior.

## Test Results

- Verification details are stored in `ai/tasks/wla-consultant-blueprint/verification.md`.
- Passed: 5
- Failed: 1

## Diff Summary

The slice adds one local structured contract and exposes it through existing
storage and authenticated operator surfaces without adding a runtime engine or
external integration.

## Requested Review Focus

- Verify tenant isolation for create/list/detail, including admin filters.
- Verify validation occurs before persistence and no secret-bearing extension
  fields are accepted.
- Verify the surface remains inspectable-only and local-first.

## Kimi Cross-Family Review

Initial Kimi review requested changes because the API detail route allowed an
authenticated non-admin with no bound tenant to perform an unscoped lookup.
The route now rejects that case with 403, matching the list route and CLI
guard, and `test_consultant_blueprint_requires_tenant_and_role` covers the
regression. Kimi otherwise found the validation, persistence, admin filtering,
and inspectable-only boundaries consistent with the plan.

The follow-up hardening also makes `_risk` reject non-string CLI JSON values
with `BlueprintValidationError`; the CLI regression test now covers a list
value and confirms a clean `BadParameter` response.

The final hardening aligns blueprint credential-like key validation with the
existing persistence redaction token policy (`key`, `passwd`, `authorization`,
`bearer`, and `private` included) and removes the no-op field-name check.

## Kimi Cross-Family Review

[output byte limit applied]
[output line limit applied]
kimi version 0.29.2
• Let me read the task files.The diff doesn't include consultant.py (the new module) or tests/test_consultant.py. It says 6 files changed, but plan mentioned src/wait_local_agent/consultant.py, tests/test_consultant.py, docs. The diff shows only 6 files; consultant.py is imported but its diff isn't in the file — maybe it exists as untracked and not included? Let me check whether consultant.py exists in the repo.Now let's check some potential issues:

  1. **_text secret check is on field name, not value** — `_FORBIDDEN_KEY.search(field)` checks the field name, not the value content. So a value like `"password": "hunter2"` in business_goal — wait, `_business_goal` uses `_identifier(key, "business_goal key")` — the `_identifier` checks `_FORBIDDEN_KEY.search(normalized)` which checks the key value itself. Good: a business_goal key "password" is rejected. But a business_goal *string value* containing a secret is not detectable anyway (fine — can't detect secrets in arbitrary text). But _text's check `_FORBIDDEN_KEY.search(field)` — field like "solution.name" never matches, so that's a no-op except it will reject if field name contains "token" etc. Not a bug, just odd. Actually wait — there's a subtle bug: `_text` is called for `created_by` and `client_id` with field names "created_by"/"client_id" — no forbidden match. Fine.

  2. **Pydantic request model types are loose**: `users: list[object]`, etc. Since SolutionBlueprintRequest uses ConfigDict(extra="forbid"), and parse validates everything. But risk: `risk: str` in pydantic; parse re-validates. OK.

  3. **API list route: non-admin with no tenant** — raises 403 unless admin. Admin with no filter and no bound tenant gets `scoped_client_id=None` → lists ALL tenants' blueprints. That's the documented admin filter semantics. OK.

  4. **Detail route: admin without client_id and no bound tenant** — `scoped_client_id=None` → `store.get_solution_blueprint(blueprint_id, client_id=None)` → unscoped fetch, cross-tenant read. Intended for admin. OK.

  5. **Potential bug: create endpoint catches only BlueprintValidationError**, but `store.create_solution_blueprint` raises `ValueError` for missing client_id — but client_id was already validated non-None. Also `_solution_blueprint_from_row` → `parse_solution_blueprint` may raise BlueprintValidationError inside the try (it's called in store, within the same try block — actually create endpoint's try wraps `store.create_solution_blueprint` too, so BlueprintValidationError from re-parse is caught). OK.

  6. **Duplicate blueprint id**: insert with primary key conflict → sqlite3.IntegrityError → 500. Since IDs are server-generated uuid4, collision unlikely. Not user-supplied. OK.

  7. **updated_at/created_at**: parse sets both to `now` timestamp; store row stores created_at/updated_at columns, and `_solution_blueprint_from_row` passes `now=row["created_at"]` then `replace(updated_at=row["updated_at"])`. Payload doesn't include timestamps, so round-trip is consistent. But wait — on create, `blueprint.created_at` is the generated timestamp, stored in column. On read, parse uses row's created_at. Consistent.

  8. **Circular import concern**: store.py imports from consultant.py, consultant.py imports from models.py — fine. But api/app.py imports store and consultant — fine.

  9. **`risk` in payload stored via `blueprint_payload` as `blueprint.risk` — a str Literal. Fine.

  10. **Missing tests**: tests/test_consultant.py exists (in glob). The diff didn't include it, but it's presumably new file not in the diff (the diff shows only 6 files — test_consultant.py not included in diff stat, which is odd; maybe prepared diff omitted untracked/new files? Actually consultant.py is also missing from the diff stat yet it exists). The diff summary says "6 files changed, 496 insertions" — consultant.py and test_consultant.py absent. Perhaps the diff tool only captured tracked modifications? Anyway, files exist in the tree.

  11. **Docs**: plan said docs/architecture.md or focused doc; diff shows no docs file. Let me check if docs were added.

  12. **API: 403 for viewer create** — viewer create returns 403 via TechnicianAccess presumably. Test asserts 403. OK.

  13. **Potential issue: `_consultant_client_scope` for list route with non-admin and bound tenant and requested == bound** returns bound — fine.

  14. **CLI show: doesn't accept --client-id**, so an admin with no bound client_id gets scoped None → unscoped fetch; non-admin bound uses bound. Fine. But a non-admin CLI user can't pass --client-id to show even matching their bound tenant — minor.

  15. **Secret-in-payload check**: `_identifier` rejects identifiers containing "token" etc. But a blueprint could still include `{"business_goal": {"note": "my password is X"}}` — can't prevent free text; acceptable per design ("do not accept credentials" via field-name rejection).

  16. **Check `_text` control character check**: allows \t and \n. Fine.

  17. **Potential regression in store.py**: import of consultant at module top of store — consultant imports models only, no cycle. OK.

  18. **API route ordering**: `/consultant/blueprints/{blueprint_id}` after `/consultant/blueprints` — fine.

  19. **The `parse_solution_blueprint` in `_solution_blueprint_from_row`**: validates stored payload — if validation rules change, old rows become unreadable (RuntimeError or BlueprintValidationError propagates as 500). Noted in review open questions. Minor.
... [output lines omitted] ...

  `GET /consultant/blueprints/{blueprint_id}` in `api/app.py` never checks for a `None` scope:

  ```python
  scoped_client_id = _consultant_client_scope(context, client_id)
  blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped_client_id)
  ```

  `_consultant_client_scope` returns `None` for a **non-admin principal with no bound tenant** (it only raises when a mismatched tenant is explicitly requested). `store.get_solution_blueprint(..., client_id=None)` then runs an **unscoped** `where id = ?` query — returning any tenant's blueprint by ID. Compare:

  - The sibling **list** route guards this: `if scoped_client_id is None and context.role < Role.ADMIN: raise 403`.
  - The pre-existing `smart_action_run_detail` guards the identical case with a 404 (`app.py:405`).
  - The CLI `show` command also guards it.

  So the new detail route is the only surface where an authenticated tenant-less viewer/technician can read cross-tenant blueprint content. This is reachable: your own test (`test_consultant_blueprint_requires_tenant_and_role`) proves non-admin tokens authenticate with no `client_id` configured. Blueprint IDs are `bp_<uuid4 hex>` so not directly guessable, but they leak via audit/event-history records, and the plan's acceptance test explicitly requires "tenant-scoped list/detail routes do not disclose another tenant's blueprint." Fix: mirror the list-route guard (403 or 404) before the store call.

  **Missing test:** no test covers the unbound non-admin detail case (the create path's equivalent case is tested and passes because create *does* guard). Add one alongside the fix.

  ### Minor observations (non-blocking)

  - **Silent redaction at persistence:** `create_solution_blueprint` serializes via `_json_dumps`, which runs `redact_value`. Free-text blueprint content matching secret-like patterns (e.g. `api_key=<redacted> inside a string value, AWS key patterns) is silently rewritten in the stored record while the API still returns 201. This matches repo-wide convention and is defensible as defense-in-depth, but it means the persisted artifact can differ from the validated input without any signal — worth a note in `docs/consultant-blueprints.md`.
  - **Dead/misleading check:** `_text()` tests `_FORBIDDEN_KEY.search(field)` — the *field name*, never the value — which is a no-op for all current call sites. The real secret-key protection lives in `_identifier`'s value check. Harmless, but confusing.
  - `store.create_solution_blueprint` can raise `ValueError`/`RuntimeError` that would surface as a 500 rather than 4xx; currently unreachable from the API path, so acceptable.
  - Unbounded integers in `business_goal` values (JSON bigint); bounded only by request body limits. Negligible.

  ### What checks out

  - Validation runs strictly before persistence; unknown/oversized/duplicate/credential-key inputs are rejected with actionable 422s and no partial writes (tested, including post-rejection row counts).
  - `create table if not exists` preserves existing SQLite databases; round-trip across a fresh `Store` is tested.
  - Create requires Technician+, list/detail Viewer+; cross-tenant create/list/detail for *bound* principals correctly 403/404 (tested). Admin tenant filter semantics work.
  - Collection sizes (32), text lengths (240/500), identifier charset, risk enum, and control characters are all deterministically bounded; duplicate agent/workflow IDs rejected.
  - Surface is inspectable-only: no provider, network, tool, or deployment calls anywhere in the new code; docs file exists and matches scope.
  - CLI mirrors the API scoping logic correctly (including the unbound-non-admin guard that the API detail route lacks) and emits scriptable JSON.

  ### Verdict

  **Request changes** — one concrete fix: add the missing `scoped_client_id is None and role < ADMIN` guard to `GET /consultant/blueprints/{blueprint_id}` (matching the list route and `smart_action_run_detail` precedent), plus a regression test for the unbound non-admin detail case. Everything else is solid and consistent with the plan's constraints; the minor items above are advisory only.

To resume this session: kimi -r session_1467d06c-5a64-44dc-a0f8-122f8b849bef

## Kimi Cross-Family Review

[output byte limit applied]
[output line limit applied]
kimi version 0.29.2
• Let me read the task files.The diff references `consultant.py` (imported) but it's not in the diff — need to read the actual file. Also tests/test_consultant.py and docs. Let me read those files.Now let me verify key claims in the code. Check a few things:

  1. `_consultant_client_scope` in app.py — verify context.client_id normalization helper `_normalize_client_id` exists in app.py.
  2. `_cli_access` behavior — does it exist? It's pre-existing presumably.
  3. `_json_dumps` and `redact_value` — silent redaction in store.
  4. `_add_audit_event`, `_add_event_history` signatures — check positional/keyword args match.
  5. Check `blueprint_payload` payload doesn't include created_by etc. — on read, `_solution_blueprint_from_row` passes `created_by=str(row["created_by"])`. But wait: stored `created_by` column is set from blueprint.created_by. In `_solution_blueprint_from_row`, `parse_solution_blueprint(..., created_by=str(row["created_by"]), now=str(row["created_at"]))` — parse validates created_by via `_text`. OK.

  6. Round-trip equality issue: `_solution_blueprint_from_row` returns `replace(blueprint, updated_at=row["updated_at"])`. On create, updated_at == created_at. Test asserts persisted == blueprint. OK.

  7. Potential bug: `_json_dumps` applies redaction. If payload contains redactable pattern, stored payload differs from validated input, and on read parse re-validates — redacted text like "<redacted>" still passes validation (non-empty). Equality test only uses safe values. OK.

  8. A subtle issue: `parse_solution_blueprint` with `risk` key — `_risk` checks `value not in {"low","medium","high"}` — if value is unhashable (e.g. list), `in` on a set would raise TypeError. Actually `[] in {"low"}` — set membership requires hashable; list is unhashable → TypeError, not BlueprintValidationError → 500. Pydantic declares `risk: str`, so API path is protected by pydantic. But the CLI path reads raw JSON and calls parse directly — a CLI user passing `"risk": []` would get an unhandled TypeError → traceback instead of BadParameter. Also business_goal values with floats are rejected properly. Also `risk: 1`? `1 in {"low"...}` is fine (hashable). So CLI with risk as list → crash. Minor robustness bug on CLI surface only. Also direct store path. Worth flagging as minor.

  Similarly `_identifier` uses `_text` which handles non-str. `_object` handles non-dict. `payload["agents"]` list of non-dict handled. What about `agents` list containing dict with "tools" being a dict? `_text_list` requires list → error raised properly. Fine.

  9. Check `_normalize_client_id` in app.py exists (used by `_consultant_client_scope`). It's pre-existing per diff context. Let me grep.

  10. Check `_add_event_history` signature — positional args: (connection, event_type, ref_id, status, message, payload_json, client_id)? Let me verify.

  11. Check `context.approver_id` exists on AuthContext.

  12. Check RBAC: `TechnicianAccess`/`ViewerAccess` exist. And `context.role < Role.ADMIN` — Role ordering.

  13. Duplicate blueprint ID handling: store.create insert → sqlite3.IntegrityError if id collision. Server-generated; fine.

  14. Detail route path ordering: `/consultant/blueprints/{blueprint_id}` vs `/consultant/blueprints` — GET vs POST, fine.

  15. Timestamps: `now or datetime.now(UTC).isoformat()` — created_at from API is current time; fine.

  16. Missing: no test for show CLI cross-tenant for admin? Minor.

  Let me verify a few signatures in app.py and store.py.

• Let me verify some referenced helpers and signatures in the surrounding code.

• Now check `_normalize_client_id` in app.py (used by `_consultant_client_scope`), `AuthContext.approver_id`, `_cli_access` signature, `_json_dumps` in store.py (redaction), and the `_risk` unhashable TypeError concern. Also check `Role` ordering (IntEnum?).`_normalize_client_id` doesn't exist at module top of app.py with that exact pattern? It returned no matches for `^def _normalize_client_id` in app.py. Maybe it's defined inside create_app or imported from elsewhere. Grep the whole app.py.Good — `_normalize_client_id` is imported from store. `approver_id` exists on AuthContext. Role ordering used elsewhere similarly.

  Now check the previous Kimi review's fix: detail route guard — present in the diff (lines with `if scoped_client_id is None and context.role < Role.ADMIN: raise 403`). Fixed and tested (`test_consultant_blueprint_requires_tenant_and_role` asserts `unbound_detail.status_code == 403`).
... [output lines omitted] ...

  5. Test gaps (minor): no CLI test for `show` not-found / unbound-non-admin `show` guard; no API test for oversized text / forbidden-key 422 (covered at domain level though); no test for non-string risk via CLI.

  Also verified: tenant scoping create/list/detail, admin filter semantics, `_add_audit_event`/`_add_event_history` signatures match call sites, `_normalize_client_id` imported from store, Role IntEnum ordering, redact never empties strings (so re-parse can't break on emptiness), no network/provider/tool calls in consultant.py, table created with `create table if not exists`, docs exist and match scope, CLI has no secret-bearing options (only token envvar, consistent with repo).

  Verdict: Approve — prior blocking issue fixed with regression test; remaining items are minor/advisory, recommend (non-blocking) hardening `_risk` against non-string input on the CLI path.

• ## Cross-Family Review: `wla-consultant-blueprint`

  I read the plan, review notes (including the prior Kimi round), the prepared diff, and the files the diff omits (`consultant.py`, `tests/test_consultant.py`, `docs/consultant-blueprints.md`), and verified the surrounding helpers (`_add_audit_event`/`_add_event_history` signatures, `_normalize_client_id` import, `Role` IntEnum ordering, `AuthContext.approver_id`, `redact_value` behavior).

  ### Prior blocking issue — verified fixed
  The unscoped cross-tenant read on `GET /consultant/blueprints/{blueprint_id}` is now guarded (`scoped_client_id is None and role < ADMIN` → 403), matching the list route and the CLI, and `test_consultant_blueprint_requires_tenant_and_role` covers the regression. Fix is correct.

  ### Findings

  **1. Minor bug: `_risk` crashes on unhashable input via the CLI path.**
  `consultant.py:249` does `if value not in {"low", "medium", "high"}` — set membership on an unhashable value raises `TypeError`, not `BlueprintValidationError`. The API is safe (Pydantic `risk: str` rejects non-strings with 422 first), but the CLI feeds raw JSON from disk straight into `parse_solution_blueprint` and only catches `OSError`/`JSONDecodeError`/`BlueprintValidationError` — so `"risk": []` or `"risk": {}` in a blueprint file produces an unhandled traceback instead of a clean `BadParameter`. Fix is one line: `if not isinstance(value, str) or value not in {...}`. Missing test: CLI failure path with a non-string `risk`.

  **2. Advisory: read path re-validates stored rows.**
  `_solution_blueprint_from_row` re-runs `parse_solution_blueprint` on every read; if validation rules tighten later, previously valid rows raise `BlueprintValidationError`/`RuntimeError`, and only the *create* route catches that exception — list/detail would 500. Already noted in the review's open questions; consider catching it in read routes or separating read-path deserialization from create-path validation.

  **3. Advisory: dead check in `_text`.**
  `_FORBIDDEN_KEY.search(field)` tests the field *name* (always things like `"solution.name"`), never the value — a no-op at all current call sites. The real credential-key protection lives in `_identifier`. Harmless but misleading to future maintainers.

  **4. Test gaps (minor):** no CLI test for `show` not-found or the unbound-non-admin `show` guard; oversized-text/forbidden-key rejection is covered at domain level but not asserted as a 422 through the API (only `risk` is). Acceptable coverage, but these are cheap additions.

  ### What checks out
  - Validation runs strictly before persistence; no partial writes on rejection (row-count asserted after a 422).
  - Tenant isolation on create/list/detail for bound principals (403/404 without existence disclosure), admin filter semantics, and the unbound-non-admin case on all three surfaces — all tested.
  - `_add_audit_event`/`_add_event_history` call-site signatures match; event history is written in the same transaction; `create table if not exists` preserves existing databases; round-trip across a fresh `Store` is tested including payload equality.
  - `redact_value` never empties strings, so persistence-time redaction can't break read-path re-validation; the redaction divergence is documented in `docs/consultant-blueprints.md`.
  - Surface is inspectable-only: no provider, network, tool, or deployment calls anywhere in the new code; CLI has no secret-bearing options; deterministic bounds (32 items, 240/500 chars, identifier charset, risk enum, control characters, duplicate IDs) all enforced.

  ### Verdict for the final gate

  **Approve.** The previously identified cross-tenant detail-route hole is fixed with a regression test, and the implementation satisfies the plan's constraints. Finding 1 (CLI `_risk` TypeError on non-string JSON input) is a genuine but low-severity robustness bug worth a one-line hardening fix and test — non-blocking for merge. Findings 2–4 are advisory.

To resume this session: kimi -r session_6ee806a2-b571-4717-8b78-7f2eec8a7f9c

## Kimi Cross-Family Review

[output byte limit applied]
[output line limit applied]
kimi version 0.29.2
• Let me read the task files.The diff omits consultant.py, tests/test_consultant.py, and docs. Let me read those files to verify independently.

• The prepared diff omits the new `consultant.py` module, `tests/test_consultant.py`, and docs. Let me read those files directly, since the core validation logic lives there.

• Now let me verify key surrounding-code facts myself rather than trusting prior Kimi review claims:

  1. `_risk` non-string fix — consultant.py:249 now has `not isinstance(value, str) or ...` — fixed. Good.
  2. `_text` forbidden-key check on field name — dead check confirmed (line 152).
  3. `_normalize_client_id` exists in store.py (defined at bottom per diff). app.py imports it? Let me check.
  4. `Role` ordering, `ViewerAccess`, `TechnicianAccess`, `context.approver_id`, `_add_audit_event`/`_add_event_history` signatures.
  5. `_json_dumps` redaction.
  6. Check risk Literal in models.py — `RiskLevel` used in SolutionBlueprint, and `BlueprintRisk` in consultant. Check RiskLevel is Literal["low","medium","high"].
  7. Potential issue: `parse_solution_blueprint` strict top-level fields — API request excludes client_id before dumping; pydantic extra=forbid covers client_id separately. But what about pydantic model requiring all fields? `SolutionBlueprintRequest` fields all required (no defaults) — missing field → 422 pydantic. Good.
  8. Check the CLI `create` requires `risk` etc — missing fields → BlueprintValidationError caught. Good.
  9. Check `blueprint_view` returns "risk" as str.
  10. Check `agents` tool entries — `_text_list(item.get("tools", []))` — default [] fine.
  11. Potential: API detail route for admin with requested client_id → scoped fetch. Fine.
  12. `list_solution_blueprints` ordering by created_at — ties broken by id desc; timestamps same-second isoformat includes microseconds. Fine.
  13. One concern: `_consultant_client_scope` for non-admin with bound tenant and no requested → returns bound. Admin with requested → requested. OK.
  14. Circular import: store.py imports consultant; consultant imports models only. OK.
  15. Check that `_json_dumps` applies redaction and check `redact_value` behavior.
  16. Check docs file quickly.
  17. Check `_add_audit_event` signature (client_id kw).
  18. Check `RiskLevel` in models.

  Also potential bug: In API create, `payload.model_dump(exclude={"client_id"})` — but SolutionBlueprintRequest has fields typed loosely (list[object]). Pydantic model_dump includes all. Then parse validates. Fine.

  Another potential: The pydantic model requires `approvals: dict[str, object]`, and parse requires values be str via `_text`. If approver is int → BlueprintValidationError → 422. Fine.

  Potential issue: unbounded int in business_goal — JSON bigint; sqlite json stored as text; fine, negligible.

  One more: `_identifier` with allow_prefix=True for blueprint id; generated ids `bp_<hex>` match regex. Client-supplied agent ids can't start with bp_ — odd but harmless.

  Potential: parse accepts `blueprint_id` param — store read path passes row id. API create doesn't accept client-supplied id. Good.

  Check `_cli_access` and auth: CLI show with no --client-id for admin → scoped None → unscoped fetch. Admin OK.

  Let me verify the surrounding helpers quickly with grep.Signatures check out. Now check `redact_text` — does it ever return empty string? Check renderers.redact_text. Also check `_add_event_history` positional args: (connection, event_type, subject_id, status, message, payload_json, client_id?) — the call site passes 7 positional args; let me see the signature after payload_json.Redact_text never returns empty for non-empty input — "<redacted>" is non-empty. But wait: redact_mapping could redact a whole dict key if a key matches sensitive tokens. In blueprint payload, top-level keys are fixed ("solution", etc.), business_goal keys are identifiers validated to not contain forbidden words — but `_is_sensitive_key` tokens include "key" — business_goal identifier regex allows "key" as a value? Identifier like "apikey"? `_identifier` rejects forbidden key pattern "api[_-]?key" — "apikey"? Pattern is `api[_-]?key` — matches "apikey" (the [_-]? is optional). Good. But what about SENSITIVE_KEY_TOKENS broader than _FORBIDDEN_KEY? E.g. a business_goal key "token" — _FORBIDDEN_KEY rejects "token". What about a key that redact_mapping considers sensitive but _FORBIDDEN_KEY doesn't? Check SENSITIVE_KEY_TOKENS. If e.g. tokens include "passphrase" and _FORBIDDEN_KEY doesn't include it, then validated input could have business_goal key "passphrase" which gets redacted at persistence to "<redacted>" — value replaced, key intact. Then read-path re-parse: business_goal value "<redacted>" is a string, passes _text. Key "passphrase" passes _identifier. Fine, no crash, just silent divergence.

... [output lines omitted] ...
  Everything the prior Kimi rounds flagged is addressed. My independent findings:

  - Confirmed no blocking issues.
  - New minor: consultant `_FORBIDDEN_KEY` and renderer `SENSITIVE_KEY_TOKENS` mismatch — blueprint accepts keys like "key", "bearer", "authorization", "passwd", "private" in business_goal/approvals that persistence-time `redact_mapping` will silently rewrite to "[redacted]". Silent divergence between validated input and stored record; plan says "store only the declared blueprint fields; do not accept credentials" — arguably these keys should be rejected at validation for consistency. Low severity (data-fidelity, not security — redaction is conservative).
  - Dead check in `_text` (advisory).
  - Read-path re-validation 500 risk on future rule tightening (advisory).
  - Test gaps: CLI show not-found/unbound, API 422 for oversized/forbidden-key inputs.

  Verdict: Approve.

• # Cross-Family Review: `wla-consultant-blueprint`

  I independently read the plan, the prior review notes (both Kimi rounds), the prepared diff, and the files the diff omits (`consultant.py`, `tests/test_consultant.py`, `docs/consultant-blueprints.md`), and verified the surrounding contracts (`_add_audit_event`/`_add_event_history` signatures, `_normalize_client_id` import, `Role` IntEnum ordering, `AuthContext.approver_id`, `redact_value`/`redact_mapping` behavior).

  ## Prior blocking findings — verified fixed

  1. **Cross-tenant unscoped detail read** — `GET /consultant/blueprints/{id}` now guards `scoped_client_id is None and context.role < Role.ADMIN` → 403 (app.py, matching the list route), and `test_consultant_blueprint_requires_tenant_and_role` asserts the regression. Correct fix.
  2. **`_risk` TypeError on non-string CLI JSON** — `consultant.py:249` now checks `not isinstance(value, str)` before set membership, and `test_consultant_blueprint_cli_rejects_non_string_risk` covers `"risk": []` → clean `BadParameter`. Correct fix.

  ## Findings (none blocking)

  1. **Minor: validation/redaction key-policy mismatch.** `consultant._FORBIDDEN_KEY` rejects `secret|token|password|credential|api[_-]?key|private[_-]?key` in identifiers, but persistence runs `redact_mapping` whose `SENSITIVE_KEY_TOKENS` also includes bare `key`, `passwd`, `authorization`, `bearer`, `private`. So a `business_goal`/`approvals` key like `"key"` or `"bearer"` passes blueprint validation, then its value is silently rewritten to `[redacted]` in the stored record while the API returns 201. Read-path re-parse still succeeds (`[redacted]` is non-empty text), so no crash — but the persisted artifact diverges from validated input, and the plan says credential-like fields should not be accepted. Aligning the two token sets (or validating against `SENSITIVE_KEY_TOKENS`) would close this. Low severity: the divergence is conservative (more redaction, not less) and partially documented in `docs/consultant-blueprints.md`.
  2. **Advisory: dead check.** `_text()` at `consultant.py:152` tests `_FORBIDDEN_KEY.search(field)` — the field *name* (`"solution.name"`, `"client_id"`, …), never the value — a no-op at every call site. The real protection is in `_identifier`. Misleading to future maintainers.
  3. **Advisory: read-path re-validation.** `_solution_blueprint_from_row` re-runs full `parse_solution_blueprint` on every read; if validation rules ever tighten, previously valid rows would raise `BlueprintValidationError` out of list/detail routes as a 500 (only create catches it). Fine today; consider separating read deserialization from create validation.
  4. **Test gaps (cheap, optional):** no CLI test for `show` not-found or the unbound-non-admin `show` guard; oversized-text/forbidden-key rejection is domain-tested but not asserted as a 422 through the API (only `risk` is).

  ## What checks out

  - Validation runs strictly before persistence; unknown/missing/oversized/duplicate/credential-key inputs rejected with actionable 422s and no partial writes (row count asserted post-rejection).
  - Tenant isolation verified on create/list/detail for bound principals (403/404 without existence disclosure), admin filter semantics, and unbound non-admin on all surfaces — all tested. `Role` IntEnum ordering and `_normalize_client_id` behavior confirmed.
  - SQLite: `create table if not exists` preserves existing databases; audit event + event history written in the same transaction; signatures match call sites; fresh-`Store` round-trip with payload equality tested.
  - Redaction can't break re-parse (`REDACTED` is non-empty); duplicate blueprint IDs are server-generated uuid4, so `IntegrityError`→500 is unreachable in practice.
  - Inspectable-only boundary holds: no provider, network, tool, or deployment calls anywhere in the new code; CLI has no secret-bearing options; docs match implemented scope without overclaiming Microsoft integration.

  ## Verdict for Claude's final gate

  **Approve.** Both previously identified blocking issues are fixed with regression tests, and the implementation satisfies the plan's constraints (local-first, tenant-scoped, validated-before-persistence, inspectable-only, schema-compatible). Finding 1 (key-policy mismatch between blueprint validation and persistence-time redaction) is a genuine low-severity data-fidelity issue worth a follow-up; findings 2–4 are advisory. Nothing here warrants blocking the merge.

To resume this session: kimi -r session_f4b9d7a5-a72c-4872-922e-18aafdccac41

## Kimi Cross-Family Review

[output byte limit applied]
[output line limit applied]
kimi version 0.29.2
• Let me read the files.I'm the new independent reviewer. The review.md includes prior Kimi rounds (some of which may be from prior AI reviewers). I should independently verify. Let me read consultant.py, tests/test_consultant.py, verification.md, and docs/consultant-blueprints.md, plus check surrounding helpers.

• The review notes embed prior Kimi rounds, but I need to verify independently. Let me read the files the diff omits plus verification evidence.

• Note the bare `pytest` failed due to environment (missing slowapi module, no PYTHONPATH presumably) — documented environment limitation. The primary run with PYTHONPATH passed.

  Now let me read tests/test_consultant.py and docs/consultant-blueprints.md, and verify some surrounding facts: `_json_dumps` redaction, `_add_audit_event`/`_add_event_history` signatures, `_normalize_client_id` in store, `_cli_access`, Role ordering. Also check a subtle point: `_identifier` checks `_has_forbidden_key(normalized)` but the current consultant.py uses token-set approach now (differs from prior reviews' description). Note `_has_forbidden_key` includes "key", "passwd", "authorization", "bearer", "private" — aligning with redaction policy per review.md note about "final hardening".

  Also verify RiskLevel in models.py exists. Let me check relevant helpers.Now verify the surrounding helpers myself: `_json_dumps` in store (redaction), `_add_audit_event` and `_add_event_history` signatures, `_normalize_client_id` in store, `_cli_access`, Role ordering, AuthContext.approver_id, redact behavior.Signatures check out. Now a few independent things I want to verify myself:

  1. The current `_has_forbidden_key` uses token-set approach — identifiers like "create_user" pass; "bearer" rejected (test covers "bearer" in approvals). But: `redact_mapping`/`redact_value` behavior — does redaction of blueprint payload cause silent divergence? Consultant `_FORBIDDEN_KEY_TOKENS` includes key/passwd/authorization/bearer/private now, aligned with SENSITIVE_KEY_TOKENS per review. Let me check SENSITIVE_KEY_TOKENS in renderers to confirm alignment claim.

  2. Check `_has_forbidden_key` edge cases: identifier regex only allows lowercase `[a-z0-9_.:-]`, so camelCase branch in `_has_forbidden_key` is dead for identifiers (identifiers can't contain uppercase). Fine.

  Potential bypass: tokenization splits on non-alphanumeric; "api.key" → tokens "api","key" → "key" in forbidden set → rejected. "mykeys"? Token "mykeys" not in set; "".join → "mykeys" not in {"apikey","privatekey"} → allowed. But would redact_mapping redact "mykeys"? Check SENSITIVE_KEY_TOKENS matching (substring vs token).

  3. Check demo mode: API tests use demo_mode False. In demo mode with no tokens, resolve_auth_context presumably returns ADMIN. Fine.

  4. CLI create: reads file, parse; the `_cli_access` requires Role.TECHNICIAN. In the non-string risk test, no tokens set and demo mode presumably default? They set WAIT_CLIENT_ID and WAIT_DATA_PATH only. If demo_mode default true, _cli_access returns admin context. OK.

  5. Potential issue in CLI create: `Store(settings.data_path)` — is data_path the db path? In the test they set WAIT_DATA_PATH to state.db, consistent with other CLI tests presumably.

  6. One thing to check: API create route — `payload.model_dump(exclude={"client_id"})` includes all 10 required top-level fields. parse requires exactly _TOP_LEVEL_FIELDS — matches. Good.

  7. Detail route: admin with no client_id and no bound → scoped None → unscoped fetch. Intended admin behavior, documented.

  8. check redact_value: does it redact by key names within nested dicts (business_goal keys)? Let me check renderers redact_value / SENSITIVE_KEY_TOKENS.Key policies are now aligned (identical token sets), so the prior "key-policy mismatch" finding is resolved — `_FORBIDDEN_KEY_TOKENS` == `SENSITIVE_KEY_TOKENS`. But one subtle check: redact `_is_sensitive_key` uses `"".join(tokens) in SENSITIVE_KEY_TOKENS` while consultant's `_has_forbidden_key` uses `"".join(tokens) in {"apikey","privatekey"}`. Since SENSITIVE_KEY_TOKENS contains only single tokens, "".join of multiple tokens would only match if join equals a token, e.g. "privatekey"? "privatekey" not in SENSITIVE_KEY_TOKENS set ("private" and "key" are separate). Hmm: consultant rejects joined "apikey"/"privatekey" explicitly. For redaction, "apikey" → tokens = ["apikey"], intersection with tokens set: "apikey" not in set; joined "apikey" not in set → not redacted! But consultant rejects "apikey" identifier. OK so consultant is stricter there. What about redaction matching something consultant allows? Redact tokens: same token set. Consultant: intersection or joined in {apikey, privatekey}. Renderer: intersection or joined in SENSITIVE_KEY_TOKENS (single-word joined only realistically). Identifier regex lowercases only; renderer's `_normalized_key_tokens` handles camelCase. Identifiers can't have uppercase so equivalent. So validated keys will never be redacted at persistence now — mismatch resolved. Good.

  Free-text values: redact_text can rewrite values containing "password=<redacted> patterns silently. That's documented in docs. OK.

  Now, independent checks on remaining concerns:

  1. `_text` no longer has the dead field-name check — confirmed, current `_text` (lines 156-164) has no `_FORBIDDEN_KEY` check. Prior review's "dead check" was removed.

  2. Read-path re-validation: `_solution_blueprint_from_row` re-parses on read. If stored payload was redacted such that a value becomes "[redacted]" — non-empty, passes. But what if redact_text makes a string > max length? No—redaction only shortens/replaces. Could redaction make business_goal int? No. OK.

  Edge: redact_text pattern matches e.g. "key: value" inside free text users list — value replaced with "[redacted]"; re-parse passes. Fine.

  3. Potential new issue: `_identifier` — `allow_prefix` only for blueprint id.dation (`_solution_blueprint_from_row` re-runs full `parse_solution_blueprint`); future validation tightening → 500s on list/detail. Only create catches BlueprintValidationError. Advisory.
... [output lines omitted] ...
  One more thing to double-check: `_has_forbidden_key` joined check {"apikey","privatekey"} vs renderer's joined check in SENSITIVE_KEY_TOKENS — consultant is stricter; no redaction-without-validation divergence. Good.

  Also `_identifier` applied to business_goal keys/approvals actions — means keys like "reduce manual onboarding" (with spaces) rejected; fine, deterministic.

  Potential nit: CLI `create` validates scope before reading the file — error precedence fine.

  Timestamps: created_at/updated_at identical forever (no update route). Fine per scope.

  Verdict: Approve.

• # Cross-Family Review: `wla-consultant-blueprint`

  I independently read the plan, review notes (including the three embedded prior Kimi rounds), the prepared diff, and the files the diff omits (`consultant.py`, `tests/test_consultant.py`, `docs/consultant-blueprints.md`), and verified the surrounding contracts myself: `Role` IntEnum ordering, `AuthContext.approver_id`, `resolve_auth_context`, `_normalize_client_id` (defined in store, imported by app.py), `_add_audit_event`/`_add_event_history` signatures vs. call sites, `_json_dumps` redaction, and `SENSITIVE_KEY_TOKENS` in renderers.

  ## Prior findings — verified fixed

  1. **Cross-tenant unscoped detail read** — `GET /consultant/blueprints/{id}` now guards `scoped_client_id is None and context.role < Role.ADMIN` → 403, matching the list route and CLI; `test_consultant_blueprint_requires_tenant_and_role` covers it. Correct.
  2. **`_risk` TypeError on non-string CLI JSON** — `consultant.py:259` now checks `isinstance(value, str)` first; `test_consultant_blueprint_cli_rejects_non_string_risk` covers `"risk": []` → clean `BadParameter`. Correct.
  3. **Validation/redaction key-policy mismatch** — resolved: `_FORBIDDEN_KEY_TOKENS` is now token-identical to `SENSITIVE_KEY_TOKENS`, and consultant's joined-token check (`apikey`/`privatekey`) is strictly stricter than the renderer's, so no validated key can be silently redacted at persistence. The dead `_text` field-name check is also gone.

  ## New findings (none blocking)

  1. **Advisory: read-path re-validation.** `_solution_blueprint_from_row` re-runs full `parse_solution_blueprint` on every read; only the create route catches `BlueprintValidationError`. If validation rules ever tighten, previously valid rows would surface as 500s from list/detail. Fine today (redaction can't empty strings or break types — verified), but consider separating read deserialization from create validation.
  2. **Advisory: silent persistence-time redaction of free text.** Values matching `_SENSITIVE_TEXT_PATTERN` (e.g. `password: <redacted> inside a `users` entry) pass validation but are rewritten to `[redacted]` in the stored payload, audit, and event history. Conservative direction, consistent response (create returns the re-read row), and now documented in `docs/consultant-blueprints.md` — acceptable.
  3. **Test gaps (cheap, optional):** no CLI test for `show` not-found or the unbound-non-admin `show` guard; oversized-text/forbidden-key rejection is domain-tested but not asserted as a 422 through the API. `consultant.py` sits at 80% coverage vs. the repo's ~95% norm (the aggregate gate still passes).

  ## What checks out

  - Validation runs strictly before persistence; unknown/missing/oversized/duplicate/credential-like inputs rejected with actionable 422s, no partial writes (row count asserted post-rejection).
  - Tenant isolation on create/list/detail for bound principals (403/404 without existence disclosure), admin filter semantics, and the unbound-non-admin case on all three surfaces — all tested. Auth helpers and signatures verified against call sites.
  - `create table if not exists` preserves existing databases; audit + event history written in the same transaction; fresh-`Store` round-trip with payload equality tested.
  - Inspectable-only boundary holds: no provider, network, tool, or deployment calls anywhere in the new code; CLI has no secret-bearing options; docs don't overclaim Microsoft integration.
  - The failed bare `pytest` in verification.md is environmental (missing `slowapi`, wrong interpreter, no `PYTHONPATH`) and documented; the primary gated run passed with 95.39% coverage, plus ruff/mypy/compileall clean.

  ## Verdict for Claude's final gate

  **Approve.** All previously identified blocking issues are fixed with regression tests, and the implementation satisfies the plan's constraints (local-first, tenant-scoped, validated-before-persistence, inspectable-only, schema-compatible). The remaining findings are advisory hardening items, not merge blockers.

To resume this session: kimi -r session_f263680b-cec0-48fe-b411-bb3e8ae8a3dd

