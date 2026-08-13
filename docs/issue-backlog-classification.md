# Open Issue Backlog Classification

Audited against the 11 issues returned by the GitHub open-issue query on
2026-08-12. Each issue has one primary roadmap category. Cross-category work is
called out without changing the primary ownership boundary. Hosted CI status is
reported against the current PR head when reviewed; it is evidence for the
integrated PR only, not proof that every release or browser gate is done.

| Issue | Primary category | Status and action | Remaining blocker |
| --- | --- | --- | --- |
| [#261](https://github.com/W-A-I-T/wait-local-agent/issues/261) | D. MSP Operations Vertical | Keep open as the coordination tracker; reframe from NeoAgent parity to MSP Operations Vertical completion and enterprise evidence. The canonical onboarding fixture now exercises eight bounded child roles locally. | Child issues and the final truth audit remain open. |
| [#260](https://github.com/W-A-I-T/wait-local-agent/issues/260) | A. Core Platform | Keep open; complete deterministic/local/optional-remote provider conformance and failure-path evidence. | Provider fixtures and offline/remote boundary validation. |
| [#259](https://github.com/W-A-I-T/wait-local-agent/issues/259) | E. Evaluation / Governance | Keep open; make the enterprise-readiness matrix executable and verify backend, UI, security, and local-first gates. PR #270 backend and UI CI are passing. | Release-script, security-audit, and real-browser evidence remain separate gates. |
| [#258](https://github.com/W-A-I-T/wait-local-agent/issues/258) | E. Evaluation / Governance | Keep open; truth-audit every capability against reachable interfaces, tests, and unsupported boundaries. | Documentation still needs a final current-state pass after integration. |
| [#257](https://github.com/W-A-I-T/wait-local-agent/issues/257) | F. Enterprise Readiness | Keep open; continue the route/control/state matrix, responsive behavior, and recovery pass. A current Chromium slice covers `/consultant` success, validation, server-error recovery, and review-only boundaries; see [UI and API wiring evidence](ui-feature-evidence.md). | Full route/control coverage, denied/offline/provider-error matrices, and responsive/accessibility evidence remain to be completed. |
| [#256](https://github.com/W-A-I-T/wait-local-agent/issues/256) | D. MSP Operations Vertical | Keep open; add governed PSA and documentation operations; Microsoft and marketplace work remains explicitly cross-referenced to C/H. | Each provider operation still needs a documented contract, scope, approval, audit, and tests. |
| [#255](https://github.com/W-A-I-T/wait-local-agent/issues/255) | D. MSP Operations Vertical | Keep open; bounded composition now covers versioned local review/report playbooks, preview, stop-at-approval execution, audit, and a tenant-scoped publish/edit/disable/restore/compare slice; continue the full evidence-backed playbook and scheduled/event pass. | Richer step mappings, historical/provider ingestion, and several provider-backed operations remain partial. |
| [#254](https://github.com/W-A-I-T/wait-local-agent/issues/254) | A. Core Platform | Keep open pending the final integrated acceptance audit; the existing executor now has bounded result-aware continuation, explicit retry/fallback/human-input/technician-escalation/blocked paths, cancellation, retry lineage, API/CLI/Agents UI state, audit/execution evidence, and focused tests. | Full-branch CI and the final cross-surface evidence review remain; broader human-task fulfillment and live-provider rollback remain outside this slice. |
| [#253](https://github.com/W-A-I-T/wait-local-agent/issues/253) | D. MSP Operations Vertical | Keep open; complete technician notifications, end-user boundaries, and white-label flows through the shared runtime. | External delivery and branding remain opt-in/incomplete. |
| [#252](https://github.com/W-A-I-T/wait-local-agent/issues/252) | D. MSP Operations Vertical | Keep open; deepen governed RMM parity one documented provider capability at a time. | Provider contracts, polling, failure paths, and write approvals remain incomplete. |
| [#38](https://github.com/W-A-I-T/wait-local-agent/issues/38) | F. Enterprise Readiness | Keep open as an external prerequisite; code paths are guarded but certificates/secrets cannot be invented in-repository. | Apple Developer and Windows signing credentials. |

No issue was demonstrably completed, duplicated, or obsolete in this audit, so
none was closed. The former master tracker is intentionally retained as a
coordination issue under the MSP Operations category rather than defining the
whole product.
