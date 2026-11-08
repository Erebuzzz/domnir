"""Portable, independently verifiable Court Record for 3D mission runs.

The record carries everything needed to re-fly the mission on a fresh MuJoCo
instance: mission and world specs, fault schedule, initial conditions, every
controller action (one per controller invocation), and full integration-state
checkpoints. The verifier does not trust any recorded result. It re-runs the
flight from the recorded actions and recomputes contacts, stage outcomes and
verdicts, then compares them with what the record claims.

What verification proves: the recorded actions, applied to the recorded
world/mission/faults with the pinned model files, reproduce the recorded
states, contacts, stage results and verdicts. What it does not prove: who ran
the experiment. Hashes here are integrity checks, not signatures; someone who
re-runs a different experiment can produce a different self-consistent record.
Provenance is only server-confirmed when ``provenance.status`` says so, and
that claim can only be checked against the issuing server's artifact registry.
"""

from __future__ import annotations

import hashlib
import math
import platform
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import mujoco
import numpy as np

from domnir.court_record import canonical_json, chain_events, verify_event_chain
from domnir.faults.schema import MissionFaultSchedule
from domnir.missions.schema import MissionSpecV2
from domnir.missions.simulator import (
    REPLAY_TOLERANCE,
    MissionSimulationResult,
    compile_world_xml,
    fly,
)
from domnir.replay import INTEGRATION_SIGNATURE, model_hashes
from domnir.worlds import get_world
from domnir.worlds.schema import WorldSpec

MISSION_SCHEMA_VERSION = "domnir-mission-court-record-v1"
MAX_TRAJECTORY_SAMPLES = 250
MAX_CONTACT_SAMPLES = 200
MAX_CHECKPOINTS = 400
STAGE_TIME_TOLERANCE_S = 1e-9
ROBUSTNESS_TOLERANCE = 1e-5

MISSION_LIMITATIONS = [
    "Actuator dynamics and model limits are uncalibrated research assumptions.",
    "Simulated mission completion does not prove real-world hardware safety.",
    "Deterministic replay proves MuJoCo trajectory reproducibility under recorded actions, not physical validity.",
    "Finite scenario testing does not prove universal safety.",
    "Record hashes are integrity checks, not signatures; they do not authenticate who produced the record.",
]


