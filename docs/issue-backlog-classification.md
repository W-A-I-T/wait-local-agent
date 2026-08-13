# Open Issue Backlog Classification

Audited against the 9 issues returned by the GitHub open-issue query on
2026-08-13. Each issue has one primary roadmap category. Cross-category work is
called out without changing the primary ownership boundary. Green integrated PRs
or local release runs are evidence for those slices only, not proof that every
release or browser gate is done.

| Issue | Primary category | Status and action | Remaining blocker |
| --- | --- | --- | --- |
| [#261](https://github.com/W-A-I-T/wait-local-agent/issues/261) | D. MSP Operations Vertical | Keep open as the coordination tracker; reframe from NeoAgent parity to MSP Operations Vertical completion and enterprise evidence. The canonical onboarding fixture now exercises eight bounded child roles locally. | Child issues and the final truth audit remain open. |
| [#259](https://github.com/W-A-I-T/wait-local-agent/issues/259) | E. Evaluation / Governance | Keep open; the enterprise matrix now records opt-in, read-only environment health evidence in addition to the backend/UI/security gates. PR #289 adds bounded controlled-evaluation security evidence; each integration PR still requires fresh green backend and UI CI. | Release-script, security-audit, and real-browser evidence remain separate gates; live customer authorization remains external evidence. |
| [#258](https://github.com/W-A-I-T/wait-local-agent/issues/258) | E. Evaluation / Governance | Keep open; truth-audit every capability against reachable interfaces, tests, and unsupported boundaries. | Documentation still needs a final current-state pass after integration. |
| [#257](https://github.com/W-A-I-T/wait-local-agent/issues/257) | F. Enterprise Readiness | Keep open; the executable Playwright CLI matrix now checks all 21 operator/direct-link routes, named controls, desktop/mobile overflow, keyboard focus, controlled provider failure, controlled offline transport, and token-enforced permission state; continue the per-control action and recovery pass. See [browser validation](ui-browser-validation.md). | Full per-control success, cancellation, recovery, and live-provider behavior remain to be completed. |
| [#256](https://github.com/W-A-I-T/wait-local-agent/issues/256) | D. MSP Operations Vertical | Keep open; add governed PSA and documentation operations; Microsoft and marketplace work remains explicitly cross-referenced to C/H. | Each provider operation still needs a documented contract, scope, approval, audit, and tests. |
| [#255](https://github.com/W-A-I-T/wait-local-agent/issues/255) | D. MSP Operations Vertical | Keep open; scheduled static and tenant-published playbooks plus tenant-scoped event subscriptions now use the existing scheduler/event dispatcher and controlled coordinator. | Provider-backed input mappings, historical/provider ingestion, and several catalog workflows remain partial. |
| [#253](https://github.com/W-A-I-T/wait-local-agent/issues/253) | D. MSP Operations Vertical | Keep open; complete technician notifications, end-user boundaries, and white-label flows through the shared runtime. | External delivery and branding remain opt-in/incomplete. |
| [#252](https://github.com/W-A-I-T/wait-local-agent/issues/252) | D. MSP Operations Vertical | Keep open; deepen governed RMM parity one documented provider capability at a time. | Provider contracts, polling, failure paths, and write approvals remain incomplete. |
| [#38](https://github.com/W-A-I-T/wait-local-agent/issues/38) | F. Enterprise Readiness | Keep open as an external prerequisite; code paths are guarded but certificates/secrets cannot be invented in-repository. | Apple Developer and Windows signing credentials. |

No issue was demonstrably completed, duplicated, or obsolete in this audit, so
none was closed. The former master tracker is intentionally retained as a
coordination issue under the MSP Operations category rather than defining the
whole product.
