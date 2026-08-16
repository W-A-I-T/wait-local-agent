# Licensing requirements for WAIT Local Agent 2.0

The base Community source license for the `2.0` development line is now **GNU Affero General Public License v3 only (`AGPL-3.0-only`)**. The standard AGPL text in the root [`LICENSE`](../../LICENSE) is effective for the public `main` line.

This document records additional product and commercial requirements that are **not automatically part of the AGPL license**. Qualified software counsel must approve any future WAIT-specific Section 7 terms, additional permissions, commercial EULA, attribution rules, trademark policy, white-label rights, or OEM terms before they are represented as legally effective.

## Community route — effective base

Community is public-source, useful, self-hosted, and local-first under `AGPL-3.0-only`.

The current repository therefore:

- permits use, modification, and commercial operation subject to AGPL-3.0-only;
- requires compliance with the AGPL's corresponding-source obligations, including Section 13 for modified network-accessible versions;
- preserves applicable copyright and license notices;
- does not grant proprietary WAIT packs, official support, LTS, white-label rights, OEM distribution rights, or other commercial services merely through the Community license; and
- does not currently impose a custom `Powered by WAIT` attribution requirement beyond the standard AGPL text.

A commercial operator may use the Community route when it fully complies with AGPL-3.0-only. The product must not claim that every MSP is automatically prohibited from Community.

## Future Community additions under review

Product strategy may later add counsel-approved AGPL Section 7 terms or additional permissions concerning matters such as:

- preservation of a reasonable `Powered by WAIT` legal notice or attribution;
- trademark and origin/misrepresentation protections;
- an additional permission for an organization using WAIT for its own internal operations; and
- documented source/notice presentation in interactive interfaces.

These items remain **requirements under review**, not effective license conditions, until approved text is deliberately committed.

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
- branding removal or partner/co-branding;
- white-label rights; and
- OEM redistribution rights.

Generic Enterprise purchase must not silently grant complete white-label or OEM rights. Those rights require explicit contract language and entitlements.

## Branding entitlements

The future commercial implementation should support explicit states rather than a single ambiguous flag:

```text
wait
co_branded
partner
white_label
```

Because no custom WAIT attribution term is currently in force under Community, these states must not be described as overriding a Community `Powered by WAIT` condition until such a condition is legally approved and added. Commercial branding rights can still govern WAIT-owned proprietary packs, official builds, trademarks, support assets, and separately licensed distributions.

## Version transition

```text
WAIT Local Agent 1.x
Apache-2.0 baseline preserved; previously granted rights remain in force

WAIT Local Agent 2.0 development line
AGPL-3.0-only Community source license is effective

WAIT Commercial License
Separate written agreement; commercial exception/rights remain subject to counsel and provenance review
```

See [`../../LICENSE_HISTORY.md`](../../LICENSE_HISTORY.md) for the exact source-license boundary.
