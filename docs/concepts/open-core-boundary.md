# Public and Commercial Boundary

WAIT Local Agent is one customer-facing product with a public runtime and
separately governed commercial capabilities.

The currently effective repository license remains Apache 2.0. The exact
pre-transition baseline is preserved on `1.x` and
`archive/apache-2.0-final-2026-08-15`. WAIT is planning a future major-version
dual-licensing model, but no future Community or Commercial terms become
effective merely because they are described in planning documents. See
[`../legal/README.md`](../legal/README.md).

## Public repository scope

This repository may contain:

- local runtime, API, CLI, dashboard, and Docker Compose appliance;
- SQLite store, knowledge index, approval engine, event history, and audit export;
- deliberately selected Community connector implementations;
- workflow schemas and Community workflow templates;
- connector and commercial-pack interfaces;
- useful baseline Change Governance schemas and deterministic capabilities;
- tests, launch documentation, sample data, scripts, and issue templates; and
- license/edition status and attribution surfaces required by an approved future Community license.

Public source does not mean every commercial entitlement, proprietary pack, or
official-service commitment belongs in this repository.

## Private commercial scope

Do not add proprietary implementation internals to this public repository.
That includes:

- MSP Pack implementation beyond public interfaces and deliberately approved Community functionality;
- advanced Change Governance Pro policies, adjudication, historical intelligence, and commercial reports;
- Founder Pack project scanner, evidence vault, Launch Passport bundle implementation, or investor workflow internals;
- private or commercially supported connector profiles that are not intentionally released as Community functionality;
- centralized MSP Control, fleet management, billing, and cross-client policy internals;
- NIS2, European Assurance, OEM, and enterprise pack internals;
- private white-label branding implementation;
- proprietary templates, scripts, or client-specific automations; and
- private signing keys, licensing secrets, or server-side entitlement implementation.

Private pack work belongs in `W-A-I-T/wait-local-agent-packs` or another
approved private repository. Private packs are plug-ins loaded by this runtime;
they must not create a second API server, identity system, tenant model,
approval engine, persistence layer, or audit system.

## Editions and licensing transition

### Current 1.x line

Community is the C$0 Apache-2.0 edition represented by the preserved 1.x line.
Previously granted Apache rights remain in force.

### Planned 2.x line

The intended future model is dual licensing under counsel-approved WAIT
Community and WAIT Commercial terms. Product requirements include:

- a useful public-source Community route with approved attribution and the selected source/copyleft obligations;
- commercial rights for private modifications, managed-service operation, proprietary packs, support, official builds, branding removal, white-labeling, and OEM distribution where explicitly contracted; and
- a clear distinction between Community compliance and paid commercial rights.

Do not claim that every MSP is prohibited from a future Community route if it
fully complies with the final Community terms. Do not imply that a generic
Enterprise subscription automatically grants complete white-label or OEM
rights.

## Local install directory

`packs/` is gitignored. It is reserved for local proprietary pack installs and
must not be committed.

## Dependency policy

- Record every direct, transitive, bundled, and generated dependency or asset.
- Confirm compatibility with the currently effective repository license before merging.
- Before a 2.x transition, confirm compatibility with both the approved Community terms and WAIT's ability to distribute a separate Commercial build/license.
- Do not copy code from another project merely because it is publicly visible.
- Treat AGPL, GPL, source-available, and custom-licensed projects as requiring explicit compatibility review.
- Run a reproducible license inventory, third-party-notice build, and SBOM gate when dependencies change.

The transition checklist is maintained in
[`../legal/TRANSITION_CHECKLIST.md`](../legal/TRANSITION_CHECKLIST.md).

## Runtime boundary

Public-runtime behavior remains safe by default:

- no live writes by default;
- no HTTP probing by default;
- no cloud fallback by default;
- no model inference by default;
- no proprietary pack code by default; and
- all applicable mutations require draft, policy, tenant, role, and approval checks before execution.
