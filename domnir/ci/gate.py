"""Robotics Continuous Integration (CI) and Revision Regression Gate."""

from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence, Self

import mujoco
import numpy as np
from pydantic import BaseModel, Field, model_validator

from domnir.contracts.stl import SafetyContract, STLMonitor, STLRobustnessResult
from domnir.court_record import canonical_json
from domnir.ragnarok.repair import HoldoutSuite
from domnir.scenario import ScenarioParameter, calculate_applied_disturbance
from domnir.spec import GeneratedController
from domnir.uncertainty.simulator import resolve_model_path


class ReleaseStatus(str, Enum):
    RELEASE_APPROVED = "RELEASE_APPROVED"
    REGRESSION_FOUND = "REGRESSION_FOUND"
    BLOCKED_INCOMPLETE = "BLOCKED_INCOMPLETE"
    AWAITING_REVIEW = "AWAITING_REVIEW"


class ReleaseAssessment(BaseModel):
    status: ReleaseStatus
    candidate_version: str
    baseline_version: str
    contracts_evaluated: int
    contracts_passed: int
    regressions_count: int
    new_failures: list[str] = Field(default_factory=list)
    resolved_failures: list[str] = Field(default_factory=list)
    nominal_tracking_error_m: float = 0.0
    min_robustness_margin: float = 0.0
    court_record_hashes: list[str] = Field(default_factory=list)
    summary: str = ""
    candidate_pass_rate: float = 0.0
    created_at_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @model_validator(mode="after")
    def guard_prohibited_safety_claims(self) -> Self:
        prohibited = ("SAFE", "PROVEN_SAFE", "PROVEN SAFE", "FULLY SAFE")
        if self.status.value in ("SAFE", "PROVEN_SAFE"):
            raise ValueError(
                "Strict safety rule: unqualified SAFE or PROVEN_SAFE release status is strictly prohibited."
            )
        sum_upper = self.summary.upper()
        for phrase in ("PROVEN SAFE", "PROVEN_SAFE", "FULLY SAFE", "UNCONDITIONALLY SAFE"):
            if phrase in sum_upper:
                raise ValueError(
                    f"Summary contains prohibited unqualified safety claim: {phrase}"
                )
        return self


