# Consultant Power Platform XML source package

WAIT Local Agent can convert validated, credential-free consultant artifacts
into a deterministic local source package using the proven Power Platform
XML solution layout. This is a source handoff suitable for a later
operator-run `pac solution pack --folder <source-root> --zipfile <zip-path> --packagetype Unmanaged`
command. It is not a solution ZIP,
provider import, live environment verification, or deployment result.

The package contains `Other/Solution.xml`, `Other/Customizations.xml`, and
`Other/Relationships.xml` at the pack-folder root. Dataverse entities whose
logical names begin with the requested publisher prefix plus `_` and whose
primary name column is explicitly declared are emitted, along with their
confidently mapped string attributes, in
`Other/Customizations.xml`; the solution manifest, publisher block, numeric
entity root components, and missing-dependency element are emitted in
`Other/Solution.xml`. The relationships file carries the proven empty
`EntityRelationships` element. Canvas app binaries are not synthesized and
are recorded under `unsupported/components.json` with an explicit reason.
The primary name can be declared as the table's `primary_name_column` or as
`primary: true` on exactly one column. A string column's declared `max_length`
must be 1-4000; when it is absent, the package uses the documented default of
100 for both `MaxLength` and `Length`.
Modern flows remain design-only because the package does not contain a Logic
Apps `clientdata` definition. Custom connectors remain design-only because
the emitted WAIT connector metadata is not the Power Platform custom connector
definition made from `apiDefinition.swagger.json` and `apiProperties.json`.

Every source file has a SHA-256 digest and the package has a digest over its
canonical JSON representation. Component IDs are UUID5 values derived from
the tenant and stable component path. No timestamp, random value, provider
call, PAC invocation, or credential is involved.

A flow artifact must carry its trigger and actions under `power_automate`, the
same shape returned by `POST /consultant/workflows/power-automate/plan`. The
flow is retained as a design-only component with its path and reason in
`design_only_components`; no fake flow source file is emitted. It is not an
importable cloud flow definition.
An importable flow requires a `clientdata` Logic Apps definition with
`connectionReferences`, named trigger and action maps, and `runAfter` ordering;
the package does not provide those structures. A flow artifact missing
its `power_automate` section is rejected rather than packaged with empty flow
metadata.

Package readiness is reported per component class. `deployable_source` means
every emitted component class is import-complete. `partial_source` means the
package contains a usable import-complete component but also contains a
design-only emitted component, including a partially mapped entity. `deployable`
is true only when the package contains at least one import-complete artifact
component; a package containing only design-only or unsupported artifacts is
not deployable. Unsupported artifacts are not emitted into the source and
remain separately listed below. `design_only_components` lists design-only
components, including each component path, format, and reason, and is also
written to `design_only/components.json`. `unsupported_components` and
`unsupported/components.json` remain the separate record for artifact formats
with no supported XML source mapping.

## API

Technicians can build and validate a tenant-scoped package:

```text
POST /consultant/power-platform/package
POST /consultant/power-platform/package/validate
```

The consultant delivery-plan API and CLI also accept a validated
`deployable_package`; they retain the review bundle as `deployable: false` and
link the separate source package digest.

Materialization is admin-only and still requires
`WAIT_ALLOW_WRITE_ACTIONS=true`:

```text
POST /consultant/power-platform/package/materialize
```

The requested `output_directory` must be below the pre-created
`WAIT_POWER_PLATFORM_WORKSPACE`. Existing symlinks, traversal, tenant
mismatches, secret-like values, digest mismatches, and unsafe source paths are
rejected. With writes disabled, materialization returns `status: "blocked"`
without creating files. A successful result verifies every on-disk digest and
returns a PAC pack preview whose `--folder` is the validated materialization
directory, whose `--zipfile` is a deterministic sibling path inside that
directory, and whose pack type is `Unmanaged`. Packing requires no
`pac solution init`: the materialized directory already contains the complete
solution source.

## CLI

The equivalent local commands read and emit bounded JSON:

```text
wait-local-agent microsoft package build package-input.json
wait-local-agent microsoft package validate package.json
wait-local-agent microsoft package materialize package.json
```

The build and validate commands require technician scope; materialization
requires admin scope. The CLI does not execute PAC.

## Compatibility

The proven XML solution format was packed and imported with
Microsoft.PowerApps.CLI 2.4.1. The package records that minimum version and
uses the validated materialization directory as the folder. Provider
credentials, licensing, environment authorization, and deployment approval
remain separate operator responsibilities.
