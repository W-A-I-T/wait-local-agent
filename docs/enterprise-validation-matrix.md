# Enterprise validation matrix

This matrix is the repository-level evidence index for the local-first safety
and release-readiness gate. It records where a requirement is exercised and
what the evidence does—and does not—prove. The GitHub Actions `test` workflow
is authoritative for the final integration commit; a local focused test run or
a fixture is not a substitute for that gate.

| Requirement | Runtime surface | Evidence | Current boundary / remaining risk |
| --- | --- | --- | --- |
| Backend quality and coverage | `.github/workflows/test.yml`, `scripts/validate_release.sh` | `ruff check .`, `mypy src tests`, `bandit -r src`, `pip-audit --skip-editable`, and `pytest --cov=wait_local_agent --cov-fail-under=95` | Requires a green CI run on the final PR commit; this matrix does not claim a local full-suite result when the local environment cannot complete it. |
| Public API/CLI contract | `scripts/public_surface_audit.py`, FastAPI routes, Typer commands | `tests/test_public_surface_audit.py`, API/CLI-focused tests, and the workflow public-surface step | A passing surface audit does not prove every provider is configured or reachable. |
| Tenant isolation and RBAC | API dependencies, connector routes, AgentService, MCP | `tests/test_rbac.py`, `tests/test_runtime_scope.py`, connector-specific cross-tenant tests, `tests/test_agents.py`, `tests/test_mcp.py`, and consultant route scope tests | Provider authorization is never inferred from an empty result; live tenant verification still requires customer credentials. |
| Approval-before-write | Smart-action catalog, agent approvals, connector mutation routes | `tests/test_smart_actions.py`, `tests/test_agents.py`, connector mutation tests, and consultant deployment/promotion tests | Draft, artifact, and approval evidence do not mean a provider write or production deployment occurred. |
| Redaction and input safety | Shared renderers, vault, API validators, connector boundaries | `tests/test_security_vault.py`, `tests/test_reports.py`, connector validation/failure tests, and agent secret-redaction assertions | Redaction is bounded output protection; it is not proof that an external provider will never log a secret outside WAIT. |
| Prompt/tool injection and unknown operations | Evaluation contract, Work IQ policy, MCP policy, tool catalog | `tests/test_evaluation.py`, `tests/test_workiq.py`, `tests/test_mcp.py`, and tool-selection tests | Controlled evaluation derives tenant/required-role (`rbac`) and disabled-write/no-successful-write (`unexpected_writes`) evidence, plus bounded lifecycle evidence from persisted runtime status/history/exception lineage. Results label security evidence as `runtime`, explicit fixture `observation`, or `unsupported`; provenance does not override a false value. Injection, secret-leakage, and rollback dimensions still fail closed without dedicated evidence. No broad mutation is enabled merely because a provider has an unverified API. |
| Offline/local-first behavior | Settings offline mode, deterministic provider fallback, connector guards, provider health CLI/API/UI | [`docs/provider-conformance-matrix.md`](provider-conformance-matrix.md), `tests/test_providers.py`, `tests/test_cloud_adapters.py`, `tests/test_mcp_client.py`, `tests/test_cli.py`, and `tests/conftest.py` default settings | Optional remote providers and external connectors remain unavailable without explicit configuration and credentials; health probes report scope and state without exposing secrets. |
| Failure, timeout, retry, cancellation, and partial execution | AgentService, supervisor, event delivery, connector adapters | `tests/test_agents.py`, `tests/test_cli.py`, `tests/test_supervisor.py`, `tests/test_event_dispatch.py`, provider failure tests, and evaluation security-dimension tests; API, CLI, Agents UI, run detail, and controlled evaluation include deterministic exception/recovery, retry-parent, configured fallback, human-input, technician-escalation, blocked, lifecycle, and partial-history evidence | Evaluation evidence is runtime/fixture evidence; it does not claim live-provider rollback unless that evidence is explicitly captured. Step retries and fallbacks remain bounded by the reviewed definition and never select an unconfigured tool. |
| Blueprint-to-delivery safety | Discovery, environment, architecture, governance, delivery, Power Platform stages | `tests/test_discovery.py`, `tests/test_environment.py`, `tests/test_consultant.py`, `tests/test_delivery_plan.py`, `tests/test_power_platform_deployment.py`, and `tests/test_employee_onboarding_demo.py` | The canonical onboarding walkthrough is `local_fixture`; it now generates and validates bounded review-only Power Apps, Power Automate, and Copilot Studio manifests and a redacted digest-bound review package. Live provider execution, deployable packaging, and deployment remain explicit boundaries. |
| UI route/control/state quality | React dashboard and API proxy | `ui/tests/`, `ui/package.json`, `docs/ui-feature-evidence.md`, `docs/ui-browser-validation.md`, and the workflow UI test/build steps | Real-browser evidence now covers all route headings, a mobile responsive replay, offline/denied states, viewer write-control gating, and review-only artifact generation; the full every-control, keyboard, provider-error, and responsive matrix remains open under issue #257. |
| Release and operational readiness | Desktop workflow, updater, backup/restore, release validation | `.github/workflows/release-desktop.yml`, `docs/desktop-install.md`, `src/wait_local_agent/backup.py`, `tests/test_backup.py`, `docs/launch-checklist.md`, and `scripts/validate_release.sh` | External macOS/Windows signing certificates and production credentials are not present in the repository; issue #38 remains the signing blocker. |

## Evidence interpretation

- `configured`, `authenticated`, `authorized`, `reachable`, `permission-limited`,
  `unavailable`, `not_configured`, and `unknown` are distinct environment
  states. An authorization or provider failure is not an empty environment.
- A local fixture proves bounded composition, persistence, redaction, and audit
  behavior only. It does not prove Microsoft, PSA, RMM, documentation, or
  Teams provider success.
- `PLAN`, `GENERATE`, `VALIDATE`, `PACKAGE`, `DEPLOY`, `DEV`, `TEST`, and `PROD`
  are separate boundaries. Artifact digests and approval records are evidence
  for gates, not evidence that a deployment started.
- A requirement is not release-ready until the linked behavior-focused tests,
  repository checks, and—where required—real-browser or live-provider evidence
  all exist. Missing evidence remains a risk rather than an inferred pass.

## Known open gates

1. Issue [#257](https://github.com/W-A-I-T/wait-local-agent/issues/257): full
   real-browser control/state, responsive, permission, offline, and recovery
   matrix.
2. Issue [#259](https://github.com/W-A-I-T/wait-local-agent/issues/259): final
   green CI on the integrated PR plus release-script and security evidence.
3. Issue [#258](https://github.com/W-A-I-T/wait-local-agent/issues/258): final
   capability-to-evidence truth audit across all provider and user-facing docs.
4. Issue [#38](https://github.com/W-A-I-T/wait-local-agent/issues/38): external
   desktop signing certificates and release credentials.
