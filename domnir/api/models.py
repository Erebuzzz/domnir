"""Pydantic schemas and state definitions for Dómnir API."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator

from domnir.spec import FlightSpec, GeneratedController


class ExperimentState(str, Enum):
    CREATED = "CREATED"
    SPEC_APPROVED = "SPEC_APPROVED"
    CONTROLLER_VALIDATED = "CONTROLLER_VALIDATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ModelInfo(BaseModel):
    id: str
    name: str
    family: str
    provider: str = "vultr"
    description: str
    default: bool = False
    reasoning_effort: str | None = "minimal"


class ModelsResponse(BaseModel):
    models: list[ModelInfo]
    default_model: str


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "domnir-api"
    version: str = "0.1.0"
    timestamp: str


class ReadyResponse(BaseModel):
    ready: bool
    status: str = "ready"
    http_health: bool = True
    model_loaded: bool
    inference_configured: bool
    live_inference_verified: bool = False
    microvm_available: bool
    execution_permitted: bool = False
    supported_models: list[str]
    details: dict[str, Any] = Field(default_factory=dict)


class SpecValidationRequest(BaseModel):
    spec: FlightSpec


class SpecValidationResponse(BaseModel):
    valid: bool
    spec: FlightSpec
    step_budget: int
    message: str = "Specification valid"


class GenerateControllerRequest(BaseModel):
    spec: FlightSpec
    model: str = "glm-5.3-flash"
    prompt_version: str = "v1"
    max_tokens: int = 4096
    reasoning_effort: str = Field(default="minimal", pattern="^(minimal|low|medium|high)$")


class GenerateControllerResponse(BaseModel):
    controller: GeneratedController
    model_id: str
    source_sha256: str
    reasoning_effort: str = "minimal"
    message: str = "Controller generated successfully"


class RunExperimentRequest(BaseModel):
    spec: FlightSpec
    controller: GeneratedController | None = None
    controller_source: str | None = None
    model: str | None = None
    reasoning_effort: str | None = Field(default=None, pattern="^(minimal|low|medium|high)$")
    steps: int | None = Field(default=None, ge=1, le=5000)
    initial_altitude_m: float = Field(default=0.15, ge=0.01, le=5.0)
    vertical_disturbance_n: float = Field(default=0.0, ge=-1.0, le=1.0)
    pulse_start_s: float = Field(default=0.0, ge=0.0, le=10.0)
    pulse_duration_s: float = Field(default=0.0, ge=0.0, le=10.0)
    seed: int = Field(default=42, ge=0)
    run_async: bool = False

    @field_validator("controller_source")
    @classmethod
    def validate_source_size(cls, v: str | None) -> str | None:
        if v is not None and len(v.encode("utf-8")) > 32768:
            raise ValueError("Controller source code cannot exceed 32 KiB (32768 bytes)")
        return v


class StateTransitionRecord(BaseModel):
    from_state: ExperimentState | None
    to_state: ExperimentState
    timestamp: str
    reason: str | None = None


class ExperimentSummary(BaseModel):
    id: str
    state: ExperimentState
    created_at: str
    updated_at: str
    spec: FlightSpec
    controller_sha256: str | None = None
    model_id: str | None = None
    verdict: str | None = None
    execution_backend: str = "trusted_simulator"
    steps_completed: int = 0
    final_altitude_m: float | None = None
    minimum_altitude_m: float | None = None
    maximum_altitude_m: float | None = None
    altitude_error_m: float | None = None
    replay_max_abs_difference: float | None = None
    replay_matched: bool | None = None
    error_message: str | None = None
    cleanup_succeeded: bool = True


class ExperimentDetailResponse(ExperimentSummary):
    state_history: list[StateTransitionRecord] = Field(default_factory=list)
    telemetry_sample_count: int = 0
    artifacts_available: list[str] = Field(default_factory=list)


class ArtifactsResponse(BaseModel):
    experiment_id: str
    state: ExperimentState
    court_record: dict[str, Any] | None = None
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
    event_log: list[dict[str, Any]] = Field(default_factory=list)


class CourtRecordVerifyRequest(BaseModel):
    court_record: dict[str, Any] | None = None
    model_config = {"extra": "allow"}


class CourtRecordVerifyResponse(BaseModel):
    verified: bool
    replay_verdict: str
    replay_max_abs_difference: float
    tolerance: float
    controller_hash_matched: bool
    trajectory_hash_matched: bool
    model_hashes_matched: bool
    event_chain_verified: bool
    record_id: str | None = None
    experiment_id: str | None = None
    errors: list[str] = Field(default_factory=list)
    timestamp: str


class ContainmentFixtureResult(BaseModel):
    fixture_id: str
    name: str
    status: str
    evidence_source: str
    policy_id: str | None = None
    policy: dict[str, Any] | None = None
    request_id: str | None = None
    elapsed_seconds: float | None = None
    observation: dict[str, Any] | None = None
    termination_cause: str | None = None
    per_attempt_host_observation: str | None = None
    guest_diagnostic: dict[str, Any] | None = None
    cleanup_succeeded: bool = True
    model_config = {"extra": "allow"}


class ContainmentHostEventLog(BaseModel):
    file: str
    sha256_head: str
    event_count: int
    verified: bool


class ContainmentStatusResponse(BaseModel):
    schema_version: str = "containment-feasibility-1"
    status: str
    microvm_available: bool
    cleanup_guarantee: str
    fixtures: list[ContainmentFixtureResult]
    host_event_log: ContainmentHostEventLog
    limitations: list[str] = Field(default_factory=list)
    execution_source: str
    timestamp: str


class RagnarokFalsifyRequest(BaseModel):
    spec: FlightSpec = Field(default_factory=FlightSpec)
    controller_source: str
    budget: int = Field(default=12, ge=2, le=30)
    strategy: str = Field(default="differential_evolution", pattern="^(differential_evolution|sobol|compare)$")
    seed: int = Field(default=42, ge=0)


class RagnarokFalsifyResponse(BaseModel):
    strategy: str
    evaluations_count: int
    first_violation_iteration: int | None
    violations_found: int
    min_robustness: float
    best_scenario: dict[str, Any]
    critical_witness: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    comparison: dict[str, Any] | None = None
    summary: str


class RagnarokMinimizeRequest(BaseModel):
    spec: FlightSpec = Field(default_factory=FlightSpec)
    controller_source: str
    witness_scenario: dict[str, Any]
    max_evaluations: int = Field(default=12, ge=2, le=25)


class RagnarokMinimizeResponse(BaseModel):
    original_scenario: dict[str, Any]
    minimized_scenario: dict[str, Any]
    original_robustness: float
    minimized_robustness: float
    original_cost: float
    minimized_cost: float
    cost_reduction_ratio: float
    evaluations_used: int
    predicate_preserved: bool
    summary: str


class RagnarokRepairRequest(BaseModel):
    spec: FlightSpec = Field(default_factory=FlightSpec)
    controller_source: str
    witness_scenario: dict[str, Any]
    model: str | None = None
    reasoning_effort: str | None = None
    max_revisions: int = Field(default=2, ge=1, le=3)


class RagnarokRepairResponse(BaseModel):
    outcome: str
    repaired_controller_source: str | None = None
    repaired_source_sha256: str | None = None
    total_revisions_attempted: int
    history: list[dict[str, Any]] = Field(default_factory=list)
    summary: str