class RoboticsCIGate:
    """Robotics CI Gate evaluating candidate controllers against baseline revisions."""

    def __init__(
        self,
        *,
        model_path: Path | str | None = None,
        evaluator: Callable[[Any, ScenarioParameter, SafetyContract], STLRobustnessResult] | None = None,
        min_pass_rate_for_approval: float = 0.80,
    ) -> None:
        self.model_path = model_path
        self.custom_evaluator = evaluator
        self.min_pass_rate_for_approval = min_pass_rate_for_approval

    def _extract_version(self, ctrl: Any, default: str) -> str:
        if isinstance(ctrl, GeneratedController):
            return ctrl.source_sha256[:12]
        if hasattr(ctrl, "source_sha256"):
            return str(ctrl.source_sha256)[:12]
        if hasattr(ctrl, "model_id") and ctrl.model_id:
            return str(ctrl.model_id)
        if isinstance(ctrl, str):
            return hashlib.sha256(ctrl.encode("utf-8")).hexdigest()[:12]
        return default

    def _default_simulate_and_evaluate(
        self,
        ctrl: Any,
        scenario: ScenarioParameter,
        contract: SafetyContract,
    ) -> tuple[STLRobustnessResult, float, str]:
        resolved_path = resolve_model_path(self.model_path)
        if not resolved_path or not resolved_path.is_file():
            raise FileNotFoundError(f"MuJoCo model file not found: {resolved_path}")

        observe_fn: Callable[[dict[str, Any]], Any]
        if isinstance(ctrl, (GeneratedController, str)):
            source_code = ctrl.source_code if isinstance(ctrl, GeneratedController) else ctrl
            from domnir.evaluator import SafeControllerEvaluator
            if not SafeControllerEvaluator.is_execution_available():
                invalid_res = STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=0.0,
                    critical_step_index=0,
                    critical_predicate="execution_unavailable",
                    critical_actual_value=0.0,
                    critical_threshold=0.0,
                    summary="MicroVM sandbox required to evaluate untrusted controller in CI gate",
                    timeline=[],
                    is_valid=False,
                )
                return invalid_res, 0.0, ""
            exec_res = SafeControllerEvaluator.execute(
                source_code,
                model_path=resolved_path,
                contract=contract,
                scenario=scenario,
            )
            if exec_res.status != "SUCCESS":
                invalid_res = STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=0.0,
                    critical_step_index=0,
                    critical_predicate="execution_error",
                    critical_actual_value=0.0,
                    critical_threshold=0.0,
                    summary=f"CI execution error: {exec_res.error_message}",
                    timeline=[],
                    is_valid=False,
                )
                return invalid_res, 0.0, ""
            robustness_result = STLMonitor.evaluate_trajectory(contract, exec_res.trajectory)
            tracking_errors = [
                abs(f.get("altitude_error_m", 0.0))
                for f in exec_res.trajectory
                if f.get("sim_time_s", 0.0) >= contract.settling_time_s
            ]
            mean_tracking_err = (
                float(np.mean(tracking_errors)) if tracking_errors else 0.0
            )
            record_hash = hashlib.sha256(canonical_json(exec_res.trajectory)).hexdigest()
            return robustness_result, mean_tracking_err, record_hash
        elif hasattr(ctrl, "observe") and callable(ctrl.observe):
            observe_fn = ctrl.observe
        elif callable(ctrl):
            observe_fn = ctrl
        else:
            raise ValueError(f"Controller must be callable or define observe: {type(ctrl)}")

        model = mujoco.MjModel.from_xml_path(str(resolved_path))
        body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
        data = mujoco.MjData(model)
        data.qpos[2] = float(scenario.initial_altitude_m)
        mujoco.mj_forward(model, data)

        steps = contract.physics_steps
        decimation = contract.decimation
        dt = contract.physics_dt_s
        target_z = contract.target_altitude_m
        disturbance = float(scenario.disturbance_force_z)

        trajectory: list[dict[str, Any]] = []
        tracking_errors: list[float] = []
        current_action = np.zeros(4, dtype=np.float64)

        for step_idx in range(steps):
            sim_time = step_idx * dt

            if step_idx % decimation == 0:
                obs = {
                    "schema_version": "1.0",
                    "trial_id": "ci_eval",
                    "step_index": step_idx,
                    "sim_time_s": sim_time,
                    "dt_s": dt * decimation,
                    "position_m": data.qpos[:3].tolist(),
                    "velocity_mps": data.qvel[:3].tolist(),
                    "orientation_quat_wxyz": data.qpos[3:7].tolist(),
                    "body_angular_velocity_rps": data.qvel[3:6].tolist(),
                    "target_position_m": [0.0, 0.0, target_z],
                    "target_altitude_m": target_z,
                }
                raw_act = observe_fn(obs)
                if isinstance(raw_act, dict):
                    current_action = np.array([
                        float(raw_act.get("thrust", 0.0)),
                        float(raw_act.get("moment_x", 0.0)),
                        float(raw_act.get("moment_y", 0.0)),
                        float(raw_act.get("moment_z", 0.0)),
                    ], dtype=np.float64)
                elif isinstance(raw_act, (list, tuple, np.ndarray)):
                    current_action = np.array(raw_act[:4], dtype=np.float64)

            data.ctrl[:] = current_action
            dist_force = calculate_applied_disturbance(scenario, sim_time)
            if body_id >= 0:
                data.xfrc_applied[body_id, 2] = dist_force

            mujoco.mj_step(model, data)

            point = {
                "step_index": step_idx,
                "sim_time_s": sim_time,
                "position_m": data.qpos[:3].tolist(),
                "velocity_mps": data.qvel[:3].tolist(),
                "orientation_quat_wxyz": data.qpos[3:7].tolist(),
            }
            trajectory.append(point)

            if sim_time >= contract.settling_time_s:
                tracking_errors.append(abs(data.qpos[2] - target_z))

        robustness_result = STLMonitor.evaluate_trajectory(contract, trajectory)
        mean_tracking_err = (
            float(np.mean(tracking_errors)) if tracking_errors else abs(data.qpos[2] - target_z)
        )
        record_hash = hashlib.sha256(canonical_json(trajectory)).hexdigest()
        return robustness_result, mean_tracking_err, record_hash

    def evaluate_revision(
        self,
        candidate_ctrl: Any,
        baseline_ctrl: Any,
        contract: SafetyContract | None = None,
        suite: Sequence[ScenarioParameter] | None = None,
    ) -> ReleaseAssessment:
        if contract is None:
            contract = SafetyContract()

        if suite is None:
            suite = HoldoutSuite.generate_suite(target_altitude_m=contract.target_altitude_m)

        cand_ver = self._extract_version(candidate_ctrl, "candidate_rev")
        base_ver = self._extract_version(baseline_ctrl, "baseline_rev")

        if not suite or len(suite) == 0:
            return ReleaseAssessment(
                status=ReleaseStatus.BLOCKED_INCOMPLETE,
                candidate_version=cand_ver,
                baseline_version=base_ver,
                contracts_evaluated=0,
                contracts_passed=0,
                regressions_count=0,
                new_failures=[],
                resolved_failures=[],
                nominal_tracking_error_m=0.0,
                min_robustness_margin=0.0,
                court_record_hashes=[],
                summary="Evaluation blocked: Scenario suite is empty. No evaluations could be performed.",
                candidate_pass_rate=0.0,
            )

        new_failures: list[str] = []
        resolved_failures: list[str] = []
        court_record_hashes: list[str] = []
        candidate_passed_count = 0
        min_margin = float("inf")
        nominal_tracking_err = 0.0
        regressions_count = 0
        incomplete_errors: list[str] = []

        for idx, scenario in enumerate(suite):
            scenario_name = f"scenario_{idx}_z{scenario.initial_altitude_m:.3f}_f{scenario.disturbance_force_z:+.3f}"

            cand_res: STLRobustnessResult
            cand_err: float = 0.0
            cand_hash: str = ""
            try:
                if self.custom_evaluator is not None:
                    try:
                        cand_res = self.custom_evaluator(candidate_ctrl, scenario, contract)
                    except TypeError:
                        cand_res = self.custom_evaluator(candidate_ctrl, scenario)
                    cand_err = 0.0
                    cand_hash = hashlib.sha256(f"cand_{scenario_name}_{cand_res.min_robustness}".encode()).hexdigest()
                else:
                    cand_res, cand_err, cand_hash = self._default_simulate_and_evaluate(
                        candidate_ctrl, scenario, contract
                    )
            except Exception as e:
                incomplete_errors.append(f"Candidate execution failed on {scenario_name}: {e}")
                cand_res = STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=0.0,
                    critical_step_index=0,
                    critical_predicate="execution_error",
                    critical_actual_value=0.0,
                    critical_threshold=0.0,
                    summary=str(e),
                    timeline=[],
                    is_valid=False,
                )
                cand_hash = hashlib.sha256(f"error_{scenario_name}".encode()).hexdigest()

            court_record_hashes.append(cand_hash)

            base_res: STLRobustnessResult
            try:
                if self.custom_evaluator is not None:
                    try:
                        base_res = self.custom_evaluator(baseline_ctrl, scenario, contract)
                    except TypeError:
                        base_res = self.custom_evaluator(baseline_ctrl, scenario)
                else:
                    base_res, _, _ = self._default_simulate_and_evaluate(
                        baseline_ctrl, scenario, contract
                    )
            except Exception as e:
                incomplete_errors.append(f"Baseline execution failed on {scenario_name}: {e}")
                base_res = STLRobustnessResult(
                    satisfied=False,
                    verdict="INVALID",
                    min_robustness=0.0,
                    critical_timestamp_s=0.0,
                    critical_step_index=0,
                    critical_predicate="execution_error",
                    critical_actual_value=0.0,
                    critical_threshold=0.0,
                    summary=str(e),
                    timeline=[],
                    is_valid=False,
                )

            if cand_res.satisfied:
                candidate_passed_count += 1
            if cand_res.min_robustness < min_margin:
                min_margin = cand_res.min_robustness

            if scenario.disturbance_force_z == 0.0 and abs(scenario.initial_altitude_m - contract.target_altitude_m) < 1e-4:
                nominal_tracking_err = cand_err
            elif nominal_tracking_err == 0.0 and cand_err > 0.0:
                nominal_tracking_err = cand_err

            if base_res.satisfied and not cand_res.satisfied:
                new_failures.append(scenario_name)
                regressions_count += 1
            elif not base_res.satisfied and cand_res.satisfied:
                resolved_failures.append(scenario_name)

        total_scenarios = len(suite)
        pass_rate = candidate_passed_count / total_scenarios if total_scenarios > 0 else 0.0
        if math.isinf(min_margin):
            min_margin = 0.0

        if incomplete_errors:
            status = ReleaseStatus.BLOCKED_INCOMPLETE
            summary = (
                f"Release blocked (incomplete): {len(incomplete_errors)} scenario(s) failed with runtime errors. "
                f"First error: {incomplete_errors[0]}."
            )
        elif regressions_count > 0:
            status = ReleaseStatus.REGRESSION_FOUND
            summary = (
                f"Release blocked (regression found): Candidate revision {cand_ver} failed on {regressions_count} scenario(s) "
                f"where baseline {base_ver} previously passed. Regressions: {', '.join(new_failures)}."
            )
        elif pass_rate >= self.min_pass_rate_for_approval:
            status = ReleaseStatus.RELEASE_APPROVED
            summary = (
                f"Release approved: Candidate revision {cand_ver} achieved {pass_rate:.1%} pass rate "
                f"({candidate_passed_count}/{total_scenarios}) with 0 regressions against baseline {base_ver}. "
                f"Min robustness margin: {min_margin:+.4f}, nominal tracking error: {nominal_tracking_err:.4f} m."
            )
        else:
            status = ReleaseStatus.AWAITING_REVIEW
            summary = (
                f"Release awaiting review: Candidate revision {cand_ver} has 0 regressions but pass rate "
                f"{pass_rate:.1%} is below approval threshold ({self.min_pass_rate_for_approval:.1%}). "
                f"Passed {candidate_passed_count}/{total_scenarios} scenarios."
            )

        return ReleaseAssessment(
            status=status,
            candidate_version=cand_ver,
            baseline_version=base_ver,
            contracts_evaluated=total_scenarios,
            contracts_passed=candidate_passed_count,
            regressions_count=regressions_count,
            new_failures=new_failures,
            resolved_failures=resolved_failures,
            nominal_tracking_error_m=float(nominal_tracking_err),
            min_robustness_margin=float(min_margin),
            court_record_hashes=court_record_hashes,
            summary=summary,
            candidate_pass_rate=float(pass_rate),
        )
