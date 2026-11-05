"""FastAPI application for Dómnir adversarial qualification platform."""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
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
    ReadyResponse,
    RunExperimentRequest,
    SpecValidationRequest,
    SpecValidationResponse,
)
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

    is_ready = bool(model_loaded and inference_configured)

    return ReadyResponse(
        ready=is_ready,
        model_loaded=model_loaded,
        inference_configured=inference_configured,
        microvm_available=microvm_available,
        supported_models=list(SUPPORTED_MODELS.keys()),
        details={
            "model_path": str(model_path),
            "backend": "microvm" if microvm_available else "trusted_simulator",
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
            max_tokens=request.max_tokens,
        )
        return GenerateControllerResponse(
            controller=controller,
            model_id=controller.model_id,
            source_sha256=controller.source_sha256,
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
def run_containment_endpoint() -> ContainmentStatusResponse:
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


WEB_DIR = Path(__file__).resolve().parents[1] / "web"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


