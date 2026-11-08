"""Portable Court Record Multi-Tier Independent Verifier and CLI for Dómnir."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

import mujoco
import numpy as np
from pydantic import BaseModel, Field

from domnir.missions.court_record import MISSION_SCHEMA_VERSION, verify_mission_court_record
from domnir.signing import (
    AUTHENTIC,
    INVALID_SIGNATURE,
    SIGNED_UNTRUSTED_KEY,
    UNSIGNED,
    check_signature,
    parse_trusted_keys,
)
from domnir.court_record import (
    LIMITATIONS,
    REPLAY_TOLERANCE,
    SCHEMA_VERSION,
    _seal_payload,
    canonical_json,
    compute_legacy_trajectory_hash,
    compute_trajectory_hash,
    sha256_of,
    verify_event_chain,
)
from domnir.replay import (
    INTEGRATION_SIGNATURE,
    capture_integration_state,
    model_hashes,
    restore_integration_state,
)


def resolve_model_path(model_path: Path | str | None = None) -> Path | None:
    """Resolve Crazyflie 2 MuJoCo model file."""
    if model_path is not None:
        p = Path(model_path)
        if p.is_file():
            return p
    env_path = os.environ.get("DOMNIR_SPIKE_MODEL")
    if env_path and Path(env_path).is_file():
        return Path(env_path)
    candidates = [
        Path.cwd() / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
        Path(__file__).resolve().parents[1] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
        Path(__file__).resolve().parents[2] / ".cache" / "mujoco_menagerie" / "bitcraze_crazyflie_2" / "cf2.xml",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


class TierLevel(str, Enum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class TierResult(BaseModel):
    level: str
    name: str
    passed: bool
    status: str = "PASS"  # PASS, FAIL, NOT_RUN, INCOMPLETE, UNAVAILABLE
    tampered: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class VerificationReport(BaseModel):
    verified: bool
    tampered: bool
    record_id: str | None = None
    experiment_id: str | None = None
    tiers: dict[str, TierResult] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    tamper_details: list[str] = Field(default_factory=list)
    summary: str = ""
    authenticity: str = UNSIGNED
    signer_key_id: str | None = None
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class CourtRecordVerifier:
    """Multi-tier independent verifier for portable Court Records."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        replay_tolerance: float = REPLAY_TOLERANCE,
        trusted_keys: dict[str, str] | None = None,
    ) -> None:
        self.model_path = resolve_model_path(model_path)
        self.replay_tolerance = replay_tolerance
        self.trusted_keys = trusted_keys

    def verify(
        self,
        record_or_path: dict[str, Any] | str | Path,
        max_tier: str = "L3",
    ) -> VerificationReport:
        record: dict[str, Any]
        if isinstance(record_or_path, (str, Path)):
            path = Path(record_or_path)
            if not path.is_file():
                return VerificationReport(
                    verified=False,
                    tampered=False,
                    errors=[f"Court record file not found: {path}"],
                    summary=f"File not found: {path}",
                )
            try:
                with path.open("r", encoding="utf-8") as f:
                    record = json.load(f)
            except Exception as e:
                return VerificationReport(
                    verified=False,
                    tampered=False,
                    errors=[f"Failed to parse court record JSON: {e}"],
                    summary=f"Invalid JSON: {e}",
                )
        elif isinstance(record_or_path, dict):
            record = record_or_path
        else:
            return VerificationReport(
                verified=False,
                tampered=False,
                errors=["Court record must be a dict or a file path"],
                summary="Invalid court record type",
            )

        if "court_record" in record and isinstance(record["court_record"], dict):
            record = record["court_record"]

        tiers: dict[str, TierResult] = {}
        all_errors: list[str] = []
        tamper_details: list[str] = []
        is_tampered = False

        # Tier L0: Structural Integrity
        l0_result = self.verify_l0(record)
        tiers["L0"] = l0_result
        if not l0_result.passed:
            all_errors.extend(l0_result.errors)
        if l0_result.tampered:
            is_tampered = True
            tamper_details.extend(l0_result.errors)

        # Tier L1: Physics Replay
        if max_tier in ("L1", "L2", "L3"):
            l1_result = self.verify_l1(record)
            tiers["L1"] = l1_result
            if not l1_result.passed:
                all_errors.extend(l1_result.errors)
            if l1_result.tampered:
                is_tampered = True
                tamper_details.extend(l1_result.errors)

        # Tier L2: Controller Determinism
        if max_tier in ("L2", "L3"):
            l2_result = self.verify_l2(record)
            tiers["L2"] = l2_result
            if not l2_result.passed:
                all_errors.extend(l2_result.errors)
            if l2_result.tampered:
                is_tampered = True
                tamper_details.extend(l2_result.errors)

        # Tier L3: Containment Audit
        if max_tier == "L3":
            l3_result = self.verify_l3(record)
            tiers["L3"] = l3_result
            if not l3_result.passed:
                all_errors.extend(l3_result.errors)
            if l3_result.tampered:
                is_tampered = True
                tamper_details.extend(l3_result.errors)

        all_passed = all(t.passed for t in tiers.values())
        verified = all_passed and not is_tampered

        record_id = record.get("record_id") if isinstance(record, dict) else None
        exp_id = record.get("experiment_id") if isinstance(record, dict) else None

        if is_tampered:
            summary = (
                f"TAMPERING DETECTED in record {record_id or 'unknown'}: "
                f"{len(tamper_details)} tamper issue(s) detected across tiers."
            )
        elif all_passed:
            passed_names = ", ".join(t.level for t in tiers.values())
            summary = (
                f"Court Record {record_id or 'unknown'} verified across tiers ({passed_names}). "
                "All deterministic hashes, replay traces, and containment events confirmed."
            )
        else:
            failed_tiers = ", ".join(k for k, v in tiers.items() if not v.passed)
            summary = (
                f"Verification FAILED for record {record_id or 'unknown'}. "
                f"Failed tiers: {failed_tiers}."
            )

        return VerificationReport(
            verified=verified,
            tampered=is_tampered,
            record_id=record_id,
            experiment_id=exp_id,
            tiers=tiers,
            errors=all_errors,
            tamper_details=tamper_details,
            summary=summary,
            authenticity=l0_result.details.get("authenticity", UNSIGNED),
            signer_key_id=l0_result.details.get("signer_key_id"),
        )

    def verify_l0(self, record: dict[str, Any]) -> TierResult:
        errors: list[str] = []
        details: dict[str, Any] = {}
        tampered = False

        if not isinstance(record, dict):
            return TierResult(
                level="L0",
                name="Structural Integrity",
                passed=False,
                tampered=False,
                errors=["Court record payload is not a dictionary"],
            )

        # Cryptographic seal verification (backward-compatible with unsigned older records)
        if "record_signature" in record or "content_sha256" in record:
            body = {k: v for k, v in record.items() if k not in ("content_sha256", "record_signature")}
            rec_sha = record.get("content_sha256")
            computed_sha = sha256_of(body)
            if not rec_sha or computed_sha != rec_sha:
                tampered = True
                errors.append(
                    "Record content SHA-256 mismatch; the record was modified after it was sealed"
                )

            sig = record.get("record_signature")
            authenticity, reason = check_signature(_seal_payload(record), sig, self.trusted_keys)
            details["authenticity"] = authenticity
            details["signer_key_id"] = sig.get("key_id") if isinstance(sig, dict) else None
            if authenticity == INVALID_SIGNATURE:
                tampered = True
                errors.append(f"Invalid record seal signature: {reason}")
        else:
            details["authenticity"] = UNSIGNED
            details["signer_key_id"] = None

        schema_ver = record.get("schema_version")
        if schema_ver != SCHEMA_VERSION:
            errors.append(f"Unsupported schema version: {schema_ver} (expected {SCHEMA_VERSION})")

        rec_id = record.get("record_id")
        if not rec_id or not isinstance(rec_id, str):
            errors.append("Missing or invalid record_id")

        exp_id = record.get("experiment_id")
        if not exp_id or not isinstance(exp_id, str):
            errors.append("Missing or invalid experiment_id")

        spec_sec = record.get("spec")
        if not isinstance(spec_sec, dict):
            errors.append("Missing or invalid spec section")

        limits = record.get("limitations")
        if not isinstance(limits, list) or len(limits) == 0:
            errors.append("Missing or empty mandatory limitations disclosure")

        ctrl_sec = record.get("controller")
        if not isinstance(ctrl_sec, dict):
            errors.append("Missing or invalid controller section")
        else:
            src = ctrl_sec.get("source_code", "")
            rec_sha = ctrl_sec.get("source_sha256", "")
            if not isinstance(src, str) or not isinstance(rec_sha, str):
                errors.append("Controller source_code and source_sha256 must be strings")
            else:
                computed_sha = hashlib.sha256(src.encode("utf-8")).hexdigest()
                if not rec_sha or computed_sha != rec_sha:
                    tampered = True
                    errors.append(
                        f"Controller SHA-256 mismatch (tampered code or hash): recorded {rec_sha}, computed {computed_sha}"
                    )
                else:
                    details["controller_hash"] = rec_sha

        traj_sec = record.get("trajectory")
        if not isinstance(traj_sec, dict):
            errors.append("Missing or invalid trajectory section")
        else:
            rec_traj_sha = traj_sec.get("trajectory_sha256", "")
            try:
                computed_traj_sha = compute_trajectory_hash(
                    steps=traj_sec["steps"],
                    timestamps=traj_sec["timestamps"],
                    position_m=traj_sec["position_m"],
                    velocity_mps=traj_sec["velocity_mps"],
                    actions=traj_sec["actions"],
                    integration_states=traj_sec["integration_states"],
                )
                if not rec_traj_sha or computed_traj_sha != rec_traj_sha:
                    legacy_traj_sha = compute_legacy_trajectory_hash(
                        steps=traj_sec["steps"],
                        timestamps=traj_sec["timestamps"],
                        position_m=traj_sec["position_m"],
                        velocity_mps=traj_sec["velocity_mps"],
                        actions=traj_sec["actions"],
                        integration_states=traj_sec["integration_states"],
                    )
                    if rec_traj_sha and legacy_traj_sha == rec_traj_sha:
                        details["trajectory_hash"] = rec_traj_sha
                        details["canonicalization"] = "legacy_v1"
                    else:
                        tampered = True
                        errors.append(
                            f"Trajectory SHA-256 mismatch (modified actions or states): recorded {rec_traj_sha}, computed {computed_traj_sha}"
                        )
                else:
                    details["trajectory_hash"] = rec_traj_sha
                    details["canonicalization"] = "rfc8785_jcs"
            except (KeyError, TypeError, ValueError) as err:
                tampered = True
                errors.append(f"Trajectory payload malformed or tampered: {err}")

            timestamps = traj_sec.get("timestamps", [])
            if isinstance(timestamps, list) and len(timestamps) > 1:
                for idx in range(len(timestamps) - 1):
                    if timestamps[idx + 1] < timestamps[idx]:
                        tampered = True
                        errors.append(
                            f"Altered timestamps: non-monotonic trajectory timestamp at step {idx + 1} ({timestamps[idx + 1]} < {timestamps[idx]})"
                        )
                        break

        event_sec = record.get("event_log")
        if not isinstance(event_sec, dict):
            errors.append("Missing or invalid event_log section")
        else:
            events = event_sec.get("events")
            if not isinstance(events, list):
                errors.append("Event log events must be a list")
            else:
                head_sha = event_sec.get("head_sha256")
                count = event_sec.get("event_count")
                chain_ok, chain_reason = verify_event_chain(
                    events,
                    expected_head=head_sha,
                    expected_count=count,
                )
                if not chain_ok:
                    tampered = True
                    errors.append(f"Broken event chain: {chain_reason}")
                else:
                    details["event_chain_head"] = head_sha
                    details["event_count"] = len(events)

        verdicts_sec = record.get("verdicts")
        if not isinstance(verdicts_sec, dict):
            errors.append("Missing or invalid verdicts section")
        else:
            if verdicts_sec.get("flight_qualification") != "INCONCLUSIVE":
                errors.append(
                    f"Flight qualification must be INCONCLUSIVE, got {verdicts_sec.get('flight_qualification')}"
                )

        passed = len(errors) == 0 and not tampered
        status_str = "PASS" if passed else ("FAIL" if tampered else "INCOMPLETE")
        return TierResult(
            level="L0",
            name="Structural Integrity",
            passed=passed,
            status=status_str,
            tampered=tampered,
            details=details,
            errors=errors,
        )

    def verify_l1(self, record: dict[str, Any]) -> TierResult:
        errors: list[str] = []
        details: dict[str, Any] = {}
        tampered = False

        model_path = self.model_path or resolve_model_path()
        if model_path is None or not model_path.is_file():
            return TierResult(
                level="L1",
                name="Physics Replay",
                passed=False,
                tampered=False,
                errors=["MuJoCo model file could not be found for physics replay"],
            )

        sim_sec = record.get("simulator", {})
        expected_hashes = sim_sec.get("model_hashes_sha256") or record.get("model_hashes_sha256", {})
        current_norm = {k.replace("\\", "/"): v for k, v in model_hashes(model_path).items()}
        expected_norm = {k.replace("\\", "/"): v for k, v in (expected_hashes or {}).items()}
        if expected_norm and current_norm != expected_norm:
            tampered = True
            errors.append("Model file SHA-256 hashes do not match recorded hashes")

        traj_sec = record.get("trajectory")
        if not isinstance(traj_sec, dict):
            return TierResult(
                level="L1",
                name="Physics Replay",
                passed=False,
                tampered=True,
                errors=["Missing trajectory section for physics replay"],
            )

        try:
            model = mujoco.MjModel.from_xml_path(str(model_path))
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "cf2")
            if model.nu != 4 or body_id < 0 or not np.all(model.actuator_ctrllimited):
                errors.append("Replay model structure mismatch")
                return TierResult(
                    level="L1",
                    name="Physics Replay",
                    passed=False,
                    tampered=False,
                    errors=errors,
                )

            raw_steps = traj_sec.get("steps")
            if not isinstance(raw_steps, int) or raw_steps < 1:
                return TierResult(
                    level="L1",
                    name="Physics Replay",
                    passed=False,
                    tampered=True,
                    errors=[f"Invalid trajectory steps count: {raw_steps}"],
                )

            steps = raw_steps
            actions = np.asarray(traj_sec.get("actions", []), dtype=np.float64)
            integration_states = np.asarray(traj_sec.get("integration_states", []), dtype=np.float64)
            pos_m = np.asarray(traj_sec.get("position_m", []), dtype=np.float64)
            vel_mps = np.asarray(traj_sec.get("velocity_mps", []), dtype=np.float64)
            timestamps = np.asarray(traj_sec.get("timestamps", []), dtype=np.float64)

            state_size = mujoco.mj_stateSize(model, INTEGRATION_SIGNATURE)
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
            ):
                return TierResult(
                    level="L1",
                    name="Physics Replay",
                    passed=False,
                    tampered=True,
                    errors=["Invalid action or trajectory state dimensions/finite checks"],
                )

            scenario = record.get("scenario", {})
            disturbance = float(scenario.get("vertical_disturbance_n", 0.0))

            data = mujoco.MjData(model)
            restore_integration_state(model, data, integration_states[0])
            step_max = float(np.max(np.abs(capture_integration_state(model, data) - integration_states[0])))

            for idx, action in enumerate(actions):
                data.ctrl[:] = action
                data.xfrc_applied[body_id, 2] = disturbance
                mujoco.mj_step(model, data)

                fresh_state = capture_integration_state(model, data)
                state_diff = float(np.max(np.abs(fresh_state - integration_states[idx + 1])))
                pos_diff = float(np.max(np.abs(data.qpos[:3] - pos_m[idx + 1])))
                vel_diff = float(np.max(np.abs(data.qvel[:3] - vel_mps[idx + 1])))

                current_max = max(state_diff, pos_diff, vel_diff)
                if current_max > step_max:
                    step_max = current_max

            details["max_divergence_m"] = step_max
            details["tolerance_m"] = self.replay_tolerance
            details["steps_replayed"] = steps

            if step_max <= self.replay_tolerance:
                passed = True
            else:
                passed = False
                tampered = True
                errors.append(
                    f"Physics replay divergence {step_max:.2e} m exceeds tolerance {self.replay_tolerance:.2e} m"
                )
        except Exception as sim_err:
            passed = False
            errors.append(f"Simulation replay failure: {sim_err}")

        return TierResult(
            level="L1",
            name="Physics Replay",
            passed=passed,
            status="PASS" if passed else "FAIL",
            tampered=tampered,
            details=details,
            errors=errors,
        )

    def verify_l2(self, record: dict[str, Any]) -> TierResult:
        errors: list[str] = []
        details: dict[str, Any] = {}
        tampered = False

        ctrl_sec = record.get("controller", {})
        src = ctrl_sec.get("source_code", "")
        if not src:
            return TierResult(
                level="L2",
                name="Controller Determinism",
                passed=False,
                tampered=True,
                errors=["Missing controller source code"],
            )

        traj_sec = record.get("trajectory", {})
        actions = traj_sec.get("actions", [])
        timestamps = traj_sec.get("timestamps", [])
        pos_m = traj_sec.get("position_m", [])
        vel_mps = traj_sec.get("velocity_mps", [])
        integration_states = traj_sec.get("integration_states", [])
        steps = traj_sec.get("steps", len(actions))

        if len(actions) != steps:
            return TierResult(
                level="L2",
                name="Controller Determinism",
                passed=False,
                tampered=True,
                errors=["Action count does not match trajectory steps"],
            )

        # 1. Static validation of controller source without host execution
        try:
            from domnir.evaluator import validate_controller_source, is_microvm_available
            validate_controller_source(src)
        except Exception as err:
            return TierResult(
                level="L2",
                name="Controller Determinism",
                passed=False,
                tampered=True,
                errors=[f"Controller source validation error: {err}"],
            )

        # 2. Check execution capability (MicroVM or dev fallback)
        is_prod = os.environ.get("DOMNIR_ENV", os.environ.get("ENV", "")).lower() in {"production", "prod", "live"}
        dev_fallback = (not is_prod) and (os.environ.get("DOMNIR_DEV_ALLOW_SUBPROCESS_FALLBACK") == "1")

        if not (is_microvm_available() or dev_fallback):
            return TierResult(
                level="L2",
                name="Controller Determinism",
                passed=False,
                status="UNAVAILABLE",
                tampered=False,
                details={
                    "status": "UNAVAILABLE",
                    "reason": "MicroVM hardware acceleration (/dev/kvm) is required to execute untrusted controller code",
                },
                errors=["L2 execution skipped: microVM sandbox unavailable on unvirtualized host"],
            )

        # 3. Execution strictly via isolated stream
        from domnir.api.jobs import _MicroVMGuestStream, _IsolatedSubprocessGuestStream
        from domnir.sandbox import SandboxLease
        import shutil

        stream = None
        lease = None
        target_alt = float(record.get("spec", {}).get("target_altitude_m", 0.1))
        dt_s = float(record.get("scenario", {}).get("timestep_s", 0.002))
        max_action_diff = 0.0

        try:
            if is_microvm_available():
                msb_path = Path(os.environ.get("DOMNIR_MSB") or shutil.which("msb"))
                lease = SandboxLease(msb_path, duration_seconds=60)
                lease.__enter__()
                lease.install_controller(src.encode("utf-8"))
                stream = _MicroVMGuestStream(lease)
            else:
                stream = _IsolatedSubprocessGuestStream(src)

            for k in range(steps):
                obs = {
                    "schema_version": "1.0",
                    "trial_id": str(record.get("experiment_id", "")),
                    "step_index": k,
                    "sim_time_s": float(timestamps[k]) if k < len(timestamps) else k * dt_s,
                    "dt_s": dt_s,
                    "position_m": list(pos_m[k]) if k < len(pos_m) else [0.0, 0.0, 0.1],
                    "velocity_mps": list(vel_mps[k]) if k < len(vel_mps) else [0.0, 0.0, 0.0],
                    "orientation_quat_wxyz": list(integration_states[k][3:7]) if k < len(integration_states) and len(integration_states[k]) >= 7 else [1.0, 0.0, 0.0, 0.0],
                    "body_angular_velocity_rps": list(integration_states[k][7:10]) if k < len(integration_states) and len(integration_states[k]) >= 10 else [0.0, 0.0, 0.0],
                    "target_position_m": [0.0, 0.0, target_alt],
                    "target_altitude_m": target_alt,
                }

                try:
                    resp_str = stream.exchange(obs)
                    raw_act = json.loads(resp_str)
                except Exception as err:
                    tampered = True
                    errors.append(f"Guest observe() failed at step {k}: {err}")
                    break

                if isinstance(raw_act, dict):
                    act_vec = np.array([
                        float(raw_act.get("thrust", 0.0)),
                        float(raw_act.get("moment_x", 0.0)),
                        float(raw_act.get("moment_y", 0.0)),
                        float(raw_act.get("moment_z", 0.0)),
                    ], dtype=np.float64)
                elif isinstance(raw_act, (list, tuple, np.ndarray)):
                    act_vec = np.array(raw_act[:4], dtype=np.float64)
                else:
                    tampered = True
                    errors.append(f"Controller returned invalid action type at step {k}: {type(raw_act)}")
                    break

                rec_act = np.array(actions[k], dtype=np.float64)
                diff = float(np.max(np.abs(act_vec - rec_act)))
                if diff > max_action_diff:
                    max_action_diff = diff

                if diff > 1e-6:
                    tampered = True
                    errors.append(
                        f"Action mismatch at step {k}: observed action differs from recorded action (max diff: {diff:.2e})"
                    )
                    break
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if lease is not None:
                try:
                    lease.remove()
                except Exception:
                    pass

        details["max_action_diff"] = max_action_diff
        details["steps_verified"] = steps

        passed = len(errors) == 0 and not tampered
        return TierResult(
            level="L2",
            name="Controller Determinism",
            passed=passed,
            status="PASS" if passed else "FAIL",
            tampered=tampered,
            details=details,
            errors=errors,
        )

    def verify_l3(self, record: dict[str, Any]) -> TierResult:
        errors: list[str] = []
        details: dict[str, Any] = {}
        tampered = False

        cleanup_ok = record.get("cleanup_succeeded")
        verdicts_cleanup = record.get("verdicts", {}).get("cleanup_status")
        if cleanup_ok is not True or verdicts_cleanup != "SUCCEEDED":
            errors.append(
                f"Containment cleanup status failed: cleanup_succeeded={cleanup_ok}, cleanup_status={verdicts_cleanup}"
            )

        event_sec = record.get("event_log", {})
        events = event_sec.get("events", [])
        trusted_events_count = 0
        for idx, ev in enumerate(events):
            src = ev.get("source")
            if src != "trusted_host":
                tampered = True
                errors.append(f"Untrusted event source at event {idx}: {src}")
            else:
                trusted_events_count += 1

            ev_type = ev.get("event_type", "")
            if "breach" in ev_type.lower() or "violation" in ev_type.lower() or "leak" in ev_type.lower():
                errors.append(f"Containment violation event detected: {ev_type}")

        details["trusted_events_count"] = trusted_events_count

        spec = record.get("spec", {})
        mission_duration_s = float(spec.get("mission_duration_s", 10.0))
        scenario = record.get("scenario", {})
        duration_s = float(scenario.get("duration_s", 0.0))
        if duration_s > mission_duration_s + 0.5:
            errors.append(
                f"Execution duration {duration_s:.3f}s exceeded spec mission budget {mission_duration_s:.3f}s"
            )

        verdicts = record.get("verdicts", {})
        cont_status = verdicts.get("containment_status")
        if cont_status not in ("POLICY_CONFIRMED", "PARTIAL", "NOT_TESTED"):
            errors.append(f"Invalid containment status: {cont_status}")

        details["containment_status"] = cont_status
        details["cleanup_status"] = verdicts_cleanup

        passed = len(errors) == 0 and not tampered
        return TierResult(
            level="L3",
            name="Containment Audit",
            passed=passed,
            status="PASS" if passed else "FAIL",
            tampered=tampered,
            details=details,
            errors=errors,
        )


