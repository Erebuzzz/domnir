"""Court Record generation and independent replay verification for Dómnir."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from domnir.replay import (
    INTEGRATION_SIGNATURE,
    capture_integration_state,
    model_hashes,
    restore_integration_state,
)
from domnir.sandbox import RUNTIME_VERSION
from domnir.spec import FlightSpec

SCHEMA_VERSION = "domnir-court-record-v1"
REPLAY_TOLERANCE = 1e-12
GENESIS_HASH = "0" * 64

MANDATORY_LIMITATIONS = [
    "Actuator dynamics and model limits are uncalibrated research assumptions.",
    "Synthetic hover falsification does not prove real-world hardware safety.",
    "Deterministic replay proves MuJoCo trajectory reproducibility under recorded actions, not physical validity.",
    "Finite adversarial search does not prove universal safety.",
]
LIMITATIONS = MANDATORY_LIMITATIONS


def canonical_json(value: Any) -> bytes:
    def _default(obj: Any) -> Any:
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_default,
    ).encode("utf-8")


def compute_trajectory_hash(
    steps: int,
    timestamps: list[float] | np.ndarray,
    position_m: list[list[float]] | np.ndarray,
    velocity_mps: list[list[float]] | np.ndarray,
    actions: list[list[float]] | np.ndarray,
    integration_states: list[list[float]] | np.ndarray,
) -> str:
    def _to_list(val: Any) -> Any:
        return val.tolist() if isinstance(val, np.ndarray) else val

    payload = {
        "actions": _to_list(actions),
        "integration_states": _to_list(integration_states),
        "position_m": _to_list(position_m),
        "steps": int(steps),
        "timestamps": _to_list(timestamps),
        "velocity_mps": _to_list(velocity_mps),
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def chain_events(raw_events: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    chained: list[dict[str, Any]] = []
    previous_hash = GENESIS_HASH

    for index, raw in enumerate(raw_events):
        event_copy = dict(raw)
        timestamp = (
            event_copy.get("timestamp_utc")
            or event_copy.get("timestamp")
            or datetime.now(timezone.utc).isoformat()
        )
        source = event_copy.get("source", "trusted_host")
        event_type = event_copy.get("event_type", "event")

        if "details" in event_copy and isinstance(event_copy["details"], dict):
            details = dict(event_copy["details"])
        else:
            skip_keys = {
                "sequence",
                "timestamp",
                "timestamp_utc",
                "source",
                "event_type",
                "previous_sha256",
                "sha256",
            }
            details = {k: v for k, v in event_copy.items() if k not in skip_keys}

        entry: dict[str, Any] = {
            "sequence": index,
            "timestamp_utc": timestamp,
            "source": source,
            "event_type": event_type,
            "details": details,
            "previous_sha256": previous_hash,
        }

        entry_digest = hashlib.sha256(canonical_json(entry)).hexdigest()
        entry["sha256"] = entry_digest
        chained.append(entry)
        previous_hash = entry_digest

    return chained, previous_hash


def verify_event_chain(
    events: list[dict[str, Any]],
    *,
    expected_head: str | None = None,
    expected_count: int | None = None,
) -> tuple[bool, str]:
    if expected_count is not None and len(events) != expected_count:
        return False, f"Event count mismatch: expected {expected_count}, got {len(events)}"

    previous = GENESIS_HASH
    for index, item in enumerate(events):
        if not isinstance(item, dict):
            return False, f"Event at index {index} is not a dictionary"

        if item.get("sequence") != index:
            return False, f"Event sequence mismatch at index {index}: expected {index}, got {item.get('sequence')}"

        if item.get("previous_sha256") != previous:
            return False, f"Previous hash mismatch at index {index}"

        recorded_sha = item.get("sha256")
        if not recorded_sha:
            return False, f"Missing sha256 at index {index}"

        copy_item = {k: v for k, v in item.items() if k != "sha256"}
        computed_sha = hashlib.sha256(canonical_json(copy_item)).hexdigest()
        if computed_sha != recorded_sha:
            return False, f"Event digest mismatch at index {index}"

        previous = recorded_sha

    if expected_head is not None and previous != expected_head:
        return False, f"Head hash mismatch: expected {expected_head}, got {previous}"

    return True, "Chain integrity verified"


def build_court_record(
    *,
    experiment_id: str,
    spec: dict[str, Any] | FlightSpec,
    scenario_seed: int,
    initial_altitude_m: float,
    vertical_disturbance_n: float,
    steps: int,
    timestep_s: float,
    controller_source: str,
    controller_model_id: str | None,
    prompt_metadata: dict[str, Any] | None = None,
    model_path: Path,
    model_file_hashes: dict[str, str] | None = None,
    timestamps: list[float],
    position_m: list[list[float]],
    velocity_mps: list[list[float]],
    actions: list[list[float]],
    integration_states: list[list[float]],
    replay_max_abs_diff: float,
    replay_matched: bool,
    flight_verdict: str,
    verdict_reason: str,
    execution_backend: str = "trusted_simulator",
    cleanup_succeeded: bool = True,
    containment_checked: bool = False,
    raw_events: list[dict[str, Any]] | None = None,
    record_id: str | None = None,
) -> dict[str, Any]:
    spec_dict = spec.model_dump() if isinstance(spec, FlightSpec) else dict(spec)

    chained_events, head_sha256 = chain_events(raw_events or [])
    chain_ok, _ = verify_event_chain(
        chained_events,
        expected_head=head_sha256,
        expected_count=len(chained_events),
    )

    trajectory_sha = compute_trajectory_hash(
        steps=steps,
        timestamps=timestamps,
        position_m=position_m,
        velocity_mps=velocity_mps,
        actions=actions,
        integration_states=integration_states,
    )

    hashes = model_file_hashes or model_hashes(model_path)
    source_sha = hashlib.sha256(controller_source.encode("utf-8")).hexdigest()

    rec_id = record_id or f"cr-{uuid.uuid4().hex[:16]}"
    now_utc = datetime.now(timezone.utc).isoformat()

    replay_verdict = (
        "MATCHED"
        if replay_matched
        else ("DIVERGED" if replay_max_abs_diff > REPLAY_TOLERANCE else "INVALID")
    )

    if execution_backend == "microvm":
        containment_status = "POLICY_CONFIRMED" if containment_checked else "PARTIAL"
    elif execution_backend in ("trusted_simulator", "subprocess", "subprocess_dev_unisolated"):
        containment_status = "PARTIAL"
    else:
        containment_status = "NOT_TESTED"

    cleanup_status = "SUCCEEDED" if cleanup_succeeded else "FAILED"
    provenance_status = "VERIFIED" if chain_ok else "INCOMPLETE"

    final_alt = position_m[-1][2] if position_m else initial_altitude_m
    all_alt = [p[2] for p in position_m] if position_m else [initial_altitude_m]
    target_alt = float(spec_dict.get("target_altitude_m", 0.1))

    return {
        "schema_version": SCHEMA_VERSION,
        "record_id": rec_id,
        "experiment_id": experiment_id,
        "created_at": now_utc,
        "verdict": flight_verdict,
        "verdict_reason": verdict_reason,
        "execution_backend": execution_backend,
        "spec": spec_dict,
        "scenario": {
            "seed": scenario_seed,
            "initial_altitude_m": initial_altitude_m,
            "vertical_disturbance_n": vertical_disturbance_n,
            "steps": steps,
            "timestep_s": timestep_s,
            "duration_s": float(round(steps * timestep_s, 6)),
        },
        "controller": {
            "source_code": controller_source,
            "source_sha256": source_sha,
            "model_id": controller_model_id,
            "prompt_metadata": prompt_metadata or {"prompt_version": "v1"},
        },
        "simulator": {
            "engine": "mujoco",
            "mujoco_version": mujoco.__version__,
            "runtime_version": RUNTIME_VERSION,
            "platform": platform.platform(),
            "model_path": model_path.name,
            "model_hashes_sha256": hashes,
            "integration_signature": INTEGRATION_SIGNATURE,
        },
        "trajectory": {
            "steps": steps,
            "timestamps": timestamps,
            "position_m": position_m,
            "velocity_mps": velocity_mps,
            "actions": actions,
            "integration_states": integration_states,
            "trajectory_sha256": trajectory_sha,
        },
        "replay": {
            "tolerance": REPLAY_TOLERANCE,
            "max_abs_difference": replay_max_abs_diff,
            "verdict": replay_verdict,
        },
        "event_log": {
            "events": chained_events,
            "event_count": len(chained_events),
            "head_sha256": head_sha256,
            "chain_integrity": "VERIFIED" if chain_ok else "BROKEN",
        },
        "verdicts": {
            "flight_verdict": flight_verdict,
            "flight_qualification": "INCONCLUSIVE",
            "containment_status": containment_status,
            "provenance_status": provenance_status,
            "cleanup_status": cleanup_status,
        },
        "summary_metrics": {
            "steps": steps,
            "final_altitude_m": float(final_alt),
            "final_altitude_error_m": float(abs(final_alt - target_alt)),
            "minimum_altitude_m": float(min(all_alt)),
            "maximum_altitude_m": float(max(all_alt)),
            "target_altitude_m": target_alt,
            "replay_max_abs_difference": replay_max_abs_diff,
            "replay_matched": replay_matched,
            "integration_signature": INTEGRATION_SIGNATURE,
        },
        "model_hashes_sha256": hashes,
        "trajectory_sha256": trajectory_sha,
        "cleanup_succeeded": cleanup_succeeded,
        "limitations": list(MANDATORY_LIMITATIONS),
    }


def verify_court_record(
    court_record: dict[str, Any],
    *,
    model_path: Path | None = None,
    tolerance: float = REPLAY_TOLERANCE,
) -> dict[str, Any]:
    errors: list[str] = []

    if not isinstance(court_record, dict):
        return {
            "verified": False,
            "replay_verdict": "INVALID",
            "replay_max_abs_difference": 0.0,
            "tolerance": tolerance,
            "controller_hash_matched": False,
            "trajectory_hash_matched": False,
            "model_hashes_matched": False,
            "event_chain_verified": False,
            "record_id": None,
            "experiment_id": None,
            "errors": ["Court record must be a dictionary"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    schema_ver = court_record.get("schema_version")
    if schema_ver != SCHEMA_VERSION:
        errors.append(f"Unsupported schema version: {schema_ver}")

    record_id = court_record.get("record_id")
    if not record_id or not isinstance(record_id, str):
        errors.append("Missing or invalid record_id")

    experiment_id = court_record.get("experiment_id")
    if not experiment_id or not isinstance(experiment_id, str):
        errors.append("Missing or invalid experiment_id")

    spec_section = court_record.get("spec")
    if not isinstance(spec_section, dict):
        errors.append("Missing or invalid spec section")

    limitations = court_record.get("limitations")
    if not isinstance(limitations, list) or len(limitations) == 0:
        errors.append("Missing or empty limitations disclosure")

    verdicts_section = court_record.get("verdicts")
    if not isinstance(verdicts_section, dict):
        errors.append("Missing or invalid verdicts section")
    else:
        if verdicts_section.get("flight_qualification") != "INCONCLUSIVE":
            errors.append(
                f"Flight qualification must be INCONCLUSIVE, got {verdicts_section.get('flight_qualification')}"
            )
        if verdicts_section.get("flight_verdict") not in ("FALSIFIED", "NOT_FALSIFIED", "INVALID"):
            errors.append(f"Invalid flight_verdict: {verdicts_section.get('flight_verdict')}")
        if verdicts_section.get("containment_status") not in ("POLICY_CONFIRMED", "PARTIAL", "NOT_TESTED"):
            errors.append(f"Invalid containment_status: {verdicts_section.get('containment_status')}")
        if verdicts_section.get("provenance_status") not in ("VERIFIED", "INCOMPLETE"):
            errors.append(f"Invalid provenance_status: {verdicts_section.get('provenance_status')}")
        if verdicts_section.get("cleanup_status") not in ("SUCCEEDED", "FAILED"):
            errors.append(f"Invalid cleanup_status: {verdicts_section.get('cleanup_status')}")

    controller_section = court_record.get("controller")
    if not isinstance(controller_section, dict):
        errors.append("Missing or invalid controller section")
        controller_hash_matched = False
    else:
        src = controller_section.get("source_code", "")
        recorded_sha = controller_section.get("source_sha256", "")
        if not isinstance(src, str) or not isinstance(recorded_sha, str):
            controller_hash_matched = False
            errors.append("Controller source_code and source_sha256 must be strings")
        else:
            computed_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
            controller_hash_matched = bool(recorded_sha and computed_sha == recorded_sha)
            if not controller_hash_matched:
                errors.append(
                    f"Controller SHA-256 mismatch: recorded {recorded_sha}, computed {computed_sha}"
                )

    trajectory_section = court_record.get("trajectory")
    if not isinstance(trajectory_section, dict):
        errors.append("Missing or invalid trajectory section")
        trajectory_hash_matched = False
    else:
        recorded_traj_sha = trajectory_section.get("trajectory_sha256", "")
        try:
            computed_traj_sha = compute_trajectory_hash(
                steps=trajectory_section["steps"],
                timestamps=trajectory_section["timestamps"],
                position_m=trajectory_section["position_m"],
                velocity_mps=trajectory_section["velocity_mps"],
                actions=trajectory_section["actions"],
                integration_states=trajectory_section["integration_states"],
            )
            trajectory_hash_matched = bool(recorded_traj_sha and computed_traj_sha == recorded_traj_sha)
            if not trajectory_hash_matched:
                errors.append(
                    f"Trajectory SHA-256 mismatch: recorded {recorded_traj_sha}, computed {computed_traj_sha}"
                )
        except (KeyError, TypeError, ValueError) as err:
            trajectory_hash_matched = False
            errors.append(f"Trajectory payload malformed: {err}")

    event_log_section = court_record.get("event_log")
    if not isinstance(event_log_section, dict):
        errors.append("Missing or invalid event_log section")
        event_chain_verified = False
    else:
        events = event_log_section.get("events")
        if not isinstance(events, list):
            event_chain_verified = False
            errors.append("Event log events must be a list")
        else:
            exp_head = event_log_section.get("head_sha256")
            exp_count = event_log_section.get("event_count")
            chain_ok, chain_reason = verify_event_chain(
                events,
                expected_head=exp_head,
                expected_count=exp_count,
            )
            event_chain_verified = chain_ok
            if not chain_ok:
                errors.append(f"Event log integrity broken: {chain_reason}")

    sim_section = court_record.get("simulator")
    if not isinstance(sim_section, dict):
        sim_section = {}
        errors.append("Missing or invalid simulator section")
    else:
        if sim_section.get("engine") != "mujoco":
            errors.append("Simulator engine must be mujoco")
        if sim_section.get("integration_signature") != INTEGRATION_SIGNATURE:
            errors.append("Simulator integration signature mismatch")

    expected_model_hashes = (
        sim_section.get("model_hashes_sha256")
        or court_record.get("model_hashes_sha256", {})
    )

    resolved_model_path: Path | None = model_path
    if resolved_model_path is None:
        env_path = os.environ.get("DOMNIR_SPIKE_MODEL")
        if env_path and Path(env_path).is_file():
            resolved_model_path = Path(env_path)
        else:
            candidates = [
                Path.cwd() / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
                Path(__file__).resolve().parents[2] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
                Path(__file__).resolve().parents[1] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
            ]
            for c in candidates:
                if c.is_file():
                    resolved_model_path = c
                    break

    if resolved_model_path is None or not resolved_model_path.is_file():
        model_hashes_matched = False
        errors.append("MuJoCo model file could not be found for verification")
    else:
        current_hashes = model_hashes(resolved_model_path)
        model_hashes_matched = bool(expected_model_hashes and current_hashes == expected_model_hashes)
        if not model_hashes_matched:
            errors.append("Model file SHA-256 hashes do not match recorded hashes")

    replay_verdict = "INVALID"
    max_diff = 0.0

    if resolved_model_path and resolved_model_path.is_file() and isinstance(trajectory_section, dict):
        try:
            model = mujoco.MjModel.from_xml_path(str(resolved_model_path))
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
            if model.nu != 4 or body_id < 0 or not np.all(model.actuator_ctrllimited):
                errors.append("Replay model structure mismatch")
            else:
                raw_steps = trajectory_section.get("steps")
                if not isinstance(raw_steps, int) or raw_steps < 1 or raw_steps > 5000:
                    errors.append(f"Invalid trajectory step count: {raw_steps}")
                else:
                    steps = raw_steps
                    actions = np.asarray(trajectory_section.get("actions", []), dtype=np.float64)
                    integration_states = np.asarray(
                        trajectory_section.get("integration_states", []), dtype=np.float64
                    )
                    pos_m = np.asarray(trajectory_section.get("position_m", []), dtype=np.float64)
                    vel_mps = np.asarray(trajectory_section.get("velocity_mps", []), dtype=np.float64)
                    timestamps = np.asarray(trajectory_section.get("timestamps", []), dtype=np.float64)
                    state_size = mujoco.mj_stateSize(model, INTEGRATION_SIGNATURE)

                    scenario = court_record.get("scenario")
                    if not isinstance(scenario, dict):
                        scenario = {}
                        errors.append("Missing or invalid scenario section")

                    try:
                        disturbance = float(scenario.get("vertical_disturbance_n", 0.0))
                    except (TypeError, ValueError):
                        disturbance = 0.0
                        errors.append("Invalid vertical_disturbance_n in scenario")

                    if (
                        actions.shape != (steps, 4)
                        or integration_states.shape != (steps + 1, state_size)
                        or pos_m.shape != (steps + 1, 3)
                        or vel_mps.shape != (steps + 1, 3)
                        or timestamps.shape != (steps + 1,)
                        or not np.isfinite(actions).all()
                        or not np.isfinite(integration_states).all()
                        or not np.isfinite(pos_m).all()
                        or not np.isfinite(vel_mps).all()
                        or not np.isfinite(timestamps).all()
                        or np.any(actions < model.actuator_ctrlrange[:, 0])
                        or np.any(actions > model.actuator_ctrlrange[:, 1])
                    ):
                        errors.append("Invalid action or trajectory state dimensions/limits")
                    else:
                        data = mujoco.MjData(model)
                        restore_integration_state(model, data, integration_states[0])
                        restored_init = capture_integration_state(model, data)
                        step_max = float(np.max(np.abs(restored_init - integration_states[0])))

                        pos_init_diff = float(np.max(np.abs(data.qpos[:3] - pos_m[0])))
                        vel_init_diff = float(np.max(np.abs(data.qvel[:3] - vel_mps[0])))
                        if pos_init_diff > step_max:
                            step_max = pos_init_diff
                        if vel_init_diff > step_max:
                            step_max = vel_init_diff

                        for idx, action in enumerate(actions):
                            data.ctrl[:] = action
                            data.xfrc_applied[body_id, 2] = disturbance
                            mujoco.mj_step(model, data)

                            fresh_state = capture_integration_state(model, data)
                            if not np.isfinite(fresh_state).all():
                                raise ValueError(f"Non-finite state generated during replay step {idx + 1}")

                            state_diff = float(np.max(np.abs(fresh_state - integration_states[idx + 1])))
                            pos_diff = float(np.max(np.abs(data.qpos[:3] - pos_m[idx + 1])))
                            vel_diff = float(np.max(np.abs(data.qvel[:3] - vel_mps[idx + 1])))

                            if not math.isfinite(state_diff) or not math.isfinite(pos_diff) or not math.isfinite(vel_diff):
                                raise ValueError(f"Replay comparison produced non-finite difference at step {idx + 1}")

                            current_max = max(state_diff, pos_diff, vel_diff)
                            if current_max > step_max:
                                step_max = current_max

                        if model_hashes(resolved_model_path) != expected_model_hashes:
                            raise ValueError("Model files changed during replay")

                        max_diff = step_max
                        if max_diff <= tolerance:
                            replay_verdict = "MATCHED"
                        else:
                            replay_verdict = "DIVERGED"
                            errors.append(
                                f"Saved trajectory diverged: max difference {max_diff:.2e} exceeds tolerance {tolerance:.2e}"
                            )
        except Exception as sim_err:
            replay_verdict = "INVALID"
            errors.append(f"Simulation replay failure: {sim_err}")

    verified = bool(
        controller_hash_matched
        and trajectory_hash_matched
        and model_hashes_matched
        and event_chain_verified
        and replay_verdict == "MATCHED"
        and len(errors) == 0
    )

    return {
        "verified": verified,
        "replay_verdict": replay_verdict,
        "replay_max_abs_difference": max_diff,
        "tolerance": tolerance,
        "controller_hash_matched": controller_hash_matched,
        "trajectory_hash_matched": trajectory_hash_matched,
        "model_hashes_matched": model_hashes_matched,
        "event_chain_verified": event_chain_verified,
        "record_id": court_record.get("record_id"),
        "experiment_id": court_record.get("experiment_id"),
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
