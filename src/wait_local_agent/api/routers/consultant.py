"""Solutions Architect API routes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request, Response

from wait_local_agent.api.context import AdminAccess, ApiContext, TechnicianAccess, ViewerAccess
from wait_local_agent.api.schemas import (
    CopilotStudioPlanRequest,
    DeliveryPlanRequest,
    DiscoveryBlueprintPromotionRequest,
    DiscoveryRequest,
    DiscoverySessionStartRequest,
    DiscoveryTurnRequest,
    EmployeeOnboardingDemoRequest,
    EnvironmentDiscoveryRequest,
    EvaluationRequest,
    GovernanceRequest,
    OpenApiConnectorRequest,
    PowerAppsPlanRequest,
    PowerAutomatePlanRequest,
    PowerPlatformDeploymentRequest,
    PowerPlatformPackageMaterializationRequest,
    PowerPlatformPackageRequest,
    PowerPlatformPackageValidationRequest,
    PowerPlatformRollbackRequest,
    SolutionBlueprintRequest,
    SupervisorPlanRequest,
    SupervisorRunRequest,
)
from wait_local_agent.api.scopes import _approval_scope_visible, _resolve_detail_scope
from wait_local_agent.api.views import (
    _TERMINAL_EXECUTION_STATUSES,
    _power_platform_source_record,
    _safe_json_object,
)
from wait_local_agent.client_scope import resolve_client_scope
from wait_local_agent.connectors import list_connector_statuses, probe_connector_health
from wait_local_agent.consultant import (
    BlueprintValidationError,
    architect_solution_blueprint,
    blueprint_payload,
    blueprint_view,
    generate_playbook_from_blueprint,
    parse_solution_blueprint,
    promote_discovery_candidate,
)
from wait_local_agent.consultant_use_cases import UseCaseCatalogError, list_consultant_use_cases
from wait_local_agent.copilot_studio import CopilotStudioPlanError, build_copilot_studio_plan
from wait_local_agent.delivery_plan import DeliveryPlanError, build_consultant_delivery_plan
from wait_local_agent.discovery import (
    DiscoveryValidationError,
    build_solution_discovery,
    discover_solution_environment,
)
from wait_local_agent.employee_onboarding_demo import (
    EmployeeOnboardingDemoError,
    run_employee_onboarding_demo,
)
from wait_local_agent.evaluation import (
    AgentServiceEvaluationExecutor,
    EvaluationValidationError,
    evaluate_tool_contract,
    execute_tool_contract,
)
from wait_local_agent.governance import GovernanceValidationError, evaluate_solution_governance
from wait_local_agent.models import ConsultantDiscoverySession
from wait_local_agent.monitoring import build_agent_health_summary
from wait_local_agent.msp_playbooks import msp_playbook_entry_view
from wait_local_agent.power_apps import PowerAppsPlanError, build_power_apps_artifact, build_power_apps_plan
from wait_local_agent.power_automate import PowerAutomatePlanError, build_power_automate_flow_plan
from wait_local_agent.power_platform import (
    OpenApiDefinitionError,
    compare_pac_versions,
    generate_power_platform_connector,
    power_platform_cli_status,
)
from wait_local_agent.power_platform_deployment import (
    PowerPlatformDeploymentError,
    build_power_platform_deployment_plan,
    build_power_platform_deployment_plan_from_payload,
    execute_power_platform_rollback,
    execute_power_platform_stage,
    validate_power_platform_solution_package,
    validate_promotion_evidence,
    validate_promotion_source,
    validate_rollback_evidence,
)
from wait_local_agent.power_platform_package import (
    PAC_XML_MINIMUM_VERSION,
    PowerPlatformPackageError,
    build_power_platform_package,
    materialize_power_platform_package,
    package_validation_result,
)
from wait_local_agent.rbac import Role
from wait_local_agent.supervisor import (
    SupervisorPlanError,
    build_supervisor_delegation_plan,
    execute_supervisor_delegation,
)
from wait_local_agent.workflows import list_workflow_templates


def create_consultant_router(ctx: ApiContext) -> APIRouter:
    router = APIRouter()
    active_settings = ctx.active_settings
    store = ctx.store
    limiter = ctx.limiter
    agent_service = ctx.agent_service
    halopsa_client = ctx.halopsa_client
    hudu_client = ctx.hudu_client
    connectwise_client = ctx.connectwise_client
    syncro_client = ctx.syncro_client
    servicenow_client = ctx.servicenow_client
    autotask_client = ctx.autotask_client
    itglue_client = ctx.itglue_client
    confluence_client = ctx.confluence_client
    notion_client = ctx.notion_client
    sharepoint_client = ctx.sharepoint_client
    timezest_client = ctx.timezest_client
    scalepad_client = ctx.scalepad_client
    m365_client = ctx.m365_client
    _approval_view = ctx.approval_view
    _connector_read_client = ctx.connector_read_client

    @router.post("/consultant/blueprints", status_code=201)
    def create_consultant_blueprint(
        payload: SolutionBlueprintRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        client_id = resolve_client_scope(context, payload.client_id).client_id
        if client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            blueprint = parse_solution_blueprint(
                payload.model_dump(exclude={"client_id"}),
                client_id=client_id,
                created_by=context.approver_id or "api",
            )
            return blueprint_view(store.create_solution_blueprint(blueprint))
        except BlueprintValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/demos/employee-onboarding")
    def run_consultant_employee_onboarding_demo(
        payload: EmployeeOnboardingDemoRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        if not active_settings.demo_mode or active_settings.allow_write_actions:
            raise HTTPException(
                status_code=409,
                detail="employee-onboarding fixture requires local demo mode with writes disabled",
            )
        try:
            scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        except HTTPException as exc:
            if exc.detail == "authenticated principal has no tenant":
                raise HTTPException(
                    status_code=403,
                    detail="employee-onboarding demo requires a tenant scope",
                ) from exc
            raise
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="employee-onboarding demo requires a tenant scope")
        if (payload.blueprint_id is None) == (payload.blueprint is None):
            raise HTTPException(status_code=422, detail="provide exactly one of blueprint_id or blueprint")
        try:
            if payload.blueprint_id is not None:
                persisted = store.get_solution_blueprint(payload.blueprint_id, client_id=scoped_client_id)
                if persisted is None:
                    raise HTTPException(status_code=404, detail="solution blueprint not found in tenant scope")
                blueprint: dict[str, object] = blueprint_payload(persisted)
            else:
                blueprint = cast(dict[str, object], payload.blueprint)
            return run_employee_onboarding_demo(
                store=store,
                settings=active_settings,
                blueprint_payload=blueprint,
                client_id=scoped_client_id,
                entity_id=payload.entity_id,
                blueprint_id=payload.blueprint_id,
                persist_blueprint=payload.blueprint_id is None,
                output_directory=payload.output_directory,
            )
        except EmployeeOnboardingDemoError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/consultant/blueprints")
    def consultant_blueprints(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None and context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        return [blueprint_view(blueprint) for blueprint in store.list_solution_blueprints(client_id=scoped_client_id)]

    @router.get("/consultant/blueprints/{blueprint_id}/architecture")
    def consultant_blueprint_architecture(
        blueprint_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None and context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped_client_id)
        if blueprint is None:
            raise HTTPException(status_code=404, detail="solution blueprint not found")
        return architect_solution_blueprint(
            blueprint,
            available_tool_ids=(tool.id for tool in agent_service.list_tools()),
            workflow_templates=list_workflow_templates(),
        )

    @router.post("/consultant/blueprints/{blueprint_id}/generate-playbook")
    def generate_consultant_blueprint_playbook(
        blueprint_id: str,
        context: AdminAccess,
        response: Response,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped = resolve_client_scope(context, client_id).client_id
        if scoped is None and context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped)
        if blueprint is None:
            raise HTTPException(status_code=404, detail="solution blueprint not found")

        architecture = architect_solution_blueprint(
            blueprint,
            available_tool_ids=(tool.id for tool in agent_service.list_tools()),
            workflow_templates=list_workflow_templates(),
        )
        definition = generate_playbook_from_blueprint(blueprint, architecture)
        source_ref = f"architect:{blueprint.id}"
        provenance = f"architect_blueprint:{blueprint.id}"
        entry_id = f"architect-{blueprint.id}"
        existing = store.get_msp_playbook_entry(entry_id, blueprint.client_id)
        if existing is None:
            try:
                entry = store.create_msp_playbook_entry(
                    source_ref,
                    definition,
                    provenance=provenance,
                    client_id=blueprint.client_id,
                    enabled=False,
                    entry_id=entry_id,
                )
                response.status_code = 201
            except sqlite3.IntegrityError:
                entry = store.update_msp_playbook_entry(
                    entry_id,
                    definition=definition,
                    provenance=provenance,
                    enabled=False,
                    client_id=blueprint.client_id,
                    force_revision=True,
                )
        else:
            entry = store.update_msp_playbook_entry(
                entry_id,
                definition=definition,
                provenance=provenance,
                enabled=False,
                client_id=blueprint.client_id,
                force_revision=True,
            )
        return msp_playbook_entry_view(entry)

    @router.post("/consultant/connectors/openapi/validate")
    def validate_consultant_openapi_connector(
        payload: OpenApiConnectorRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            artifact = generate_power_platform_connector(payload.connector_id, payload.definition)
        except OpenApiDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"valid": True, "connector": artifact}

    @router.post("/consultant/connectors/openapi/generate")
    def generate_consultant_openapi_connector(
        payload: OpenApiConnectorRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return generate_power_platform_connector(payload.connector_id, payload.definition)
        except OpenApiDefinitionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/evaluations")
    def evaluate_consultant_contract(
        payload: EvaluationRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            if payload.execution is not None:
                if not active_settings.demo_mode or active_settings.allow_write_actions:
                    raise HTTPException(
                        status_code=409,
                        detail="controlled evaluation execution requires local demo mode with writes disabled",
                    )
                scoped_client_id = resolve_client_scope(context, payload.execution.client_id).client_id
                if scoped_client_id is None:
                    raise HTTPException(status_code=403, detail="evaluation execution requires a tenant scope")
                definition = agent_service.get(payload.execution.agent_id, scoped_client_id)
                if definition is None or definition.client_id != scoped_client_id:
                    raise HTTPException(status_code=404, detail="evaluation agent was not found in tenant scope")
                executor = AgentServiceEvaluationExecutor(
                    agent_service,
                    definition,
                    entity_id=payload.execution.entity_id,
                    actor=context.approver_id or "evaluation",
                    actor_role=context.role,
                    input_payload=payload.execution.input,
                    client_id=scoped_client_id,
                )
                return execute_tool_contract(payload.test_set, executor)
            return evaluate_tool_contract(payload.test_set, payload.observations)
        except EvaluationValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/governance/evaluate")
    def evaluate_consultant_governance(
        payload: GovernanceRequest,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        try:
            return evaluate_solution_governance(payload.architecture, payload.connector_artifacts)
        except GovernanceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/power-apps/plan")
    def consultant_power_apps_plan(
        payload: PowerAppsPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_apps_plan(
                client_id=scoped_client_id,
                app_name=payload.app_name,
                entities=payload.entities,
                screens=payload.screens,
                actions=payload.actions,
            )
        except PowerAppsPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/power-apps/build")
    def consultant_power_apps_build(
        payload: PowerAppsPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_apps_artifact(
                client_id=scoped_client_id,
                app_name=payload.app_name,
                entities=payload.entities,
                screens=payload.screens,
                actions=payload.actions,
            )
        except PowerAppsPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/power-platform/package")
    def build_consultant_power_platform_package(
        payload: PowerPlatformPackageRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_platform_package(
                client_id=scoped_client_id,
                solution_name=payload.solution_name,
                publisher_name=payload.publisher_name,
                publisher_prefix=payload.publisher_prefix,
                output_directory=payload.output_directory,
                artifacts=payload.artifacts,
                connector_artifacts=payload.connector_artifacts,
            )
        except PowerPlatformPackageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/consultant/power-platform/cli-status")
    @limiter.limit(active_settings.rate_limit_connector)
    def consultant_power_platform_cli_status(
        request: Request,
        _: TechnicianAccess,
    ) -> dict[str, object]:
        del request
        cli_status = power_platform_cli_status(active_settings)
        version = cli_status.get("version")
        try:
            version_compatible = (
                isinstance(version, str)
                and compare_pac_versions(version, PAC_XML_MINIMUM_VERSION) >= 0
            )
        except ValueError:
            version_compatible = False
        raw_path = cli_status.get("path")
        path_name = None
        if isinstance(raw_path, str) and raw_path:
            path_name = raw_path.replace("\\", "/").rsplit("/", 1)[-1]
        return {
            **cli_status,
            "path": path_name,
            "path_configured": isinstance(raw_path, str) and bool(raw_path),
            "minimum_version": PAC_XML_MINIMUM_VERSION,
            "version_compatible": version_compatible,
            "allow_write_actions": active_settings.allow_write_actions,
            "allow_power_platform_deployment": active_settings.allow_power_platform_deployment,
            "workspace_exists": active_settings.power_platform_workspace.is_dir(),
        }

    @router.post("/consultant/power-platform/package/validate")
    def validate_consultant_power_platform_package(
        payload: PowerPlatformPackageValidationRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        requested = payload.client_id
        package_client = payload.package.get("client_id")
        if requested is None and isinstance(package_client, str):
            requested = package_client
        scoped_client_id = resolve_client_scope(context, requested).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return package_validation_result(payload.package, client_id=scoped_client_id)
        except PowerPlatformPackageError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/power-platform/package/materialize")
    def materialize_consultant_power_platform_package(
        payload: PowerPlatformPackageMaterializationRequest,
        context: AdminAccess,
    ) -> dict[str, object]:
        if context.role < Role.ADMIN:
            raise HTTPException(status_code=403, detail="admin access required for package materialization")
        requested = payload.client_id
        package_client = payload.package.get("client_id")
        if requested is None and isinstance(package_client, str):
            requested = package_client
        scoped_client_id = resolve_client_scope(context, requested).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        result = materialize_power_platform_package(
            payload.package,
            active_settings,
            client_id=scoped_client_id,
        )
        if result.get("status") == "failed":
            raise HTTPException(status_code=422, detail=result.get("message", "package materialization failed"))
        return result

    def _consultant_discovery_result(client_id: str, answers: dict[str, object]) -> dict[str, object]:
        preliminary = build_solution_discovery(client_id=client_id, answers=answers)
        environment = discover_solution_environment(
            client_id=client_id,
            systems=cast(list[object], preliminary["answered"].get("systems", [])),
            connector_statuses=list_connector_statuses(active_settings),
            configured_client_id=active_settings.client_id,
        )
        return build_solution_discovery(client_id=client_id, answers=answers, environment=environment)

    def _promote_completed_discovery(
        result: dict[str, object],
        *,
        client_id: str,
        created_by: str,
    ) -> dict[str, object]:
        """Persist complete guided evidence as a review-only blueprint."""

        if result.get("status") != "complete":
            return result
        candidate = result.get("blueprint_candidate")
        answered = result.get("answered")
        if not isinstance(candidate, dict) or not isinstance(answered, dict):
            raise DiscoveryValidationError("completed discovery is missing blueprint evidence")
        solution = candidate.get("solution")
        solution_name = solution.get("name") if isinstance(solution, dict) else None
        if not isinstance(solution_name, str) or not solution_name.strip():
            solution_name = "Guided discovery solution"
        risk_review = result.get("risk_review")
        risk = risk_review.get("level") if isinstance(risk_review, dict) else None
        if risk not in {"low", "medium", "high"}:
            risk = "high" if answered.get("data_leaves_tenant") is True else "medium"
        try:
            blueprint = promote_discovery_candidate(
                candidate,
                client_id=client_id,
                solution_name=solution_name.strip(),
                risk=cast(str, risk),
                created_by=created_by,
            )
            persisted = store.create_solution_blueprint(blueprint)
        except BlueprintValidationError as exc:
            raise DiscoveryValidationError(f"completed discovery cannot become a blueprint: {exc}") from exc
        result["blueprint_id"] = persisted.id
        result["blueprint"] = blueprint_view(persisted)
        return result

    def _consultant_discovery_session_view(
        session: ConsultantDiscoverySession,
        *,
        client_id: str,
    ) -> dict[str, object]:
        """Rehydrate one persisted session without adding inference or execution."""

        try:
            answers_value = json.loads(session.answers_json)
            transcript_value = json.loads(session.transcript_json)
        except json.JSONDecodeError as exc:
            raise DiscoveryValidationError("discovery session state is invalid") from exc
        if not isinstance(answers_value, dict) or not isinstance(transcript_value, list):
            raise DiscoveryValidationError("discovery session state is invalid")
        transcript = [item for item in transcript_value if isinstance(item, dict)]
        result = _consultant_discovery_result(client_id, cast(dict[str, object], answers_value))
        result["session_status"] = session.status
        result["session_id"] = session.id
        result["principal_scope"] = session.principal_id
        result["transcript"] = transcript
        result["turn_index"] = max(0, (len(transcript) - 1) // 2)
        result["blueprint_id"] = session.blueprint_id
        result["created_at"] = session.created_at
        result["updated_at"] = session.updated_at
        return result

    @router.post("/consultant/discovery")
    def consultant_discovery(
        payload: DiscoveryRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return _consultant_discovery_result(scoped_client_id, payload.answers)
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/discovery/promote", status_code=201)
    def consultant_discovery_promote(
        payload: DiscoveryBlueprintPromotionRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            discovery = _consultant_discovery_result(scoped_client_id, payload.answers)
            missing = cast(list[object], discovery["missing_required"])
            if missing:
                fields = ", ".join(str(item) for item in missing)
                raise DiscoveryValidationError(f"discovery is missing required answers: {fields}")
            candidate = discovery.get("blueprint_candidate")
            if not isinstance(candidate, dict):
                raise DiscoveryValidationError("discovery blueprint candidate is invalid")
            blueprint = promote_discovery_candidate(
                candidate,
                client_id=scoped_client_id,
                solution_name=payload.solution_name,
                risk=payload.risk,
                created_by=context.approver_id or "api",
            )
            persisted = store.create_solution_blueprint(blueprint)
            return {
                "blueprint": blueprint_view(persisted),
                "discovery": discovery,
                "execution_started": False,
                "deployment_started": False,
            }
        except (BlueprintValidationError, DiscoveryValidationError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/discovery/sessions")
    def consultant_discovery_session_start(
        payload: DiscoverySessionStartRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        answers = dict(payload.answers)
        opening_message = payload.opening_message.strip() if payload.opening_message else None
        try:
            if opening_message:
                build_solution_discovery(
                    client_id=scoped_client_id,
                    answers={"business_goal": opening_message},
                )
                if "business_goal" not in answers:
                    answers["business_goal"] = opening_message
            result = _promote_completed_discovery(
                _consultant_discovery_result(scoped_client_id, answers),
                client_id=scoped_client_id,
                created_by=context.approver_id or "api",
            )
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        principal_id = context.approver_id or "api"
        answered = cast(dict[str, object], result["answered"])
        transcript: list[dict[str, object]] = []
        if opening_message:
            transcript.append(
                {
                    "role": "user",
                    "field": "business_goal",
                    "content": answered.get("business_goal", opening_message),
                }
            )
        next_question = cast(dict[str, object] | None, result.get("next_question"))
        if next_question is not None:
            transcript.append(
                {
                    "role": "assistant",
                    "field": next_question["id"],
                    "content": next_question["prompt"],
                }
            )
        session = store.create_consultant_discovery_session(
            client_id=scoped_client_id,
            principal_id=principal_id,
            answers=answered,
            transcript=transcript,
            blueprint_id=cast(str | None, result.get("blueprint_id")),
        )
        return _consultant_discovery_session_view(session, client_id=scoped_client_id)

    @router.get("/consultant/discovery/sessions")
    def consultant_discovery_session_list(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> list[dict[str, object]]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = context.approver_id or "api"
        try:
            sessions = store.list_consultant_discovery_sessions(
                client_id=scoped_client_id,
                principal_id=principal_id,
            )
            return [
                _consultant_discovery_session_view(session, client_id=scoped_client_id)
                for session in sessions
            ]
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/consultant/discovery/sessions/{session_id}")
    def consultant_discovery_session_get(
        session_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = context.approver_id or "api"
        session = store.get_consultant_discovery_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="discovery session not found")
        try:
            return _consultant_discovery_session_view(session, client_id=scoped_client_id)
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/consultant/discovery/sessions/{session_id}/turn")
    def consultant_discovery_session_turn(
        session_id: str,
        payload: DiscoveryTurnRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        principal_id = context.approver_id or "api"
        session = store.get_consultant_discovery_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
        )
        if session is None:
            raise HTTPException(status_code=404, detail="discovery session not found")
        if session.status != "active":
            raise HTTPException(status_code=409, detail="discovery session is already complete")
        if payload.field == "impact":
            raise HTTPException(status_code=422, detail="impact estimates belong to stateless discovery intake")
        try:
            answers_value = json.loads(session.answers_json)
            transcript_value = json.loads(session.transcript_json)
            if not isinstance(answers_value, dict) or not isinstance(transcript_value, list):
                raise DiscoveryValidationError("discovery session state is invalid")
            answers = dict(cast(dict[str, object], answers_value))
            answers[payload.field] = payload.answer
            result = _promote_completed_discovery(
                _consultant_discovery_result(scoped_client_id, answers),
                client_id=scoped_client_id,
                created_by=principal_id,
            )
        except (DiscoveryValidationError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        answered = cast(dict[str, object], result["answered"])
        transcript = [item for item in cast(list[object], transcript_value) if isinstance(item, dict)]
        transcript.append(
            {
                "role": "user",
                "field": payload.field,
                "content": answered[payload.field],
            }
        )
        next_question = cast(dict[str, object] | None, result.get("next_question"))
        if next_question is not None:
            transcript.append(
                {
                    "role": "assistant",
                    "field": next_question["id"],
                    "content": next_question["prompt"],
                }
            )
        if len(transcript) > 64:
            raise HTTPException(status_code=422, detail="discovery session has reached its turn limit")
        discovery_status = cast(str, result["status"])
        persisted_status = {
            "active": "active",
            "complete": "completed",
        }.get(discovery_status)
        if persisted_status is None:
            raise HTTPException(status_code=422, detail="discovery result status is invalid")
        updated = store.update_consultant_discovery_session(
            session_id,
            client_id=scoped_client_id,
            principal_id=principal_id,
            status=persisted_status,
            answers=answered,
            transcript=transcript,
            blueprint_id=cast(str | None, result.get("blueprint_id")),
        )
        if updated is None:
            raise HTTPException(status_code=409, detail="discovery session could not be updated")
        return _consultant_discovery_session_view(updated, client_id=scoped_client_id)

    @router.post("/consultant/environment-discovery")
    def consultant_environment_discovery(
        payload: EnvironmentDiscoveryRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            connector_statuses = list_connector_statuses(active_settings)
            result = discover_solution_environment(
                client_id=scoped_client_id,
                systems=payload.systems,
                connector_statuses=connector_statuses,
                configured_client_id=active_settings.client_id,
            )
            if payload.probe:
                connector_ids = [
                    cast(str, item["connector_id"])
                    for item in cast(list[dict[str, object]], result["systems"])
                    if isinstance(item.get("connector_id"), str)
                    and item.get("status") == "configured"
                ]
                probe_results = (
                    probe_connector_health(
                        connector_ids,
                        active_settings,
                        halopsa_client=halopsa_client,
                        hudu_client=hudu_client,
                        connectwise_client=connectwise_client,
                        syncro_client=syncro_client,
                        servicenow_client=servicenow_client,
                        autotask_client=autotask_client,
                        itglue_client=itglue_client,
                        confluence_client=confluence_client,
                        notion_client=notion_client,
                        sharepoint_client=sharepoint_client,
                        m365_client=m365_client,
                        timezest_client=timezest_client,
                        scalepad_client=scalepad_client,
                    )
                    if active_settings.allow_http_probing
                    else {}
                )
                result = discover_solution_environment(
                    client_id=scoped_client_id,
                    systems=payload.systems,
                    connector_statuses=connector_statuses,
                    configured_client_id=active_settings.client_id,
                    probe_results=probe_results,
                )
            status_counts: dict[str, int] = {}
            for item in cast(list[dict[str, object]], result["systems"]):
                status = item.get("status")
                if isinstance(status, str):
                    status_counts[status] = status_counts.get(status, 0) + 1
            store.add_audit_event(
                "consultant.environment_discovery",
                scoped_client_id,
                f"probe_requested={payload.probe} probe_performed={result['probe_performed']} "
                f"system_statuses={json.dumps(status_counts, sort_keys=True)}",
                client_id=scoped_client_id,
                approver_id=context.approver_id or "api",
            )
            return result
        except DiscoveryValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/supervisor/plan")
    def consultant_supervisor_plan(
        payload: SupervisorPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definitions = agent_service.list_definitions(scoped_client_id)
        try:
            return build_supervisor_delegation_plan(
                client_id=scoped_client_id,
                task=payload.task,
                child_agent_ids=payload.child_agent_ids,
                definitions=definitions,
                max_retries=payload.max_retries,
            )
        except SupervisorPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/supervisor/run")
    def consultant_supervisor_run(
        payload: SupervisorRunRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        definitions = agent_service.list_definitions(scoped_client_id)
        try:
            return execute_supervisor_delegation(
                client_id=scoped_client_id,
                entity_id=payload.entity_id,
                task=payload.task,
                child_agent_ids=payload.child_agent_ids,
                definitions=definitions,
                agent_service=agent_service,
                store=store,
                actor=context.approver_id or "api",
                actor_role=context.role,
                input_payload=payload.input,
                completed_run_ids=payload.completed_run_ids,
                max_retries=payload.max_retries,
                cancel_run_id=payload.cancel_run_id,
            )
        except SupervisorPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/delivery-plan")
    def consultant_delivery_plan(
        payload: DeliveryPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_consultant_delivery_plan(
                client_id=scoped_client_id,
                architecture=payload.architecture,
                evaluation=payload.evaluation,
                governance=payload.governance,
                deployment_targets=payload.deployment_targets,
                connector_artifacts=payload.connector_artifacts,
                review_artifacts=payload.review_artifacts,
                deployable_package=payload.deployable_package,
            )
        except DeliveryPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/solutions/deployment-approvals", status_code=201)
    @limiter.limit(active_settings.rate_limit_connector)
    def request_power_platform_deployment_approval(
        payload: PowerPlatformDeploymentRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            plan = build_power_platform_deployment_plan(
                solution_name=payload.solution_name,
                publisher_name=payload.publisher_name,
                publisher_prefix=payload.publisher_prefix,
                output_directory=payload.output_directory,
                deployment_targets=payload.deployment_targets,
            )
            promotion_evidence = validate_promotion_evidence(payload.stage, payload.promotion_evidence)
            approval_payload = {
                "format": "wait-local-agent.power-platform.deployment-approval",
                "format_version": 1,
                "client_id": scoped_client_id,
                "solution_name": payload.solution_name,
                "publisher_name": payload.publisher_name,
                "publisher_prefix": payload.publisher_prefix,
                "output_directory": payload.output_directory,
                "deployment_targets": plan["deployment_targets"],
                "stage": payload.stage,
                "promotion_evidence": promotion_evidence,
                "credentials_included": False,
            }
            if promotion_evidence:
                source_id = cast(int, promotion_evidence["source_approval_request_id"])
                source_approval = store.get_approval_request(source_id)
                if source_approval is not None and not _approval_scope_visible(context, source_approval):
                    source_approval = None
                validate_promotion_source(
                    payload.stage,
                    promotion_evidence,
                    source_approval=_power_platform_source_record(source_approval),
                    current_payload=approval_payload,
                )
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        approval = store.create_approval_request(
            subject_id=f"{scoped_client_id}:{payload.solution_name}:{payload.stage}",
            action_type="power_platform.solution_stage",
            payload=approval_payload,
            client_id=scoped_client_id,
        )
        return {"approval": _approval_view(approval), "plan": plan}

    @router.post("/consultant/solutions/deployment-approvals/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_power_platform_deployment_stage(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        approval = store.get_approval_request(request_id)
        if (
            approval is None
            or approval.action_type != "power_platform.solution_stage"
            or not _approval_scope_visible(context, approval)
        ):
            raise HTTPException(status_code=404, detail="deployment approval request not found")
        if approval.status != "approved":
            raise HTTPException(status_code=409, detail="deployment approval must be approved before execution")
        if approval.execution_status in _TERMINAL_EXECUTION_STATUSES:
            raise HTTPException(status_code=409, detail="deployment approval request has already executed")
        try:
            payload = _safe_json_object(approval.payload_json)
            plan = build_power_platform_deployment_plan_from_payload(payload)
            stage_id = payload.get("stage")
            if not isinstance(stage_id, str):
                raise PowerPlatformDeploymentError("deployment approval stage is invalid")
            promotion_evidence = payload.get("promotion_evidence")
            if isinstance(promotion_evidence, dict) and promotion_evidence:
                source_id = promotion_evidence.get("source_approval_request_id")
                if not isinstance(source_id, int) or isinstance(source_id, bool):
                    raise PowerPlatformDeploymentError("promotion evidence source approval id is invalid")
                source_approval = store.get_approval_request(source_id)
                if source_approval is not None and not _approval_scope_visible(context, source_approval):
                    source_approval = None
                validate_promotion_source(
                    stage_id,
                    promotion_evidence,
                    source_approval=_power_platform_source_record(source_approval),
                    current_payload=payload,
                )
            if not store.claim_approval_execution(request_id):
                raise HTTPException(status_code=409, detail="deployment approval request has already executed")
            result = execute_power_platform_stage(
                plan,
                stage_id,
                active_settings,
                approved=True,
            )
            updated = store.record_approval_execution(
                request_id,
                status=cast(str, result["status"]),
                message=cast(str, result["message"]),
                result=result,
                audit_event_type="power_platform.solution_stage",
            )
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (KeyError, PermissionError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _approval_view(updated)

    @router.post("/consultant/solutions/rollback-approvals", status_code=201)
    @limiter.limit(active_settings.rate_limit_connector)
    def request_power_platform_rollback_approval(
        payload: PowerPlatformRollbackRequest,
        request: Request,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        del request
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            plan = build_power_platform_deployment_plan(
                solution_name=payload.solution_name,
                publisher_name=payload.publisher_name,
                publisher_prefix=payload.publisher_prefix,
                output_directory=payload.output_directory,
                deployment_targets=payload.deployment_targets,
            )
            rollback_evidence = validate_rollback_evidence(payload.rollback_evidence)
            artifact_digest = validate_power_platform_solution_package(
                Path(payload.rollback_artifact_path),
                active_settings.power_platform_workspace,
            )
            if artifact_digest != rollback_evidence["artifact_digest"]:
                raise PowerPlatformDeploymentError(
                    "rollback artifact digest does not match rollback evidence"
                )
            approval_payload = {
                "format": "wait-local-agent.power-platform.rollback-approval",
                "format_version": 1,
                "client_id": scoped_client_id,
                "solution_name": payload.solution_name,
                "publisher_name": payload.publisher_name,
                "publisher_prefix": payload.publisher_prefix,
                "output_directory": payload.output_directory,
                "deployment_targets": plan["deployment_targets"],
                "stage": payload.stage,
                "rollback_artifact_path": str(Path(payload.rollback_artifact_path).expanduser().resolve()),
                "rollback_evidence": rollback_evidence,
                "credentials_included": False,
            }
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        approval = store.create_approval_request(
            subject_id=f"{scoped_client_id}:{payload.solution_name}:rollback:{payload.stage}",
            action_type="power_platform.solution_rollback",
            payload=approval_payload,
            client_id=scoped_client_id,
        )
        return {"approval": _approval_view(approval), "plan": plan}

    @router.post("/consultant/solutions/rollback-approvals/{request_id}/execute")
    @limiter.limit(active_settings.rate_limit_connector)
    def execute_power_platform_rollback_approval(
        request_id: int,
        request: Request,
        context: AdminAccess,
    ) -> dict[str, object]:
        del request
        approval = store.get_approval_request(request_id)
        if (
            approval is None
            or approval.action_type != "power_platform.solution_rollback"
            or not _approval_scope_visible(context, approval)
        ):
            raise HTTPException(status_code=404, detail="Power Platform rollback approval request not found")
        if approval.status != "approved":
            raise HTTPException(status_code=409, detail="rollback approval must be approved before execution")
        if approval.execution_status in _TERMINAL_EXECUTION_STATUSES:
            raise HTTPException(status_code=409, detail="rollback approval request has already executed")
        try:
            payload = _safe_json_object(approval.payload_json)
            plan = build_power_platform_deployment_plan_from_payload(payload)
            stage_id = payload.get("stage")
            artifact_path = payload.get("rollback_artifact_path")
            rollback_evidence = payload.get("rollback_evidence")
            if not isinstance(stage_id, str):
                raise PowerPlatformDeploymentError("rollback approval stage is invalid")
            if not isinstance(artifact_path, str):
                raise PowerPlatformDeploymentError("rollback approval artifact path is invalid")
            normalized_evidence = validate_rollback_evidence(rollback_evidence)
            if not store.claim_approval_execution(request_id):
                raise HTTPException(status_code=409, detail="rollback approval request has already executed")
            result = execute_power_platform_rollback(
                plan,
                stage_id,
                active_settings,
                rollback_artifact_path=artifact_path,
                rollback_evidence=normalized_evidence,
                approved=True,
            )
            updated = store.record_approval_execution(
                request_id,
                status=cast(str, result["status"]),
                message=cast(str, result["message"]),
                result=result,
                audit_event_type="power_platform.solution_rollback",
            )
        except PowerPlatformDeploymentError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (KeyError, PermissionError, RuntimeError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _approval_view(updated)

    @router.get("/consultant/use-cases")
    def consultant_use_cases(
        context: ViewerAccess,
        category: str | None = Query(default=None, max_length=32),
    ) -> dict[str, object]:
        del context
        try:
            return list_consultant_use_cases(category)
        except UseCaseCatalogError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/workflows/power-automate/plan")
    def consultant_power_automate_plan(
        payload: PowerAutomatePlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_power_automate_flow_plan(
                client_id=scoped_client_id,
                workflow_id=payload.workflow_id,
                workflow_name=payload.workflow_name,
                trigger=payload.trigger,
                steps=payload.steps,
            )
        except PowerAutomatePlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/consultant/copilot-studio/plan")
    def consultant_copilot_studio_plan(
        payload: CopilotStudioPlanRequest,
        context: TechnicianAccess,
    ) -> dict[str, object]:
        scoped_client_id = resolve_client_scope(context, payload.client_id).client_id
        if scoped_client_id is None:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        try:
            return build_copilot_studio_plan(
                client_id=scoped_client_id,
                copilot_name=payload.copilot_name,
                business_goal=payload.business_goal,
                topics=payload.topics,
                knowledge_sources=payload.knowledge_sources,
                actions=payload.actions,
            )
        except CopilotStudioPlanError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/consultant/monitoring/agents")
    def consultant_agent_monitoring(
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scope = resolve_client_scope(context, client_id)
        scoped_client_id = scope.client_id
        return build_agent_health_summary(
            store.list_agent_runs(scope),
            agent_service.list_definitions(scoped_client_id),
            client_id=scoped_client_id,
        )

    @router.get("/consultant/blueprints/{blueprint_id}")
    def consultant_blueprint_detail(
        blueprint_id: str,
        context: ViewerAccess,
        client_id: str | None = None,
    ) -> dict[str, object]:
        scoped_client_id = _resolve_detail_scope(context, client_id).client_id
        if scoped_client_id is None and context.role < Role.ADMIN and not context.is_msp_admin:
            raise HTTPException(status_code=403, detail="authenticated principal has no tenant")
        blueprint = store.get_solution_blueprint(blueprint_id, client_id=scoped_client_id)
        if blueprint is None:
            raise HTTPException(status_code=404, detail="solution blueprint not found")
        return blueprint_view(blueprint)

    return router


__all__ = ["create_consultant_router"]
