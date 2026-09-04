# Power Platform live verification receipts

This is an append-only record of release-time runs against real Power
Platform tenants. A receipt records what the procedure proved and what it did
not prove; CI results and local-only package tests are not substitutes for a
dated live receipt.

## 2026-09-02 — recorded live run before the operator script (FAIL)

Source: `evidence/prior-live-run.md`.

| | |
| --- | --- |
| Code | `origin/main` @ `706901b` (includes #526) |
| CLI | `pac 2.4.1+g3799f3e` at `~/.dotnet/tools/pac` |
| Auth | `pac auth create` as `joseph.p@waitinc.ai` |
| Environment | `WAIT-Dev` · `https://waitdev.crm.dynamics.com/` · `ff39da92-1031-e429-83f5-5779e7c00d15` |
| Gates | `WAIT_ALLOW_WRITE_ACTIONS=true`, `WAIT_ALLOW_POWER_PLATFORM_DEPLOYMENT=true`, workspace pre-created |

### Proved

- WAIT resolved and version-checked the dotnet-tool PAC installation.
- WAIT built a deployable package with `package_status: partial_source` and
  design-only component `modernflows/employee_onboarding`.
- WAIT materialized 11 files locally and produced a deployment plan targeting
  the explicit live environment URL.

### Failed

The BUILD stage failed locally with `status: failed` and `Power Platform command
failed.` before the tenant was contacted. No solution was imported.

1. `pac solution init` and `pac solution pack` used the same materialized
   directory. PAC scaffolding added `src/Other/Solution.xml`,
   `Customizations.xml`, `Relationships.xml`, `source.cdsproj`, and
   `.gitignore` beside WAIT's source, creating competing solution definitions.
2. `pac solution pack` rejected WAIT's sequence-rooted YAML manifests with
   `Expected 'MappingStart', got 'SequenceStart'`. The affected manifests were
   `missingdependencies.yml`, `rootcomponents.yml`, and
   `solutioncomponents.yml`.

### Tenant state and boundary

The tenant remained unchanged with only the two stock solutions (`Crc3520`
and `Default`). The failure was entirely local. This receipt therefore does
not support the claim that the pipeline works against a live tenant; it is
the failure evidence the new pollution check and plan-driven PAC execution
must make repeatable and diagnosable.

The run also confirmed that PAC 2.4.1 `clone` and `sync` do not provide a YAML
option, and that the recorded command result field is `return_code`, not
`returncode`.
