# T1/T2 corrections — verified against the working tree

These are defects in the in-flight XML conversion, each verified against the actual code on
`ai/wla-xml-solution-format`. They would fail on a live tenant.

## 1. `pac solution check` is still in the BUILD stage

`src/wait_local_agent/power_platform.py:315` still emits
`["pac", "solution", "check", "--path", f"{directory}/{name}.zip"]`.

`pac solution check` uploads the zip to the Power Apps Checker **cloud service**. Its own usage text
says `--environment ... When not specified, the active organization selected for the current auth
profile will be used`, and the auth profile on the verification machine has a blank Environment Url.
`execute_power_platform_stage` treats any non-zero exit as stage failure
(`power_platform_deployment.py:462-463`), so BUILD would go pack-OK → check-fail → `status: failed`.
**The first live BUILD would fail on a step that is not part of building.**

Remove it. WAIT already validates the zip structurally in `validate_power_platform_solution_package`,
and the checker's findings are advisory. Record as a behaviour change in `CHANGELOG.md`.

## 2. The primary name attribute is chosen alphabetically

`src/wait_local_agent/power_platform_package.py:627`:

    primary = cast(str, attributes[0]["logical_name"])

`attributes` is sorted by logical name for determinism, so a table with `aa_email` and `zz_name`
gives `aa_email` the `PrimaryName` DisplayMask and `<PrimaryNameAttribute>`. The table's primary
column is semantically wrong, and renaming an unrelated column silently changes the Dataverse schema
and the package digest.

Determinism was achieved at the cost of correctness. Take the primary from declared data; keep
emission order sorted but decouple it from primary selection.

## 3. The canvas-app `unsupported` entry is emitted unconditionally

`src/wait_local_agent/power_platform_package.py:728-737`:

    canvas = artifact.get("canvas_app")
    app_name = artifact.get("app_name", "canvas_app")
    app_id = _component_id(tenant, f"canvas:{app_name}")
    unsupported.append({...})

`canvas` is assigned and never used — the append is unconditional. Every Dataverse-only package
reports a phantom missing canvas app.

## 4. No publisher-prefix enforcement on entity logical names

Nothing checks that `logical_name` starts with `<publisher_prefix>_`. Dataverse requires custom
entity schema names to carry the publisher prefix — the proven reference is `wait_employee` /
`wait_employees` for prefix `wait`. The route accepts arbitrary logical names.

Do **not** silently rewrite the name; that changes the customer's tenant schema behind their back.
Record the entity as design-only naming the expected prefix.
