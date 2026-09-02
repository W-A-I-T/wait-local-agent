# End-to-end production test — WAIT Power Platform deployment

Run 2026-09-02 against a live tenant. This is the P0 live evidence.

**Verdict: the pipeline does not work. It fails at the BUILD stage, locally, before reaching the
tenant. Nothing was imported.**

## Setup — all real, nothing mocked

| | |
| --- | --- |
| Code | `origin/main` @ `706901b` (includes #526) |
| CLI | `pac 2.4.1+g3799f3e` at `~/.dotnet/tools/pac` |
| Auth | `pac auth create` as `joseph.p@waitinc.ai` |
| Environment | `WAIT-Dev`, `https://waitdev.crm.dynamics.com/`, id `ff39da92-1031-e429-83f5-5779e7c00d15` |
| Gates | `WAIT_ALLOW_WRITE_ACTIONS=true`, `WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true`, workspace pre-created |

## What passed

1. **WAIT found and version-checked the CLI** —
   `{'available': True, 'path': '/home/josephp/.dotnet/tools/pac', 'version': '2.4.1', 'commands_executed': True}`.
   This only works because of #526; before it, WAIT could not see a dotnet-tool install at all.
2. **Package built** — `deployable: True`, `package_status: partial_source`,
   `design_only: ['modernflows/employee_onboarding']`. The honesty reporting from #520 behaved
   correctly.
3. **Materialized** — `status: succeeded`, 11 files on disk.
4. **Deployment plan** — correctly targeted the live environment URL, with both stages
   approval-gated.

## What failed

**BUILD stage: `status: failed`, "Power Platform command failed."**

Two independent defects, both now proven in the real pipeline rather than inferred.

### 1. `pac solution init` pollutes the materialized source directory

The BUILD stage runs `init` and `pack` against the **same** directory. `init` executed and wrote a
competing XML solution project into WAIT's materialized YAML tree:

```
Dataverse solution project with name 'source' created successfully in: .../e2ews/source
Dataverse solution files were successfully created for this project in the sub-directory Other
```

Directory afterwards — two competing solution definitions in one folder:

```
solutions/employee_onboarding/solution.yml     <- WAIT's YAML
src/Other/Solution.xml                         <- pac init's XML
src/Other/Customizations.xml
src/Other/Relationships.xml
source.cdsproj
.gitignore
```

`build_solution_command_plan` (`power_platform.py:207-244`) passes the same `directory` to
`init --outputDirectory` and `pack --folder`.

### 2. `pac solution pack` rejects WAIT's YAML manifests

```
Error: Expected 'MappingStart', got 'SequenceStart' (at Line: 1, Col: 1, Idx: 0).
```

`missingdependencies.yml` (WAIT emits `[]`) and `rootcomponents.yml` (WAIT emits a sequence of
`{id, schema_name, type}`) are sequence-rooted; SolutionPackager requires mapping roots. Both files
are required. `solutioncomponents.yml` is also sequence-rooted and never reached.

## Tenant state after the run

Unchanged — only the two stock solutions remain:

```
Unique Name  Friendly Name                          Version  Managed
Crc3520      Common Data Services Default Solution  1.0.0.0  False
Default      Default Solution                       1.0      False
```

No WAIT solution was created. The failure is entirely local; the tenant was never contacted by the
deployment path.

## Format finding

`pac solution clone` and `pac solution sync` in 2.4.1 have **no YAML option** — both emit XML
(`src/Other/Solution.xml` + `Customizations.xml`). The YAML source-control format appears reachable
only via Dataverse Git integration, which is why YAML ground truth could not be obtained from the
CLI. A real clone of `Crc3520` confirmed the YAML format is a mechanical projection of the XML
(element → key, attribute → `"@attr"`) — which is exactly why WAIT's `publisher.yml` is accepted and
its invented manifest shapes are not. The cloned `Solution.xml` carries `<RootComponents />` and
`<MissingDependencies />` as empty elements, so the populated shape is still unknown.

## Not a defect

The recorded command result field is `return_code`, not `returncode`. Failure detection correctly
uses `completed.returncode != 0`.
