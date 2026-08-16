# Public and Commercial Boundary

WAIT Local Agent is one customer-facing product with a public runtime and
separately governed commercial capabilities.

The `main` branch is the **2.0 development line** and is distributed as a
combined work under **GNU Affero General Public License v3 only
(`AGPL-3.0-only`)**. The exact pre-transition Apache-2.0 baseline remains
preserved on `1.x` and `archive/apache-2.0-final-2026-08-15`. Previously
granted Apache rights remain in force. See [`../../LICENSE_HISTORY.md`](../../LICENSE_HISTORY.md)
and [`../legal/README.md`](../legal/README.md).

## Public repository scope

This repository may contain:

- local runtime, API, CLI, dashboard, and Docker Compose appliance;
- SQLite store, knowledge index, approval engine, event history, and audit export;
- deliberately selected Community connector implementations;
- workflow schemas and Community workflow templates;
- connector and commercial-pack interfaces;
- useful baseline Change Governance schemas and deterministic capabilities;
- tests, launch documentation, sample data, scripts, and issue templates; and
- license/edition status and legal-notice surfaces required by the Community license.

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

## Editions and licensing

### Preserved 1.x line

The preserved 1.x baseline remains available under Apache License 2.0.
Previously granted Apache rights remain in force.

### 2.0 Community line

The public `main` development line is now `AGPL-3.0-only`. Community remains a
real self-hosted route and commercial use is permitted when the AGPL terms are
followed. In particular, operators of modified network-accessible versions
must satisfy the AGPL's source-availability requirements.

The repository currently imposes **no custom WAIT Section 7 terms** beyond the
standard AGPL text. A specific `Powered by WAIT` attribution rule, additional
internal-use permission, or other WAIT-specific Community term is not effective
unless it is later approved and deliberately added.

### Commercial route

WAIT may separately offer written commercial licenses and proprietary packs for
customers that need contractual rights or services beyond the AGPL route,
including private modifications, managed-service terms, official builds,
support, branding arrangements, white-labeling, OEM distribution, centralized
MSP functionality, or proprietary Change Governance/assurance capabilities.

A commercial license is a separate agreement. Do not claim that every MSP is
prohibited from using Community when it fully complies with AGPL, and do not
imply that a generic Enterprise purchase automatically grants complete
white-label or OEM rights.

## Local install directory

`packs/` is gitignored. It is reserved for local proprietary pack installs and
must not be committed.

## Dependency policy

- Record every direct, transitive, bundled, and generated dependency or asset.
- Confirm compatibility with `AGPL-3.0-only` before merging into the 2.0 public line.
- Confirm WAIT has sufficient rights before including a component in a separately licensed commercial distribution.
- Preserve applicable notices for code inherited from the Apache-2.0 baseline and other third-party material.
- Do not copy code from another project merely because it is publicly visible.
- Treat GPL, AGPL, source-available, and custom-licensed projects as requiring explicit compatibility review.
- Run a reproducible license inventory, third-party-notice build, and SBOM gate when dependencies change.

The remaining commercial-transition checklist is maintained in
[`../legal/TRANSITION_CHECKLIST.md`](../legal/TRANSITION_CHECKLIST.md).

## Runtime boundary

Public-runtime behavior remains safe by default:

- no live writes by default;
- no HTTP probing by default;
- no cloud fallback by default;
- no model inference by default;
- no proprietary pack code by default; and
- all applicable mutations require draft, policy, tenant, role, and approval checks before execution.
