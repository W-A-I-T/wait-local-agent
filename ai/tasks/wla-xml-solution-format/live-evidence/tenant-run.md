# Live gate run #1 — PASS

Date: 2026-09-02
Tenant: `WAIT-Dev` · `https://waitdev.crm.dynamics.com/` · env id `ff39da92-1031-e429-83f5-5779e7c00d15`
CLI: `pac 2.4.1+g3799f3e (.NET 10.0.11)` at `~/.dotnet/tools/pac`
Auth: `pac auth create` as `joseph.p@waitinc.ai`
Branch: `ai/wla-xml-solution-format`

**First time WAIT's own pipeline produced a solution that Dataverse accepted.** Nothing hand-built.

## Run 1 — publisher prefix `wait`, solution `waitgate`

```
1 BUILD    deployable=True status=deployable_source
           design_only: none
2 VALIDATE ok, digest sha256:e34082a3e5344b520
3 MATRLZE  status=succeeded
4 PACPLAN  ["pac","solution","pack","--folder",<dir>,"--zipfile",<dir>/waitgate.zip,"--packagetype","Unmanaged"]
```

### Materialization pollution check

The check that would have caught `pac solution init` scaffolding over the source tree.

```
expected: ['Other/Customizations.xml','Other/Relationships.xml','Other/Solution.xml','unsupported/components.json']
actual  : ['Other/Customizations.xml','Other/Relationships.xml','Other/Solution.xml','unsupported/components.json']
EXTRA   : none
MISSING : none
```

### pac, using the argv WAIT emitted

```
6 PACK    exit=0   "Packed Solution."
7 IMPORT  "Solution Imported successfully."
8 VERIFY  pac solution list:
          waitgate    waitgate    1.0    False
```

## Run 2 — publisher prefix `zzx`, solution `zzxgate`

Run specifically to settle the flagged uncertainty about
`CustomizationOptionValuePrefix`, which is hardcoded to a value copied from a
reference generated for prefix `wait`.

```
prefix=zzx  deployable=True status=deployable_source
PACK exit=0
IMPORT "Solution Imported successfully."
```

**Result: the hardcoded `CustomizationOptionValuePrefix` does not break a
different publisher prefix.** That uncertainty is now evidence, not a guess.

## What this run did NOT prove

- Flows did not import as runnable flows — they remain design-only.
- Custom connectors remain design-only; the emitted shape is not a Power
  Platform custom connector definition.
- No canvas app exists; `.msapp` synthesis is unsupported.
- A `date` column is still omitted-and-reported rather than mapped. The
  Dataverse type for it is unverified and was not guessed.
- A zero exit code from `pac` is not provider confirmation of runtime health.