def verify_court_record_cli(args: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Domnir Portable Court Record Multi-Tier Independent Verifier"
    )
    parser.add_argument("record_pos", nargs="?", help="Path to Court Record JSON file")
    parser.add_argument("--record", "-r", dest="record_opt", help="Path to Court Record JSON file")
    parser.add_argument("--model-path", "-m", help="Path to MuJoCo cf2.xml model")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose verification details")
    parser.add_argument(
        "--trusted-key",
        action="append",
        default=[],
        help=(
            "Pinned Ed25519 public key (base64), or a JSON file saved from GET /provenance/keys. "
            "Repeatable. Mission records signed by a pinned key are reported as AUTHENTIC."
        ),
    )

    parsed = parser.parse_args(args)
    target_path = parsed.record_opt or parsed.record_pos

    if not target_path:
        sys.stderr.write("Error: Court record file path is required. Use --record <path> or positional argument.\n")
        return 2

    p = Path(target_path)
    if not p.is_file():
        sys.stderr.write(f"Error: File not found: {p}\n")
        return 2

    try:
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as err:
        sys.stderr.write(f"Error: Invalid JSON in {p}: {err}\n")
        return 2
    except Exception as err:
        sys.stderr.write(f"Error reading {p}: {err}\n")
        return 2

    try:
        key_values = [
            Path(v).read_text(encoding="utf-8") if Path(v).is_file() else v
            for v in parsed.trusted_key
        ]
        trusted = parse_trusted_keys(key_values)
    except (ValueError, KeyError, json.JSONDecodeError) as err:
        sys.stderr.write(f"Error: invalid --trusted-key: {err}\n")
        return 2

    if isinstance(data, dict) and data.get("schema_version") == MISSION_SCHEMA_VERSION:
        return _verify_mission_record_cli(data, parsed, trusted_keys=trusted)

    verifier = CourtRecordVerifier(model_path=parsed.model_path, trusted_keys=trusted)
    report = verifier.verify(data)

    if parsed.json:
        print(report.model_dump_json(indent=2))
    else:
        status_str = "PASS" if report.verified else ("TAMPERED" if report.tampered else "FAIL")
        print("=" * 60)
        print("DOMNIR COURT RECORD VERIFICATION REPORT")
        print(f"Record ID:      {report.record_id or 'unknown'}")
        print(f"Experiment ID:  {report.experiment_id or 'unknown'}")
        print(f"Overall Result: {status_str}")
        print(f"Authenticity:   {report.authenticity} (signer key {report.signer_key_id or 'none'})")
        if report.authenticity == "SIGNED_UNTRUSTED_KEY":
            print("                Integrity checks passed, but the signing key is not pinned.")
            print("                Pass --trusted-key with the issuer's public key to authenticate the record.")
        print("=" * 60)
        for lvl in ("L0", "L1", "L2", "L3"):
            if lvl in report.tiers:
                t = report.tiers[lvl]
                tier_status = "PASS" if t.passed else ("TAMPERED" if t.tampered else "FAIL")
                print(f"[{lvl}] {t.name}: {tier_status}")
                if parsed.verbose or not t.passed:
                    for err in t.errors:
                        print(f"     - ERROR: {err}")
                    if parsed.verbose:
                        for k, v in t.details.items():
                            print(f"     * {k}: {v}")

        if report.tamper_details:
            print("\nTAMPERING DETECTED:")
            for item in report.tamper_details:
                print(f"  ! {item}")
        print("=" * 60)
        print(f"Summary: {report.summary}")
        print("=" * 60)

    if report.verified and not report.tampered:
        return 0
    return 1


