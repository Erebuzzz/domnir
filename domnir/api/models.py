"""Pydantic schemas and state definitions for Dómnir API."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator

from domnir.spec import FlightSpec, GeneratedController
from domnir.missions.schema import MissionSpecV2
from domnir.faults.schema import MissionFaultSchedule


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
    # Server-side record of this generation. Pass it as
    # controller_artifact_id to /missions/run to get server-confirmed provenance.
    artifact_id: str | None = None
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
    # "hover" for legacy experiment records, "mission" for 3D mission records.
    record_type: str = "hover"
    # Mission records: individual check results (e.g. world_hash, verdicts).
    checks: dict[str, bool] = Field(default_factory=dict)
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


class RagnarokArenaRequest(BaseModel):
    spec: FlightSpec = Field(default_factory=FlightSpec)
    controller_source: str = Field(min_length=1, max_length=32768)
    max_rounds: int = Field(default=2, ge=1, le=3)
    search_budget_per_round: int = Field(default=12, ge=4, le=24)
    max_repair_revisions: int = Field(default=2, ge=1, le=3)


class RagnarokArenaResponse(BaseModel):
    campaign_id: str
    target_altitude_m: float
    total_rounds_executed: int
    initial_controller_sha256: str
    final_controller_sha256: str | None = None
    final_controller_source: str | None = None
    rounds: list[dict[str, Any]] = Field(default_factory=list)
    accumulated_regression_suite_size: int = 0
    summary: str
    limitation_note: str = (
        "Passing a finite collection of test scenarios does not constitute a formal proof of universal flight safety."
    )


class MissionRunRequest(BaseModel):
    mission: MissionSpecV2 | None = None
    world_id: str = "ragnarok-gauntlet"
    controller_type: str = "baseline_3d"
    controller_source: str | None = None
    # Client-reported model label. Only used when no server artifact matches.
    model_id: str | None = None
    # artifact_id returned by /controllers/generate; resolved server-side.
    controller_artifact_id: str | None = Field(default=None, max_length=64)
    provenance: dict[str, Any] | None = None
    faults: MissionFaultSchedule | None = None
    initial_pos_m: list[float] | None = None


class MissionRunResponse(BaseModel):
    mission_id: str
    world_id: str
    controller_type: str = "baseline_3d"
    controller_hash: str | None = None
    model_id: str | None = None
    execution_backend: str = "host_trusted_kernel"
    physical_verdict: str
    mission_verdict: str
    min_robustness: float
    critical_predicate: str
    critical_timestamp_s: float
    replay_matched: bool
    replay_max_abs_diff: float
    replay_tolerance: float = 1e-12
    summary: str
    trajectory: list[dict[str, Any]] = Field(default_factory=list)
    trajectory_samples_total: int = 0
    contacts: list[dict[str, Any]] = Field(default_factory=list)
    contacts_total: int = 0
    # Totals per contact class over the full (uncapped) contact list.
    contacts_by_class: dict[str, int] = Field(default_factory=dict)
    stage_results: list[dict[str, Any]] = Field(default_factory=list)
    stages_completed: int = 0
    total_stages: int = 0
    mission_failure_reason: str | None = None
    # Isolation: "NOT_APPLICABLE" for the trusted built-in baseline (no guest
    # code runs), "MICROVM" for hardware isolation, "UNISOLATED" for the
    # development subprocess fallback.
    isolation_status: str = "NOT_APPLICABLE"
    # Teardown observed for this run: NOT_APPLICABLE (no guest), SUCCEEDED,
    # FAILED, or UNKNOWN.
    cleanup_status: str = "NOT_APPLICABLE"
    # BUILT_IN_BASELINE, SERVER_CONFIRMED_GENERATION, USER_MODIFIED or
    # UNVERIFIED_ORIGIN (see domnir/provenance.py). model_id_source says
    # whether model_id came from the server artifact or the client.
    provenance_status: str = "BUILT_IN_BASELINE"
    model_id_source: str = "server"
    controller_artifact_id: str | None = None
    controller_exchanges: int = 0
    controller_invocations: int = 0
    controller_period_steps: int = 1
    effective_controller_hz: float = 500.0
    wall_time_s: float = 0.0
    # The mission actually flown (defaults expanded) and its planned
    # reference path, for mission-aware charts and the 3D overlay.
    mission: dict[str, Any] | None = None
    reference_path: list[dict[str, Any]] = Field(default_factory=list)
    court_record_id: str | None = None
    court_record_url: str | None = None
    limitation_note: str = (
        "Passing a finite collection of test scenarios does not constitute a formal proof of universal flight safety."
    )



