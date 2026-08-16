# Dual-license transition checklist

The standard **AGPL-3.0-only Community source-license switch for the 2.0 development line is now implemented**. This checklist tracks the remaining provenance, commercial-license, attribution, contributor-rights, packaging, and release work.

## Preserved Apache baseline

- [x] Record the final pre-transition commit: `903cb595e8f735fcc306a68f2bee150fce58a416`.
- [x] Create the `1.x` maintenance branch at that commit.
- [x] Create `archive/apache-2.0-final-2026-08-15` at that commit.
- [x] Publish [`LICENSE_HISTORY.md`](../../LICENSE_HISTORY.md) confirming that previously granted Apache-2.0 rights remain unchanged.
- [x] Preserve the Apache-2.0 license text in [`LICENSES/Apache-2.0.txt`](../../LICENSES/Apache-2.0.txt).
- [ ] Create and protect a signed or annotated immutable tag for the same commit.

## Community source license

- [x] Replace the 2.0 root source license with standard GNU Affero General Public License v3 only.
- [x] Set Python and Rust package metadata to `AGPL-3.0-only` for the 2.0 development line.
- [x] Move the product/runtime version to the 2.0 development series so Apache `1.1.1` artifacts are not reused under a different license.
- [x] Update the primary README and public/commercial boundary to identify AGPL as the effective 2.0 Community source license.
- [x] State explicitly that no custom WAIT Section 7 terms are currently effective.
- [ ] Complete all remaining stale-version and stale-license metadata/doc cleanup identified by CI/search before release.

## Ownership and provenance

- [ ] Confirm the legal entity that owns the copyright.
- [ ] Inventory all human authors, pull-request authors, co-authors, employees, contractors, and adapted sources.
- [ ] Obtain assignment or sufficient relicensing permission for every material outside contribution that WAIT intends to distribute under separate commercial terms.
- [ ] Review AI-assisted/generated changes for provenance and copied expression.
- [ ] Review WAIT-Sync history before migrating any code.
- [ ] Scan history for credentials and confidential information.

## Dependencies and assets

- [ ] Inventory Python, JavaScript, Rust, desktop, container, example, media, font, and generated-artifact licenses.
- [ ] Confirm compatibility with `AGPL-3.0-only` for the public 2.0 distribution.
- [ ] Confirm WAIT has sufficient rights for components included in any separately licensed commercial distribution.
- [ ] Generate third-party notices and a reproducible SBOM.

## Commercial legal documents

- [ ] Approve the WAIT Commercial License/EULA with qualified software counsel.
- [ ] Approve any future WAIT-specific AGPL Section 7 attribution/trademark terms or additional Community permissions before adding them.
- [ ] Approve official-build, hosted-service, MSP, OEM, and white-label terms.
- [ ] Approve a CLA, copyright assignment, or equivalent contributor-rights process for material future outside contributions that need dual licensing.
- [ ] Define the exact rights attached to Community, Professional, MSP, Enterprise, and OEM offerings.

## Product implementation

- [ ] Add approved `Powered by WAIT` attribution behavior only if/when approved Community terms require it.
- [ ] Add entitlement-controlled commercial branding modes: `wait`, `co_branded`, `partner`, and `white_label`.
- [ ] Test commercial entitlement expiry, offline leases, grace periods, and non-destructive fallback.
- [ ] Update contribution automation/CLA checks when the contributor-rights model is approved.
- [ ] Add a user-visible AGPL source link/legal-notice surface where required for network-interactive distributions.

## Release gate

- [ ] All automated tests and release validation pass for the license-switch PR.
- [ ] License and version metadata is consistent across every distributed artifact.
- [ ] SBOM, provenance, signatures, checksums, notices, and support-period information are published for the first 2.0 release.
- [ ] Launch Passport issue #651 is synchronized with the effective AGPL Community base and the still-separate commercial terms.
- [ ] Qualified counsel reviews the commercial/dual-licensing program before WAIT sells or promises commercial exceptions that depend on relicensing rights.