def _verify_mission_record_cli(data: dict[str, Any], parsed: argparse.Namespace, trusted_keys: dict[str, str] | None = None) -> int:
    model_path = resolve_model_path(parsed.model_path)
    if model_path is None:
        sys.stderr.write("Error: MuJoCo cf2.xml model not found. Use --model-path.\n")
        return 2
    if trusted_keys is None:
        try:
            key_values = [
                Path(v).read_text(encoding="utf-8") if Path(v).is_file() else v
                for v in parsed.trusted_key
            ]
            trusted_keys = parse_trusted_keys(key_values)
        except (ValueError, KeyError, json.JSONDecodeError) as err:
            sys.stderr.write(f"Error: invalid --trusted-key: {err}\n")
            return 2
    result = verify_mission_court_record(data, model_path=model_path, trusted_keys=trusted_keys)
    if parsed.json:
        print(json.dumps(result, indent=2))
    else:
        print("=" * 60)
        print("DOMNIR MISSION COURT RECORD VERIFICATION REPORT")
        print(f"Record ID:      {result.get('record_id') or 'unknown'}")
        print(f"Mission ID:     {result.get('experiment_id') or 'unknown'}")
        print(f"Overall Result: {'PASS' if result['verified'] else 'FAIL'}")
        print(f"Replay:         {result['replay_verdict']} (max diff {result['replay_max_abs_difference']:.2e})")
        print(f"Authenticity:   {result['authenticity']} (signer key {result['signer_key_id'] or 'none'})")
        if result["authenticity"] == "SIGNED_UNTRUSTED_KEY":
            print("                Integrity checks passed, but the signing key is not pinned.")
            print("                Pass --trusted-key with the issuer's public key to authenticate the record.")
        print("=" * 60)
        for name, ok in result["checks"].items():
            print(f"[{'PASS' if ok else 'FAIL'}] {name}")
        for err in result["errors"]:
            print(f"     - ERROR: {err}")
        print("=" * 60)
    return 0 if result["verified"] else 1


def main() -> None:
    sys.exit(verify_court_record_cli())


if __name__ == "__main__":
    main()
