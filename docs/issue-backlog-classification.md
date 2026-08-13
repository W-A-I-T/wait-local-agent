# Open Issue Backlog Classification

Audited against the 9 issues returned by the GitHub open-issue query on
2026-08-12. Each issue has one primary roadmap category. Cross-category work is
called out without changing the primary ownership boundary. PR #270's latest
authoritative CI run passed both backend and UI checks; that is evidence for
the integrated PR only, not proof that every release or browser gate is done.

| Issue | Primary category | Status and action | Remaining blocker |
| --- | --- | --- | --- |
| [#261](https://github.com/W-A-I-T/wait-local-agent/issues/261) | D. MSP Operations Vertical | Keep open as the coordination tracker; reframe from NeoAgent parity to MSP Operations Vertical completion and enterprise evidence. The canonical onboarding fixture now exercises eight bounded child roles locally. | Child issues and the final truth audit remain open. |
| [#259](https://github.com/W-A-I-T/wait-local-agent/issues/259) | E. Evaluation / Governance | Keep open; make the enterprise-readiness matrix executable and verify backend, UI, security, and local-first gates. PR #270 requires a fresh green backend and UI CI result after the coverage fix. | Release-script, security-audit, and real-browser evidence remain separate gates. |
| [#258](https://github.com/W-A-I-T/wait-local-agent/issues/258) | E. Evaluation / Governance | Keep open; truth-audit every capability against reachable interfaces, tests, and unsupported boundaries. | Documentation still needs a final current-state pass after integration. |
| [#257](https://github.com/W-A-I-T/wait-local-agent/issues/257) | F. Enterprise Readiness | Keep open; continue the route/control/state matrix, responsive behavior, and recovery pass. The current Firefox slice covers all 20 operator route headings plus consultant validation, guided continuation, and the no-blueprint tenant-entry regression; see [UI and API wiring evidence](ui-feature-evidence.md). | Full control/state coverage, denied/offline/provider-error matrices, and responsive/accessibility evidence remain to be completed. |
| [#256](https://github.com/W-A-I-T/wait-local-agent/issues/256) | D. MSP Operations Vertical | Keep open; add governed PSA and documentation operations; Microsoft and marketplace work remains explicitly cross-referenced to C/H. | Each provider operation still needs a documented contract, scope, approval, audit, and tests. |
| [#255](https://github.com/W-A-I-T/wait-local-agent/issues/255) | D. MSP Operations Vertical | Keep open; scheduled static and tenant-published playbooks now use the existing scheduler and controlled coordinator. | Event-triggered playbook subscriptions, richer mappings, historical/provider ingestion, and several catalog workflows remain partial. |
| [#253](https://github.com/W-A-I-T/wait-local-agent/issues/253) | D. MSP Operations Vertical | Keep open; complete technician notifications, end-user boundaries, and white-label flows through the shared runtime. | External delivery and branding remain opt-in/incomplete. |
| [#252](https://github.com/W-A-I-T/wait-local-agent/issues/252) | D. MSP Operations Vertical | Keep open; deepen governed RMM parity one documented provider capability at a time. | Provider contracts, polling, failure paths, and write approvals remain incomplete. |
| [#38](https://github.com/W-A-I-T/wait-local-agent/issues/38) | F. Enterprise Readiness | Keep open as an external prerequisite; code paths are guarded but certificates/secrets cannot be invented in-repository. | Apple Developer and Windows signing credentials. |

No issue was demonstrably completed, duplicated, or obsolete in this audit, so
none was closed. The former master tracker is intentionally retained as a
coordination issue under the MSP Operations category rather than defining the
whole product.
