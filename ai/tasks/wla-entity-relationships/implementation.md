# Implementation — wla-entity-relationships

Implemented on `ai/wla-entity-relationships`.

## Changes

- `build_power_apps_plan` accepts a minimal lookup field shape:
  `type: "lookup"`, `target_entity`, and an optional `display_name`.
  Lookup targets must name another entity in the same producer artifact.
- `build_power_apps_artifact` carries lookup type, target entity, and display
  name into the Dataverse schema.
- The XML package emitter writes lookup attributes and complete OneToMany
  relationships modeled on the live-verified reference. The relationship
  includes its referencing-side role, and the solution manifest includes a
  relationship root component beside both entity root components.
- Every emitted entity retains `LocalizedCollectionNames`.
- Missing targets, missing lookup columns, non-importable endpoints, and
  incomplete relationship declarations are recorded in
  `design_only_components`; no partial relationship or dangling lookup is
  emitted.

The relationship root component numeric type `10` was observed to work in the
tenant import and is recorded here as observed-working, not independently
corroborated documentation. This follows the same evidence standard used for
entity type `1`.

## Validation

- Focused relationship tests were invoked directly without pytest, as
  required by the task.
- `WAIT_REGENERATE_GOLDEN=1` was used to regenerate the existing golden
  fixture through its helper; the single-table fixture gains no relationship
  material.
- `ruff check .` and `mypy src tests` are the required final checks.
- pytest and PAC were not run.