def sha256_of(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def contact_signature(contacts: list[Any]) -> str:
    """Hash of the discrete contact sequence (step, geoms, class).

    Float fields are left out so the hash is stable across platforms whose
    replays agree within tolerance but not bit-for-bit.
    """
    rows = []
    for c in contacts:
        get = c.get if isinstance(c, dict) else (lambda k, _c=c: getattr(_c, k))
        rows.append([int(get("step_index")), str(get("geom1")), str(get("geom2")), str(get("contact_class"))])
    return sha256_of(rows)


def _checkpoint_interval(steps: int) -> int:
    return max(25, -(-steps // MAX_CHECKPOINTS))


def _checkpoint_steps(steps: int, interval: int) -> list[int]:
    points = list(range(0, steps + 1, interval))
    if points[-1] != steps:
        points.append(steps)
    return points


def _sample_indices(n: int, max_items: int) -> list[int]:
    if n <= max_items:
        return list(range(n))
    stride = -(-n // max_items)
    idx = list(range(0, n, stride))[:max_items]
    if idx[-1] != n - 1:
        idx = idx[: max_items - 1] + [n - 1]
    return idx


def _trajectory_sample(trajectory: list[dict[str, Any]], indices: list[int]) -> list[dict[str, Any]]:
    return [
        {
            "step_index": trajectory[i]["step_index"],
            "sim_time_s": trajectory[i]["sim_time_s"],
            "position_m": trajectory[i]["position_m"],
            "velocity_mps": trajectory[i]["velocity_mps"],
            "orientation_quat_wxyz": trajectory[i]["orientation_quat_wxyz"],
            "active_stage_id": trajectory[i]["active_stage_id"],
        }
        for i in indices
    ]


def _verdict_block(result_eval: Any, replay_matched: bool, replay_diff: float) -> dict[str, Any]:
    return {
        "physical_verdict": result_eval.physical_verdict,
        "mission_verdict": result_eval.mission_verdict,
        "stages_completed": result_eval.stages_completed,
        "total_stages": result_eval.total_stages,
        "mission_failure_reason": result_eval.mission_failure_reason,
        "min_robustness": result_eval.min_robustness,
        "critical_predicate": result_eval.critical_predicate,
        "critical_timestamp_s": result_eval.critical_timestamp_s,
        "replay_matched": replay_matched,
        "replay_max_abs_diff": replay_diff,
        # A finite simulated run never qualifies a controller for flight.
        "flight_qualification": "INCONCLUSIVE",
    }


def build_mission_court_record(
    *,
    result: MissionSimulationResult,
    model_path: Path,
    faults: MissionFaultSchedule | None,
    controller_source: str | None,
    controller_type: str,
    provenance: dict[str, Any],
    execution: dict[str, Any],
) -> dict[str, Any]:
    mission = result.mission
    world = result.world
    run = result.run
    steps = mission.physics_steps
    interval = _checkpoint_interval(steps)
    cp_steps = _checkpoint_steps(steps, interval)

    mission_dump = mission.model_dump(mode="json")
    world_dump = world.model_dump(mode="json")
    faults_dump = faults.model_dump(mode="json") if faults is not None else None
    source_sha = hashlib.sha256(controller_source.encode("utf-8")).hexdigest() if controller_source else None
    try:
        registry_world = get_world(world.world_id).model_dump(mode="json")
        world_registry_match = registry_world == world_dump
    except KeyError:
        world_registry_match = None

    record_id = f"mcr-{uuid.uuid4().hex[:16]}"
    verdicts = _verdict_block(result.evaluation, result.replay_matched, result.replay_max_abs_diff)
    contacts_dump = [c.model_dump() for c in run.contacts]
    by_class: dict[str, int] = {}
    for c in run.contacts:
        by_class[c.contact_class] = by_class.get(c.contact_class, 0) + 1

    raw_events = [
        {"event_type": "mission_requested", "details": {
            "world_id": world.world_id,
            "mission_sha256": sha256_of(mission_dump),
            "controller_sha256": source_sha,
            "controller_type": controller_type,
        }},
        {"event_type": "controller_execution", "details": {
            "backend": execution.get("execution_backend"),
            "isolation_status": execution.get("isolation_status"),
            "sandbox_name": execution.get("sandbox_name"),
            "controller_invocations": run.controller_invocations,
        }},
        {"event_type": "simulation_completed", "details": {
            "physics_steps": steps,
            "physical_verdict": verdicts["physical_verdict"],
            "mission_verdict": verdicts["mission_verdict"],
            "stages_completed": verdicts["stages_completed"],
        }},
        {"event_type": "replay_completed", "details": {
            "max_abs_difference": result.replay_max_abs_diff,
            "matched": result.replay_matched,
        }},
        {"event_type": "cleanup_observed", "details": {
            "cleanup_status": execution.get("cleanup_status"),
        }},
    ]
    events, head = chain_events(raw_events)

    record: dict[str, Any] = {
        "schema_version": MISSION_SCHEMA_VERSION,
        "record_id": record_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "mission": mission_dump,
        "mission_sha256": sha256_of(mission_dump),
        "world": world_dump,
        "world_sha256": sha256_of(world_dump),
        "world_registry_match": world_registry_match,
        "faults": faults_dump,
        "faults_sha256": sha256_of(faults_dump),
        "initial_conditions": {"initial_pos_m": list(result.initial_pos_m), "seed": result.seed},
        "simulator": {
            "engine": "mujoco",
            "mujoco_version": mujoco.__version__,
            "platform": platform.platform(),
            "model_path": model_path.name,
            "model_hashes_sha256": model_hashes(model_path),
            "compiled_mjcf_sha256": hashlib.sha256(result.compiled_xml.encode("utf-8")).hexdigest(),
            "integration_signature": INTEGRATION_SIGNATURE,
            "physics_dt_s": mission.physics_dt_s,
            "controller_dt_s": mission.controller_dt_s,
            "controller_period_steps": run.controller_period_steps,
            "effective_controller_hz": result.effective_controller_hz,
            "physics_steps": steps,
        },
        "controller": {
            "controller_type": controller_type,
            "source_code": controller_source,
            "source_sha256": source_sha,
            "invocations": run.controller_invocations,
        },
        "provenance": provenance,
        "execution": execution,
        "controller_actions": run.controller_actions,
        "checkpoints": {
            "interval_steps": interval,
            "steps": cp_steps,
            "states": [run.states[i].tolist() for i in cp_steps],
        },
        "trajectory_samples": _trajectory_sample(run.trajectory, _sample_indices(len(run.trajectory), MAX_TRAJECTORY_SAMPLES)),
        "contacts": {
            "total": len(run.contacts),
            "by_class": by_class,
            "signature_sha256": contact_signature(contacts_dump),
            "samples": contacts_dump[:MAX_CONTACT_SAMPLES],
        },
        "stage_results": run.stage_history,
        "verdicts": verdicts,
        "replay": {
            "tolerance": REPLAY_TOLERANCE,
            "max_abs_difference": result.replay_max_abs_diff,
            "verdict": "MATCHED" if result.replay_matched else "DIVERGED",
        },
        "event_log": {"events": events, "event_count": len(events), "head_sha256": head},
        "limitations": list(MISSION_LIMITATIONS),
    }
    record["content_sha256"] = sha256_of(record)
    return record


def _close(a: Any, b: Any, tol: float) -> bool:
    try:
        return math.isfinite(float(a)) and math.isfinite(float(b)) and abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def verify_mission_court_record(record: dict[str, Any], *, model_path: Path) -> dict[str, Any]:
    """Re-fly the recorded mission and check every claim in the record."""
    errors: list[str] = []
    checks: dict[str, bool] = {}

    def check(name: str, ok: bool, message: str) -> bool:
        checks[name] = bool(ok)
        if not ok:
            errors.append(message)
        return bool(ok)

    def result(replay_verdict: str = "INVALID", max_diff: float = 0.0) -> dict[str, Any]:
        verified = not errors and replay_verdict == "MATCHED" and all(checks.values())
        return {
            "verified": verified,
            "record_type": "mission",
            "replay_verdict": replay_verdict,
            "replay_max_abs_difference": max_diff,
            "tolerance": REPLAY_TOLERANCE,
            "controller_hash_matched": checks.get("controller_hash", False),
            "trajectory_hash_matched": checks.get("trajectory_samples", False) and checks.get("checkpoints", False),
            "model_hashes_matched": checks.get("model_hashes", False),
            "event_chain_verified": checks.get("event_chain", False),
            "record_id": record.get("record_id") if isinstance(record, dict) else None,
            "experiment_id": (record.get("mission") or {}).get("mission_id") if isinstance(record, dict) else None,
            "checks": checks,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    if not isinstance(record, dict) or record.get("schema_version") != MISSION_SCHEMA_VERSION:
        check("schema", False, "Not a mission Court Record")
        return result()

    # 1. Whole-record integrity.
    body = {k: v for k, v in record.items() if k != "content_sha256"}
    check("content_hash", record.get("content_sha256") == sha256_of(body),
          "Record content SHA-256 does not match; the record was modified after it was sealed")

    # 2. Parse untrusted specs through the same validated schemas the API uses.
    try:
        mission = MissionSpecV2.model_validate(record.get("mission"))
        world = WorldSpec.model_validate(record.get("world"))
        faults_raw = record.get("faults")
        faults = MissionFaultSchedule.model_validate(faults_raw) if faults_raw is not None else None
    except Exception as exc:  # noqa: BLE001 - any schema failure is a rejection
        check("schema", False, f"Mission, world or fault schedule failed validation: {exc}")
        return result()
    checks["schema"] = True

    check("mission_hash", record.get("mission_sha256") == sha256_of(record.get("mission")),
          "Mission spec SHA-256 mismatch")
    check("world_hash", record.get("world_sha256") == sha256_of(record.get("world")),
          "World spec SHA-256 mismatch")
    check("faults_hash", record.get("faults_sha256") == sha256_of(record.get("faults")),
          "Fault schedule SHA-256 mismatch")
    try:
        registry_world = get_world(world.world_id).model_dump(mode="json")
        check("world_registry", registry_world == record.get("world"),
              f"World geometry differs from the registered '{world.world_id}' world")
    except KeyError:
        pass  # custom worlds are checked by hash and replay only

    controller = record.get("controller") or {}
    src = controller.get("source_code")
    if src is None:
        check("controller_hash", controller.get("source_sha256") is None,
              "Baseline record must not carry a controller hash")
    else:
        check("controller_hash", isinstance(src, str)
              and hashlib.sha256(src.encode("utf-8")).hexdigest() == controller.get("source_sha256"),
              "Controller source SHA-256 mismatch")

    events = (record.get("event_log") or {}).get("events")
    ok, reason = verify_event_chain(
        events if isinstance(events, list) else [],
        expected_head=(record.get("event_log") or {}).get("head_sha256"),
        expected_count=(record.get("event_log") or {}).get("event_count"),
    )
    check("event_chain", ok and isinstance(events, list), f"Event log integrity broken: {reason}")

    limitations = record.get("limitations")
    check("limitations", isinstance(limitations, list) and all(l in limitations for l in MISSION_LIMITATIONS),
          "Mandatory limitations disclosure is missing or altered")
    check("qualification", (record.get("verdicts") or {}).get("flight_qualification") == "INCONCLUSIVE",
          "flight_qualification must be INCONCLUSIVE")

    # 3. Model files and compiled scene.
    sim = record.get("simulator") or {}
    if not model_path.is_file():
        check("model_hashes", False, "MuJoCo model file could not be found for verification")
        return result()
    check("model_hashes", model_hashes(model_path) == sim.get("model_hashes_sha256"),
          "Model file SHA-256 hashes do not match recorded hashes")
    check("integration_signature", sim.get("integration_signature") == INTEGRATION_SIGNATURE,
          "Integration state signature mismatch")
    compiled_xml = compile_world_xml(model_path, world)
    check("compiled_mjcf", hashlib.sha256(compiled_xml.encode("utf-8")).hexdigest() == sim.get("compiled_mjcf_sha256"),
          "Compiled MJCF scene hash mismatch")
    check("controller_rate", sim.get("controller_period_steps") == mission.controller_period_steps
          and sim.get("physics_steps") == mission.physics_steps,
          "Controller period or step count does not match the mission spec")

    # 4. Re-fly from the recorded actions.
    init = record.get("initial_conditions") or {}
    actions = record.get("controller_actions")
    if not isinstance(actions, list):
        check("replay", False, "controller_actions must be a list")
        return result()
    try:
        initial_pos = [float(v) for v in init.get("initial_pos_m")]
        if len(initial_pos) != 3:
            raise ValueError("initial_pos_m must have 3 values")
        replay = fly(
            compiled_xml,
            mission,
            world,
            recorded_controller_actions=actions,
            faults=faults,
            seed=int(init.get("seed", 42)),
            initial_pos_m=initial_pos,
        )
    except Exception as exc:  # noqa: BLE001
        check("replay", False, f"Replay failed: {exc}")
        return result()
    checks["replay"] = True

    # 4a. Integration-state checkpoints.
    cps = record.get("checkpoints") or {}
    cp_steps = cps.get("steps")
    cp_states = cps.get("states")
    max_diff = 0.0
    cp_ok = (
        isinstance(cp_steps, list)
        and isinstance(cp_states, list)
        and len(cp_steps) == len(cp_states)
        and cp_steps == _checkpoint_steps(mission.physics_steps, _checkpoint_interval(mission.physics_steps))
    )
    if cp_ok:
        try:
            recorded = np.asarray(cp_states, dtype=np.float64)
            fresh = replay.states[np.asarray(cp_steps, dtype=int)]
            cp_ok = recorded.shape == fresh.shape and bool(np.isfinite(recorded).all())
            if cp_ok:
                max_diff = float(np.max(np.abs(recorded - fresh)))
        except (TypeError, ValueError, IndexError):
            cp_ok = False
    check("checkpoints", cp_ok and max_diff <= REPLAY_TOLERANCE,
          f"Integration-state checkpoints diverged from replay (max difference {max_diff:.2e})"
          if cp_ok else "Checkpoint layout does not match the mission")
    replay_verdict = "MATCHED" if cp_ok and max_diff <= REPLAY_TOLERANCE else ("DIVERGED" if cp_ok else "INVALID")

    # 4b. Trajectory samples shown to users.
    samples = record.get("trajectory_samples")
    samples_ok = isinstance(samples, list) and len(samples) > 0
    if samples_ok:
        for s in samples:
            try:
                i = int(s["step_index"])
                ref = replay.trajectory[i]
                if not (
                    _close(s["sim_time_s"], ref["sim_time_s"], REPLAY_TOLERANCE)
                    and all(_close(a, b, REPLAY_TOLERANCE) for a, b in zip(s["position_m"], ref["position_m"], strict=True))
                    and all(_close(a, b, REPLAY_TOLERANCE) for a, b in zip(s["velocity_mps"], ref["velocity_mps"], strict=True))
                    and s.get("active_stage_id") == ref["active_stage_id"]
                ):
                    samples_ok = False
                    break
            except (KeyError, TypeError, ValueError, IndexError):
                samples_ok = False
                break
    check("trajectory_samples", samples_ok, "Recorded trajectory samples do not match the replayed flight")

    # 4c. Contacts.
    contacts = record.get("contacts") or {}
    check("contacts", contacts.get("total") == len(replay.contacts)
          and contacts.get("signature_sha256") == contact_signature(replay.contacts),
          "Recorded contact history does not match the replayed flight")

    # 4d. Stage outcomes and verdicts, recomputed from the replayed flight.
    recorded_stages = record.get("stage_results")
    stages_ok = isinstance(recorded_stages, list) and len(recorded_stages) == len(replay.stage_history)
    if stages_ok:
        for got, want in zip(recorded_stages, replay.stage_history):
            if not isinstance(got, dict) or got.get("stage_id") != want["stage_id"] or got.get("status") != want["status"]:
                stages_ok = False
                break
            for key in ("entered_at_s", "completed_at_s", "timed_out_at_s"):
                if (want.get(key) is None) != (got.get(key) is None):
                    stages_ok = False
                elif want.get(key) is not None and not _close(got.get(key), want[key], STAGE_TIME_TOLERANCE_S):
                    stages_ok = False
    check("stage_results", stages_ok, "Recorded stage results do not match the replayed flight")

    v = record.get("verdicts") or {}
    ev = replay.evaluation
    check("verdicts", v.get("physical_verdict") == ev.physical_verdict
          and v.get("mission_verdict") == ev.mission_verdict
          and v.get("stages_completed") == ev.stages_completed
          and v.get("total_stages") == ev.total_stages
          and v.get("critical_predicate") == ev.critical_predicate
          and _close(v.get("min_robustness"), ev.min_robustness, ROBUSTNESS_TOLERANCE),
          "Recorded verdicts do not match the verdicts recomputed from the replayed flight")

    return result(replay_verdict, max_diff)
