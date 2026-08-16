# Dual-license transition checklist

The standard **AGPL-3.0-only Community source-license switch for the 2.0 development line is implemented**, and the repository now includes the WAIT `Powered by WAIT` attribution terms under AGPLv3 Section 7. This checklist tracks remaining provenance, commercial-license, contributor-rights, packaging, and release work.

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
- [x] Add [`../../ADDITIONAL_TERMS.md`](../../ADDITIONAL_TERMS.md) with the WAIT Section 7 attribution, origin, and trademark terms.
- [x] Add [`../../NOTICE`](../../NOTICE) and include the legal files in Python package metadata.
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
- [ ] Confirm compatibility with `AGPL-3.0-only` and applicable additional terms for the public 2.0 distribution.
- [ ] Confirm WAIT has sufficient rights for components included in any separately licensed commercial distribution.
- [ ] Generate third-party notices and a reproducible SBOM.

## Commercial legal documents

- [ ] Approve the WAIT Commercial License/EULA with qualified software counsel.
- [ ] Have qualified software counsel review the committed WAIT Section 7 wording before the first production 2.0 release or enforcement reliance.
- [ ] Approve official-build, hosted-service, MSP, OEM, and white-label terms.
- [ ] Approve a CLA, copyright assignment, or equivalent contributor-rights process for material future outside contributions that need dual licensing.
- [ ] Define the exact rights attached to Community, Professional, MSP, Enterprise, and OEM offerings.

## Product implementation

- [x] Add visible `Powered by WAIT` attribution to the Community operator interface.
- [x] Add visible `Powered by WAIT` attribution to the Community end-user support interface.
- [ ] Add entitlement-controlled commercial branding modes: `wait`, `co_branded`, `partner`, and `white_label`.
- [ ] Test commercial entitlement expiry, offline leases, grace periods, and non-destructive fallback.
- [ ] Update contribution automation/CLA checks when the contributor-rights model is approved.
- [ ] Add a complete user-visible AGPL legal/source surface for network-interactive distributions before the first production 2.0 release.

## Release gate

- [ ] All automated tests and release validation pass for the attribution PR.
- [ ] License and version metadata is consistent across every distributed artifact.
- [ ] SBOM, provenance, signatures, checksums, notices, and support-period information are published for the first 2.0 release.
- [ ] Launch Passport issue #651 is synchronized with the effective AGPL Community base, `Powered by WAIT` attribution, and separate commercial branding rights.
- [ ] Qualified counsel reviews the commercial/dual-licensing program before WAIT sells or promises commercial exceptions that depend on relicensing rights.
