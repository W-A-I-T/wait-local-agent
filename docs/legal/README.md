# Licensing and commercial transition

WAIT Local Agent now has a versioned source-license boundary and an active Community attribution term.

## Effective source licenses

- The preserved `1.x` baseline through commit `903cb595e8f735fcc306a68f2bee150fce58a416` remains available under **Apache License 2.0**.
- The `2.0` development line on `main` is distributed as a combined work under **GNU Affero General Public License v3 only (`AGPL-3.0-only`)**, together with the applicable WAIT additional terms permitted by AGPLv3 Section 7.

Previously granted Apache rights are not revoked. See [`../../LICENSE_HISTORY.md`](../../LICENSE_HISTORY.md) for the exact transition record, [`../../LICENSE`](../../LICENSE) for the standard AGPL text, and [`../../ADDITIONAL_TERMS.md`](../../ADDITIONAL_TERMS.md) for the WAIT Section 7 terms.

## Effective WAIT attribution term

For WAIT-copyrighted material to which the additional terms apply, interactive user interfaces must preserve a reasonable visible attribution:

> **Powered by WAIT**

The term is designed as a specified legal/author attribution under AGPLv3 Section 7(b), together with origin/misrepresentation and trademark boundaries under Sections 7(c) and 7(e). The exact operative text is [`../../ADDITIONAL_TERMS.md`](../../ADDITIONAL_TERMS.md); this summary does not replace it.

Community UI implementations render the attribution in both the operator shell and the end-user support surface. A separate written commercial branding agreement may expressly permit attribution removal, replacement, co-branding, partner branding, white-labeling, or OEM branding.

## Commercial licensing

WAIT may separately offer commercial licenses for customers that need contractual rights or services beyond the AGPL Community route, including private modifications, proprietary packs, managed-service terms, official builds, support, branding arrangements, white-labeling, and OEM rights.

No commercial exception is granted merely by this documentation. Commercial rights require a separate written agreement and applicable entitlement.

## Remaining transition work

The source-license and attribution-term changes do not complete the broader dual-licensing program. WAIT still needs to complete:

- contributor and copyright provenance review;
- dependency and bundled-asset license inventory;
- WAIT-Sync provenance and secret-history review before migration;
- a counsel-reviewed Commercial License/EULA;
- a contributor-rights mechanism for future dual licensing;
- final trademark, official-build, white-label, and OEM terms;
- a reproducible SBOM and third-party notices; and
- synchronized Launch Passport commercial/provisioning copy.

Qualified software counsel should review the Section 7 wording before the first production 2.0 release or before WAIT relies on the attribution term in a dispute.

Issue #310 remains the product and licensing source of truth. The checklist in this directory tracks the remaining commercial and release work.
