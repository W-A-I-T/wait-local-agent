# Consultant Power Platform YAML source package

WAIT Local Agent can convert validated, credential-free consultant artifacts
into a deterministic local source package using the official Power Platform
YAML source-control layout. This is a source handoff suitable for a later
operator-run `pac solution pack --folder <source-root> --zipfile <zip-path>`
command. It is not a solution ZIP,
provider import, live environment verification, or deployment result.

The package contains `solutions/<name>/solution.yml`,
`solutioncomponents.yml`, `rootcomponents.yml`, and
`missingdependencies.yml`; a publisher manifest under `publishers/`; and
mapped Dataverse, modern-flow, and custom-connector sources under
`entities/`, `modernflows/`, and `connectors/`. Canvas app binaries are not
synthesized. They are recorded under `unsupported/components.json` with an
explicit reason, so a package never claims a missing `.msapp` is packable.

Every source file has a SHA-256 digest and the package has a digest over its
canonical JSON representation. Component IDs are UUID5 values derived from
the tenant and stable component path. No timestamp, random value, provider
call, PAC invocation, or credential is involved.

A flow artifact must carry its trigger and actions under `power_automate`, the
same shape returned by `POST /consultant/workflows/power-automate/plan`. The
emitted `flow.yml` records the trigger type and name plus every action's unique
name, display name, kind, type, method, optional existing tool reference, and
approval flag. It is a design document, not an importable cloud flow definition.
An importable flow requires a `clientdata` Logic Apps definition with
`connectionReferences`, named trigger and action maps, and `runAfter` ordering;
the emitted source does not provide those structures. A flow artifact missing
its `power_automate` section is rejected rather than packaged with empty flow
metadata.

Package readiness is reported per component class. `deployable_source` means
every emitted component class is import-complete. `partial_source` means the
package contains a usable import-complete component but also contains a
design-only emitted component. `deployable` is true only when the package
contains at least one import-complete artifact component; a package containing
only design-only or unsupported artifacts is not deployable. Unsupported
artifacts are not emitted into the source and remain separately listed below.
`design_only_components` lists emitted design documents, including each
component path, format, and reason, and is also written to
`design_only/components.json`. `unsupported_components` and
`unsupported/components.json` remain the separate record for artifact formats
with no supported source mapping.

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
directory and whose `--zipfile` is a deterministic sibling path inside that
directory.

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

Power Platform YAML source-control support requires Microsoft.PowerApps.CLI
2.4.1 or newer. The [Microsoft YAML source-control format reference](https://learn.microsoft.com/en-us/power-platform/alm/solution-source-control-yaml-format)
documents YAML detection through
`solutions/<SolutionUniqueName>/solution.yml` and the pack command as
`pac solution pack --zipfile <zipPath> --folder <repositoryRoot>`. The package
records this minimum version and uses the validated materialization directory
as the folder. Provider credentials, licensing, environment authorization, and
deployment approval remain separate operator responsibilities.
