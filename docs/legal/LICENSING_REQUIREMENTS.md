# Licensing requirements for WAIT Local Agent 2.0

The base Community source license for the `2.0` development line is **GNU Affero General Public License v3 only (`AGPL-3.0-only`)**. The standard AGPL text is in the root [`LICENSE`](../../LICENSE).

WAIT also applies the additional terms in [`../../ADDITIONAL_TERMS.md`](../../ADDITIONAL_TERMS.md) under AGPLv3 Section 7 to copyrightable material for which the applicable copyright holder has sufficient authority to impose those terms.

## Community route — effective

Community is public-source, useful, self-hosted, and local-first under `AGPL-3.0-only` plus the applicable WAIT Section 7 terms.

The current repository therefore:

- permits use, modification, and commercial operation subject to AGPL-3.0-only and applicable Section 7 terms;
- requires compliance with the AGPL's corresponding-source obligations, including Section 13 for modified network-accessible versions;
- preserves applicable copyright and license notices;
- requires a reasonable visible `Powered by WAIT` attribution in interactive user interfaces containing WAIT-copyrighted material covered by the additional terms;
- prohibits origin misrepresentation for material covered by the additional terms;
- does not grant general WAIT trademark rights beyond the limited use needed for the required attribution and ordinary nominative reference;
- does not grant proprietary WAIT packs, official support, LTS, white-label rights, OEM distribution rights, or other commercial services merely through the Community license; and
- preserves the prior Apache-2.0 grants for the frozen 1.x baseline.

A commercial operator may use the Community route when it fully complies with AGPL-3.0-only and the applicable WAIT additional terms. The product must not claim that every MSP is automatically prohibited from Community.

## Powered by WAIT attribution

The required Community attribution is:

> **Powered by WAIT**

It must remain reasonably visible and legible during ordinary use in a persistent footer, About/Legal screen, settings/legal surface, or another comparably prominent and readily accessible product-attribution location.

Accessibility, responsive-layout, localization, and ordinary styling changes are allowed if the words remain visible and legible. Community users may not intentionally remove, conceal, or replace the attribution in a way that misrepresents the origin of WAIT-copyrighted material covered by the term.

The public operator and end-user interfaces implement this notice directly.

## Commercial route

A separately executed Commercial license may grant, according to the purchased entitlement:

- private modifications and private plugins;
- an exception from applicable Community source-publication obligations for the licensed deployment, to the extent WAIT has sufficient rights to grant that exception;
- operation for third-party managed customers under negotiated commercial terms;
- proprietary WAIT packs;
- centralized MSP/fleet functionality;
- official signed and LTS builds;
- premium updates, support, SLA, warranty, or indemnity where contracted;
- advanced Change Governance and assurance capabilities;
- enterprise identity, retention, high-availability, and integration features;
- removal or replacement of the Community `Powered by WAIT` attribution when expressly licensed;
- partner/co-branding;
- white-label rights; and
- OEM redistribution rights.

Generic Enterprise purchase must not silently grant attribution removal, complete white-label, or OEM rights. Those rights require explicit contract language and entitlements.

## Branding entitlements

The commercial implementation should support explicit states rather than a single ambiguous flag:

```text
wait
co_branded
partner
white_label
```

The Community default is `wait`, which preserves the required attribution. `co_branded`, `partner`, and `white_label` are commercial branding states and must not be enabled solely by changing a local Community preference; they require the applicable commercial rights.

## Version transition

```text
WAIT Local Agent 1.x
Apache-2.0 baseline preserved; previously granted rights remain in force

WAIT Local Agent 2.0 development line
AGPL-3.0-only + applicable WAIT Section 7 additional terms

WAIT Commercial License
Separate written agreement; commercial exception/rights remain subject to counsel and provenance review
```

See [`../../LICENSE_HISTORY.md`](../../LICENSE_HISTORY.md) for the exact source-license boundary.
