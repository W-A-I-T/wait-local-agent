# Live-verified Dataverse attribute mappings

Each entry was sent to a real environment, imported, and then **cloned back** to confirm the
column exists rather than trusting a zero exit code. Microsoft documents silent omission, so a
successful import alone is not evidence.

Environment: WAIT-Dev / waitdev.crm.dynamics.com · pac 2.4.1 · 2026-09-02

## String -> nvarchar  (verified earlier)

    <Type>nvarchar</Type>
    <MaxLength>100</MaxLength><Length>100</Length>
    <Format>text</Format>
    DisplayMask must include PrimaryName for the primary name column

Learned from the import error: "New string attributes must have a max length value."

## DateOnly / date -> datetime  (verified 2026-09-02)

Sent:

    <Type>datetime</Type>
    <Format>date</Format>
    <Behavior>1</Behavior>
    <RequiredLevel>none</RequiredLevel>
    <DisplayMask>ValidForAdvancedFind|ValidForForm|ValidForGrid</DisplayMask>

Cloned back from the tenant, the column exists on wait_employee with:

    Type: datetime
    Format: date
    Behavior: 1
    RequiredLevel: none

So the mapping round-trips unchanged. `Behavior: 1` is DateOnly.

## Still unmapped - do not guess

Numeric types, choice/optionset, boolean, lookup. Each needs its own live round-trip before it is
added to the emitter. Until then the emitter omits the column and reports it, which is correct.

## Incidental finding: the real export layout differs from what WAIT emits

`pac solution clone` returns entities as `src/Entities/<logical>/Entity.xml`, not inline inside
`Other/Customizations.xml`. WAIT's inline form imports successfully, so both are accepted on the
way in; the split layout is what Dataverse normalises to on the way out. No change required, but
worth knowing before anyone compares an export against WAIT's output and assumes a defect.
