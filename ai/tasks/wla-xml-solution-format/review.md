# Review — wla-xml-solution-format

Status: implementation complete; pending Kimi read-only review and Claude final gate.

## Codex implementation review

- Scope is limited to the Files Expected list; blocked paths are unchanged.
- The package emits the proven `Other/` XML layout and no generated `.yml`
  source files.
- Only `String` maps to `nvarchar`; unknown WAIT attribute types are omitted
  and recorded with an explicit field-level reason.
- Entity root components use numeric Dataverse type `1`; connectors have no
  guessed root type and are design-only.
- XML values are escaped, source ordering is deterministic, and existing
  tenant, path, size, credential, digest, symlink, and write-gate checks remain
  in place.

Static gate evidence is recorded in `implementation.md`. Pytest and pac were
not run per task instructions.

## Final gate (claude)

Must confirm against the LIVE tenant, not just unit tests:
- pac solution pack succeeds on a WAIT-materialized package
- pac solution import succeeds
- pac solution list shows the solution
- root component type is numeric 1, not the string Entity
- string attributes carry MaxLength
- connectors report design_only, not deployable_source
- no pac solution init in the build stage
- determinism preserved

Current status: pending orchestrator execution against the live tenant. Humans
retain merge and deploy authority.
