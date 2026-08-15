# Dual-license transition checklist

This checklist is a merge gate for the future WAIT Local Agent 2.0 license change. It does not alter the currently effective Apache-2.0 license.

## Preserved baseline

- [x] Record the final pre-transition commit: `903cb595e8f735fcc306a68f2bee150fce58a416`.
- [x] Create the `1.x` maintenance branch at that commit.
- [x] Create `archive/apache-2.0-final-2026-08-15` at that commit.
- [ ] Create and protect a signed or annotated immutable tag for the same commit.
- [ ] Publish a notice confirming that previously granted Apache-2.0 rights remain unchanged.

## Ownership and provenance

- [ ] Confirm the legal entity that owns the copyright.
- [ ] Inventory all human authors, pull-request authors, co-authors, employees, contractors, and adapted sources.
- [ ] Obtain assignment or sufficient relicensing permission for every material outside contribution.
- [ ] Review AI-assisted/generated changes for provenance and copied expression.
- [ ] Review WAIT-Sync history before migrating any code.
- [ ] Scan history for credentials and confidential information.

## Dependencies and assets

- [ ] Inventory Python, JavaScript, Rust, desktop, container, example, media, font, and generated-artifact licenses.
- [ ] Confirm compatibility with both the planned Community license and the separately executed Commercial license.
- [ ] Generate third-party notices and a reproducible SBOM.

## Legal documents

- [ ] Approve the WAIT Community License with qualified software counsel.
- [ ] Approve the WAIT Commercial License/EULA with qualified software counsel.
- [ ] Approve attribution, trademark, official-build, hosted-service, MSP, OEM, and white-label terms.
- [ ] Approve a CLA, copyright assignment, or equivalent contributor-rights process.
- [ ] Define the exact rights attached to Community, Professional, MSP, Enterprise, and OEM offerings.

## Repository implementation

- [ ] Add approved Community and Commercial license dispatch text.
- [ ] Update `pyproject.toml`, Cargo/desktop metadata, package metadata, badges, About/Legal screens, release artifacts, and documentation consistently.
- [ ] Add approved `Powered by WAIT` attribution behavior.
- [ ] Add entitlement-controlled branding modes: `wait`, `co_branded`, `partner`, and `white_label`.
- [ ] Test attribution, commercial entitlement expiry, offline leases, grace periods, and non-destructive fallback.
- [ ] Update contribution documentation and CI checks.
- [ ] Publish a version-aware migration notice for Apache 1.x and dual-licensed 2.x.

## Release gate

- [ ] All automated tests and release validation pass.
- [ ] License metadata is consistent across every distributed artifact.
- [ ] SBOM, provenance, signatures, checksums, notices, and support-period information are published.
- [ ] Launch Passport issue #651 is synchronized with the final terms.
- [ ] The license-changing PR receives legal, security, release-engineering, and product approval.
