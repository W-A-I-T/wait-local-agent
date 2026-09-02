# Implementation — wla-xml-solution-format

Status: implemented; awaiting required cross-family review and live final gate.

## Follow-up producer/consumer correction

- `build_power_apps_artifact` now accepts an optional entity
  `primary_name_column`, validates it as an identifier and against the entity's
  declared fields, and carries it into `dataverse.tables`.
- The employee-onboarding demo uses the `wait_` schema names and explicitly
  declares `wait_display_name` as the primary name column, so its real artifact
  set contains an importable entity even though its unmapped date field is
  reported as design-only.
- Regression coverage calls the real producer and feeds its artifact directly
  to the XML packager, asserts the partial-source/importable-entity contract,
  covers the fully mapped string-only path, separately rejects dangling
  producer primaries, and packages the demo artifact set.

## Changes by file

- `src/wait_local_agent/power_platform_package.py`
  - Replaced the generated YAML tree with deterministic `Other/Solution.xml`,
    `Other/Customizations.xml`, and `Other/Relationships.xml` source files.
  - Modeled the manifest, publisher block, empty siblings, entity metadata, and
    string attribute metadata on the proven reference. Entity root components
    emit numeric `type="1"`, and string attributes emit `nvarchar`, `MaxLength`,
    `Length`, and `Format`.
  - Emits only confidently mapped `String` attributes. Unmapped non-primary
    WAIT types are omitted and reported while the entity remains emitted. If
    the declared or inferred primary name column is unmappable or absent, the
    whole entity and its `RootComponent` are omitted; the design-only reason
    names the primary column and either its unmapped type or its absence.
    Flows and custom connectors remain design-only records without fake source
    files; connector source is not claimed as import-complete.
  - Updated XML media-type/path validation, PAC metadata, unmanaged pack
    preview, and materialization messaging while preserving tenant scoping,
    UUID5 component derivation, bounds, digest checks, symlink rejection,
    credential exclusion, and the write gate.
- `src/wait_local_agent/power_platform.py`
  - Removed `pac solution init`; the first build command is `pac solution pack`
    with `--packagetype Unmanaged`, followed by `check`.
- `tests/test_power_platform_package.py`
  - Replaced YAML-layout assertions with XML layout, numeric root component,
    `MaxLength`, distinct non-primary versus primary unmappable-type behavior,
    connector design-only, empty-sibling, XML validation, materialization, and
    determinism assertions. Added regression coverage proving entity display
    names containing quotes, ampersands, and angle brackets remain well-formed
    and attribute-escaped in every emitted XML file.
  - Corrected real-producer expectations so an omitted date field yields
    `partial_source` while the entity remains importable, and added a
    string-only `deployable_source` variant.
- `tests/test_power_platform.py`
  - Asserts no init command and validates the pack-first unmanaged command.
- `docs/consultant/consultant-power-platform-package.md`
  - Documents the proven XML layout, no-init packing, import-complete versus
    design-only classes, and the explicit connector/flow boundaries.
- `CHANGELOG.md`
  - Added the breaking YAML-to-XML/path/digest and connector-status entry and
    reconciled the earlier flow-source wording.
- `ai/tasks/wla-xml-solution-format/implementation.md`
  - Recorded this implementation and validation evidence.
- `ai/tasks/wla-xml-solution-format/review.md`
  - Marked implementation complete and retained the required live gate.
- `ai/tasks/wla-xml-solution-format/status.json`
  - Updated ownership, touched files, stage, and next action.

## Deviations

- The existing exported `PAC_YAML_MINIMUM_VERSION` symbol remains as a
  compatibility name because the unchanged deployment module imports it. The
  XML package uses the new `PAC_XML_MINIMUM_VERSION` alias with the same
  verified CLI minimum, 2.4.1.
- Flows and connectors do not get placeholder XML root components or YAML
  replacements. The task explicitly keeps flows design-only and says the
  existing connector shape is not a real custom connector definition.
- The existing YAML serializer remains private and covered by its defensive
  tests, but is no longer used to emit package source.

## Validation gates

The approval execution-state regression test now configures a definitively
invalid `WAIT_PAC_PATH` test value, so its expected block reason is independent
of whether the developer machine has `pac` installed on `PATH`.

Passed verbatim:

```text
ruff check .
All checks passed!

mypy src/wait_local_agent/power_platform_package.py src/wait_local_agent/power_platform.py tests/test_power_platform_package.py tests/test_power_platform.py
Success: no issues found in 4 source files

Direct XML mapping smoke check
non-primary DateOnly was omitted and reported while its entity/root remained; primary DateOnly omitted the entity and RootComponent and named the type in the design-only reason
```

Not run by explicit task instruction:

- `pytest` — sandbox hangs on this repository's FastAPI `TestClient` fixtures.
- `pac` — the orchestrator will run the live tenant pack/import/list gate.

The `xml.sax.saxutils.escape` import has a targeted Bandit `B406` suppression:
it is used only to encode emitted XML, never to parse input.

Full `mypy src tests` was run and remains blocked by six pre-existing missing
`slowapi` stubs in `src/wait_local_agent/api/auth_routes.py` and
`src/wait_local_agent/api/app.py`; the four changed Python/test files pass
targeted mypy with no issues.

## Coverage follow-up

Behavior tests now cover multiple inferred primary columns, entities with no
declared columns, invalid primary metadata, invalid string lengths, all
generated XML/JSON/Markdown media-type inference paths, malformed normalized
artifact handling, PAC path-resolution failures, and invalid PAC versions.
The XML assertions verify both that withheld entities are absent from
`Other/Customizations.xml` and that their numeric root components are absent
from `Other/Solution.xml`.

The guards that rejected an empty `attributes` list or a missing declared
primary within `attributes` were removed as unreachable. During table processing
every column is added to `column_names`; a non-`String` column is also added to
`unmapped_types` and skipped, while every `String` column is appended to
`attributes`. Therefore, after the existing guards confirm that
`declared_primary` is in `column_names` and absent from `unmapped_types`, its
column was necessarily appended to `attributes`, so both later guards could
never be reached.
