"""FastAPI application for Dómnir adversarial qualification platform."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from domnir.court_record import verify_court_record
from domnir.api.jobs import JobOrchestrator, get_default_model_path
from domnir.api.models import (
    ArtifactsResponse,
    ContainmentStatusResponse,
    CourtRecordVerifyRequest,
    CourtRecordVerifyResponse,
    ExperimentDetailResponse,
    ExperimentSummary,
    GenerateControllerRequest,
    GenerateControllerResponse,
    HealthResponse,
    ModelInfo,
    ModelsResponse,
    RagnarokFalsifyRequest,
    RagnarokFalsifyResponse,
    RagnarokMinimizeRequest,
    RagnarokMinimizeResponse,
    RagnarokRepairRequest,
    RagnarokRepairResponse,
    RagnarokArenaRequest,
    RagnarokArenaResponse,
    MissionRunRequest,
    MissionRunResponse,
    ReadyResponse,
    RunExperimentRequest,
    SpecValidationRequest,
    SpecValidationResponse,
)
from domnir.worlds import list_worlds, get_world
from domnir.missions import run_mission_simulation, MissionSpecV2, MissionStage, MissionStageKind, MissionConstraints
from domnir.controls import Baseline3DController
from domnir.contracts.stl import SafetyContract, STLMonitor, STLRobustnessResult
from domnir.ragnarok.minimize import CounterexampleMinimizer
from domnir.ragnarok.repair import AutonomousRepairEngine
from domnir.ragnarok.arena import RedBlueArenaOrchestrator
from domnir.ragnarok.search import (
    DifferentialEvolutionFalsifier,
    RagnarokSearchSpace,
    ScenarioParameter,
    SobolBaselineFalsifier,
    compare_falsification_policies,
)
from domnir.spec import FlightSpec, GeneratedController
from domnir.api.security import (
    PayloadTooLargeError,
    RateLimitMiddleware,
    RequestSizeLimitMiddleware,
    SecurityHeadersMiddleware,
    validate_id_param,
)
from domnir.containment_runner import (
    execute_containment_suite,
    get_containment_status,
    is_microvm_available,
)
from domnir.inference.vultr import (
    DEFAULT_MODEL,
    SUPPORTED_MODELS,
    ModelNotFoundError,
    VultrInferenceClient,
    resolve_model_id,
)
from domnir.spec import FlightSpec

app = FastAPI(
    title="Dómnir Orchestrator API",
    description="Adversarial qualification and containment platform for AI-generated flight controllers.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RateLimitMiddleware)


@app.exception_handler(PayloadTooLargeError)
async def handle_payload_too_large(request: Any, exc: PayloadTooLargeError) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": exc.detail},
    )

orchestrator = JobOrchestrator()


@app.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="domnir-api",
        version="0.1.0",
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/ready", response_model=ReadyResponse)
def get_ready() -> ReadyResponse:
    model_path = orchestrator.model_path
    model_loaded = model_path.is_file()
    inference_configured = bool(orchestrator.inference_client.api_key)

    microvm_available = is_microvm_available()
    is_prod = os.environ.get("DOMNIR_ENV", os.environ.get("ENV", "")).lower() in {"production", "prod", "live"}
    dev_fallback = (not is_prod) and (os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK") == "1")
    execution_permitted = bool(microvm_available or dev_fallback)

    live_inference_verified = orchestrator.inference_client.is_live_verified()

    if model_loaded and inference_configured and microvm_available:
        status_str = "ready"
        ready_flag = True
    elif model_loaded and inference_configured and dev_fallback:
        status_str = "degraded (dev mock mode)"
        ready_flag = True
    else:
        status_str = "unavailable (isolation missing)"
        ready_flag = False

    return ReadyResponse(
        ready=ready_flag,
        status=status_str,
        http_health=True,
        model_loaded=model_loaded,
        inference_configured=inference_configured,
        live_inference_verified=live_inference_verified,
        microvm_available=microvm_available,
        execution_permitted=execution_permitted,
        supported_models=list(SUPPORTED_MODELS.keys()),
        details={
            "model_path": str(model_path),
            "backend": "microvm" if microvm_available else ("subprocess_dev" if dev_fallback else "unavailable"),
            "active_jobs": len(orchestrator.list_jobs()),
        },
    )


@app.get("/models", response_model=ModelsResponse)
def list_models() -> ModelsResponse:
    model_list = [
        ModelInfo(
            id=data["id"],
            name=data["name"],
            family=data["family"],
            provider=data.get("provider", "vultr"),
            description=data["description"],
            default=data.get("default", False),
            reasoning_effort=data.get("reasoning_effort", "minimal"),
        )
        for data in SUPPORTED_MODELS.values()
    ]
    return ModelsResponse(models=model_list, default_model=DEFAULT_MODEL)


@app.post("/specs/validate", response_model=SpecValidationResponse)
def validate_spec(request: SpecValidationRequest) -> SpecValidationResponse:
    return SpecValidationResponse(
        valid=True,
        spec=request.spec,
        step_budget=request.spec.step_budget,
        message="Flight specification validated successfully",
    )


@app.post("/controllers/generate", response_model=GenerateControllerResponse)
def generate_controller(request: GenerateControllerRequest) -> GenerateControllerResponse:
    try:
        model_id = resolve_model_id(request.model)
    except ModelNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )

    try:
        controller = orchestrator.inference_client.generate_controller(
            request.spec,
            model=model_id,
            prompt_version=request.prompt_version,
            reasoning_effort=request.reasoning_effort,
            max_tokens=request.max_tokens,
        )
        return GenerateControllerResponse(
            controller=controller,
            model_id=controller.model_id,
            source_sha256=controller.source_sha256,
            reasoning_effort=request.reasoning_effort,
            message="Controller generated and statically validated",
        )
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate controller with model '{model_id}': {error}",
        )


@app.post("/experiments/run", response_model=ExperimentSummary)
def run_experiment(
    request: RunExperimentRequest,
    background_tasks: BackgroundTasks,
) -> ExperimentSummary:
    if request.model:
        try:
            request.model = resolve_model_id(request.model)
        except ModelNotFoundError as err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(err),
            )

    try:
        job = orchestrator.create_job(request)
    except RuntimeError as queue_err:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(queue_err),
        )

    if request.run_async:
        background_tasks.add_task(orchestrator.execute_job, job)
        return job.to_summary()

    orchestrator.execute_job(job)
    return job.to_summary()


@app.get("/experiments/{experiment_id}", response_model=ExperimentDetailResponse)
def get_experiment(experiment_id: str) -> ExperimentDetailResponse:
    try:
        validate_id_param(experiment_id, "experiment_id")
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    job = orchestrator.get_job(experiment_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )
    return job.to_detail()


@app.get("/experiments/{experiment_id}/artifacts", response_model=ArtifactsResponse)
def get_experiment_artifacts(experiment_id: str) -> ArtifactsResponse:
    try:
        validate_id_param(experiment_id, "experiment_id")
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    job = orchestrator.get_job(experiment_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )
    return job.to_artifacts()


@app.get("/experiments/{experiment_id}/court-record")
def get_experiment_court_record(experiment_id: str) -> dict[str, Any]:
    try:
        validate_id_param(experiment_id, "experiment_id")
    except ValueError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )
    job = orchestrator.get_job(experiment_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Experiment '{experiment_id}' not found",
        )
    if job.court_record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Court record not available for experiment '{experiment_id}'",
        )
    return job.court_record


@app.post("/court-records/verify", response_model=CourtRecordVerifyResponse)
def verify_court_record_endpoint(
    request: CourtRecordVerifyRequest,
) -> CourtRecordVerifyResponse:
    record_data: dict[str, Any]
    if request.court_record is not None and isinstance(request.court_record, dict):
        record_data = request.court_record
    else:
        raw = request.model_dump(exclude_none=True)
        if "court_record" in raw and isinstance(raw["court_record"], dict):
            record_data = raw["court_record"]
        else:
            record_data = raw

    if not record_data or not isinstance(record_data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid Court Record payload is required",
        )

    try:
        result = verify_court_record(
            record_data, model_path=orchestrator.model_path
        )
        return CourtRecordVerifyResponse(**result)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Court record verification failed: {error}",
        )


@app.get("/containment/status", response_model=ContainmentStatusResponse)
def get_containment_status_endpoint() -> ContainmentStatusResponse:
    status_dict = get_containment_status()
    return ContainmentStatusResponse(**status_dict)


@app.post("/containment/run", response_model=ContainmentStatusResponse)
def run_containment_endpoint(request: Request) -> ContainmentStatusResponse:
    operator_token = os.environ.get("DOMNIR_OPERATOR_TOKEN")
    if not operator_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Live containment execution is disabled: operator authorization token is not configured on this host. Public judges can inspect verified containment proofs via GET /containment/status.",
        )
    provided = request.headers.get("x-operator-token") or request.query_params.get("token")
    if provided != operator_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Live containment execution is restricted to operators. Public judges can inspect verified containment proofs via GET /containment/status.",
        )

    try:
        result = execute_containment_suite()
        return ContainmentStatusResponse(**result)
    except RuntimeError as err:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(err),
        )
    except Exception as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Containment execution error: {err}",
        )


def _evaluate_scenario_with_orchestrator(
    spec: FlightSpec,
    controller_source: str,
    scenario: ScenarioParameter,
) -> STLRobustnessResult:
    contract = SafetyContract.from_flight_spec(spec)
    ctrl = GeneratedController.from_source(controller_source, model_id="candidate")
    job = orchestrator.create_job(
        RunExperimentRequest(
            spec=spec,
            controller=ctrl,
            initial_altitude_m=scenario.initial_altitude_m,
            vertical_disturbance_n=scenario.disturbance_force_z,
            pulse_start_s=scenario.pulse_start_s,
            pulse_duration_s=scenario.pulse_duration_s,
            steps=contract.physics_steps,
        )
    )
    orchestrator.execute_job(job)
    return STLMonitor.evaluate_trajectory(contract, job.trajectory)


@app.post("/ragnarok/falsify", response_model=RagnarokFalsifyResponse)
def ragnarok_falsify_endpoint(request: RagnarokFalsifyRequest) -> RagnarokFalsifyResponse:
    try:
        ctrl = GeneratedController.from_source(request.controller_source, model_id="candidate")
        contract = SafetyContract.from_flight_spec(request.spec)
        space = RagnarokSearchSpace.from_contract(contract)

        def eval_fn(s: ScenarioParameter) -> STLRobustnessResult:
            return _evaluate_scenario_with_orchestrator(request.spec, ctrl.source_code, s)

        if request.strategy == "compare":
            comp = compare_falsification_policies(space, eval_fn, evaluations_budget=request.budget, seed=request.seed)
            total_evals = sum(
                comp[k].get("evaluations", request.budget)
                for k in ("uniform_random", "sobol", "differential_evolution")
                if k in comp
            )
            return RagnarokFalsifyResponse(
                strategy="compare",
                evaluations_count=total_evals,
                first_violation_iteration=comp["differential_evolution"]["first_violation"],
                violations_found=comp["differential_evolution"]["violations_found"],
                min_robustness=comp["differential_evolution"]["min_robustness"],
                best_scenario={"strategy": "comparison"},
                comparison=comp,
                summary=f"Compared Uniform Random vs Sobol vs Differential Evolution (total {total_evals} evaluations across 3 strategies). DE/Sobol efficiency ratio: {comp.get('discovery_efficiency_ratio', 1.0)}",
            )
        elif request.strategy == "sobol":
            falsifier = SobolBaselineFalsifier(space, seed=request.seed)
            res = falsifier.run(eval_fn, max_evaluations=request.budget)
        else:
            falsifier = DifferentialEvolutionFalsifier(space, seed=request.seed)
            res = falsifier.run(eval_fn, max_evaluations=request.budget)

        witness_dict = None
        if res.critical_witness is not None:
            witness_dict = {
                "iteration": res.critical_witness.iteration,
                "scenario": res.critical_witness.scenario.model_dump(),
                "robustness": res.critical_witness.robustness,
                "critical_predicate": res.critical_witness.critical_predicate,
                "critical_time_s": res.critical_witness.critical_time_s,
            }

        candidates_data = [
            {
                "candidate_id": c.candidate_id,
                "iteration": c.iteration,
                "scenario": c.scenario.model_dump(),
                "robustness": c.robustness,
                "satisfied": c.satisfied,
                "critical_predicate": c.critical_predicate,
                "critical_time_s": c.critical_time_s,
            }
            for c in res.all_candidates
        ]

        return RagnarokFalsifyResponse(
            strategy=res.strategy,
            evaluations_count=res.evaluations_count,
            first_violation_iteration=res.first_violation_iteration,
            violations_found=res.violations_found,
            min_robustness=res.min_robustness,
            best_scenario=res.best_scenario.model_dump(),
            critical_witness=witness_dict,
            candidates=candidates_data,
            summary=res.summary,
        )
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@app.post("/ragnarok/minimize", response_model=RagnarokMinimizeResponse)
def ragnarok_minimize_endpoint(request: RagnarokMinimizeRequest) -> RagnarokMinimizeResponse:
    try:
        ctrl = GeneratedController.from_source(request.controller_source, model_id="candidate")
        witness_param = ScenarioParameter(**request.witness_scenario)
        contract = SafetyContract.from_flight_spec(request.spec)

        def eval_fn(s: ScenarioParameter) -> STLRobustnessResult:
            return _evaluate_scenario_with_orchestrator(request.spec, ctrl.source_code, s)

        minimizer = CounterexampleMinimizer(
            target_altitude_m=contract.target_altitude_m,
            max_evaluations=request.max_evaluations,
        )
        res = minimizer.minimize(witness_param, eval_fn)

        return RagnarokMinimizeResponse(
            original_scenario=res.original_scenario.model_dump(),
            minimized_scenario=res.minimized_scenario.model_dump(),
            original_robustness=res.original_robustness,
            minimized_robustness=res.minimized_robustness,
            original_cost=res.original_cost,
            minimized_cost=res.minimized_cost,
            cost_reduction_ratio=res.cost_reduction_ratio,
            evaluations_used=res.evaluations_used,
            predicate_preserved=res.predicate_preserved,
            summary=res.summary,
        )
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@app.post("/ragnarok/repair", response_model=RagnarokRepairResponse)
def ragnarok_repair_endpoint(request: RagnarokRepairRequest) -> RagnarokRepairResponse:
    try:
        ctrl = GeneratedController.from_source(request.controller_source, model_id="candidate")
        witness_param = ScenarioParameter(**request.witness_scenario)
        contract = SafetyContract.from_flight_spec(request.spec)

        def eval_ctrl(c: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
            return _evaluate_scenario_with_orchestrator(request.spec, c.source_code, s)

        witness_res = eval_ctrl(ctrl, witness_param)
        if witness_res.satisfied:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Witness scenario does not violate safety contract for this controller.",
            )

        repair_engine = AutonomousRepairEngine(
            contract,
            evaluator=eval_ctrl,
            inference_client=orchestrator.inference_client,
            max_revisions=request.max_revisions,
        )
        res = repair_engine.run_repair(ctrl, witness_param, witness_res)

        history_records = [
            {
                "revision": h.revision_number,
                "source_sha256": h.source_sha256,
                "passed_known_failure": h.passed_known_failure,
                "passed_nominal": h.passed_nominal,
                "passed_holdout": h.passed_holdout,
                "holdout_pass_rate": h.holdout_pass_rate,
                "accepted": h.accepted,
                "rejection_reason": h.rejection_reason,
            }
            for h in res.history
        ]

        return RagnarokRepairResponse(
            outcome=res.outcome,
            repaired_controller_source=res.repaired_controller.source_code if res.repaired_controller else None,
            repaired_source_sha256=res.repaired_controller.source_sha256 if res.repaired_controller else None,
            total_revisions_attempted=res.total_revisions_attempted,
            history=history_records,
            summary=res.summary,
        )
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@app.post("/ragnarok/arena/run", response_model=RagnarokArenaResponse)
def ragnarok_arena_run_endpoint(request: RagnarokArenaRequest) -> RagnarokArenaResponse:
    try:
        ctrl = GeneratedController.from_source(request.controller_source, model_id="initial-candidate")
        contract = SafetyContract.from_flight_spec(request.spec)

        def eval_ctrl(c: GeneratedController, s: ScenarioParameter) -> STLRobustnessResult:
            return _evaluate_scenario_with_orchestrator(request.spec, c.source_code, s)

        arena = RedBlueArenaOrchestrator(
            contract=contract,
            evaluator=eval_ctrl,
            inference_client=orchestrator.inference_client,
            search_budget_per_round=request.search_budget_per_round,
            max_repair_revisions=request.max_repair_revisions,
        )
        report = arena.run_campaign(
            initial_controller=ctrl,
            max_rounds=request.max_rounds,
        )

        rounds_data = [r.model_dump() for r in report.rounds]
        final_src = report.final_controller.source_code if report.final_controller else None

        return RagnarokArenaResponse(
            campaign_id=report.campaign_id,
            target_altitude_m=report.target_altitude_m,
            total_rounds_executed=report.total_rounds_executed,
            initial_controller_sha256=report.initial_controller_sha256,
            final_controller_sha256=report.final_controller_sha256,
            final_controller_source=final_src,
            rounds=rounds_data,
            accumulated_regression_suite_size=report.accumulated_regression_suite_size,
            summary=report.summary,
            limitation_note=report.limitation_note,
        )
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@app.get("/worlds", response_model=list[dict[str, Any]])
async def get_worlds_endpoint() -> list[dict[str, Any]]:
    worlds = []
    for item in list_worlds():
        w = get_world(item["id"])
        worlds.append({
            "id": w.world_id,
            "name": w.name,
            "floor_dimensions_m": w.floor_dimensions_m,
            "entities": [
                {
                    "id": e.id,
                    "kind": e.kind.value,
                    "position_m": e.pose.position_m,
                    "dimensions_m": e.dimensions_m,
                    "contact_class": e.contact_class,
                }
                for e in w.entities
            ],
        })
    return worlds


@app.get("/worlds/{world_id}", response_model=dict[str, Any])
async def get_world_detail_endpoint(world_id: str) -> dict[str, Any]:
    w = get_world(world_id)
    return {
        "id": w.world_id,
        "name": w.name,
        "floor_dimensions_m": w.floor_dimensions_m,
        "entities": [
            {
                "id": e.id,
                "kind": e.kind.value,
                "position_m": e.pose.position_m,
                "dimensions_m": e.dimensions_m,
                "contact_class": e.contact_class,
            }
            for e in w.entities
        ],
    }


@app.post("/missions/run", response_model=MissionRunResponse)
async def run_mission_endpoint(request: MissionRunRequest) -> MissionRunResponse:
    model_path = get_default_model_path()
    if not model_path.exists():
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Base MuJoCo model not found at {model_path}",
        )

    world = get_world(request.world_id)

    mission = request.mission
    if mission is None:
        if request.world_id == "precision-landing":
            stages = [
                MissionStage(
                    id="approach",
                    kind=MissionStageKind.WAYPOINT,
                    target_position_m=[0.10, 0.0, 0.08],
                    tolerance_m=0.06,
                    dwell_s=0.02,
                    completion_deadline_s=0.20,
                ),
                MissionStage(
                    id="touchdown",
                    kind=MissionStageKind.LANDING,
                    target_position_m=[0.10, 0.0, 0.02],
                    tolerance_m=0.08,
                    dwell_s=0.02,
                    completion_deadline_s=1.00,
                ),
            ]
            constraints = MissionConstraints(
                min_altitude_m=0.01,
                max_landing_impact_speed_mps=1.0,
                fail_on_unpermitted_contact=True,
            )
            init_pos = request.initial_pos_m or [0.10, 0.0, 0.10]
        else:
            stages = [
                MissionStage(
                    id="takeoff",
                    kind=MissionStageKind.TAKEOFF,
                    target_position_m=[0.0, 0.0, 0.20],
                    tolerance_m=0.06,
                    dwell_s=0.02,
                    completion_deadline_s=0.25,
                ),
                MissionStage(
                    id="slalom_waypoint",
                    kind=MissionStageKind.WAYPOINT,
                    target_position_m=[0.10, -0.05, 0.22],
                    tolerance_m=0.08,
                    dwell_s=0.02,
                    completion_deadline_s=0.60,
                ),
                MissionStage(
                    id="terminal_approach",
                    kind=MissionStageKind.WAYPOINT,
                    target_position_m=[0.15, 0.0, 0.15],
                    tolerance_m=0.08,
                    dwell_s=0.02,
                    completion_deadline_s=0.90,
                ),
            ]
            constraints = MissionConstraints(
                min_altitude_m=0.02,
                max_altitude_m=1.00,
                max_tilt_deg=55.0,
                fail_on_unpermitted_contact=True,
            )
            init_pos = request.initial_pos_m or [0.0, 0.0, 0.05]

        mission = MissionSpecV2(
            mission_id=f"mission-{request.world_id}",
            world_id=request.world_id,
            stages=stages,
            constraints=constraints,
        )
    else:
        init_pos = request.initial_pos_m or [0.0, 0.0, 0.05]

    if request.controller_source is not None:
        if not is_microvm_available():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Untrusted controller code execution is disabled when hardware microVM isolation is unavailable.",
            )
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Custom controller source for 3D multi-mission execution requires microVM integration.",
        )

    ctrl = Baseline3DController()
    res = run_mission_simulation(
        model_path,
        mission,
        world,
        lambda obs: ctrl.compute_action(obs),
        faults=request.faults,
        initial_pos_m=init_pos,
    )

    stride = max(1, len(res.trajectory) // 250)
    sampled_traj = res.trajectory[::stride]

    contacts_data = [
        {
            "step_index": c.step_index,
            "sim_time_s": c.sim_time_s,
            "geom1": c.geom1,
            "geom2": c.geom2,
            "contact_class": c.contact_class,
            "impact_velocity_mps": c.impact_velocity_mps,
            "position_m": c.position_m,
        }
        for c in res.contacts
    ]

    return MissionRunResponse(
        mission_id=mission.mission_id,
        world_id=world.world_id,
        physical_verdict=res.evaluation.physical_verdict,
        mission_verdict=res.evaluation.mission_verdict,
        min_robustness=res.evaluation.min_robustness,
        critical_predicate=res.evaluation.critical_predicate,
        critical_timestamp_s=res.evaluation.critical_timestamp_s,
        replay_matched=res.replay_matched,
        replay_max_abs_diff=res.replay_max_abs_diff,
        summary=res.evaluation.summary,
        trajectory=sampled_traj,
        contacts=contacts_data,
        stage_results=res.evaluation.stage_results,
    )


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


