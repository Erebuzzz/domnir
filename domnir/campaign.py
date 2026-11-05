"""Finite synthetic campaigns and conservative evidence summaries."""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

from .replay import INTEGRATION_SIGNATURE

REPLAY_TOLERANCE = 1e-12
ALTITUDE_LIMIT_M = 0.05


def scenario_suite(seed: int) -> list[dict[str, float | str]]:
    rng = random.Random(seed)
    cases: list[dict[str, float | str]] = [
        {"kind": "baseline", "initial_altitude_m": 0.10, "vertical_disturbance_n": 0.0},
        {"kind": "edge", "initial_altitude_m": 0.10, "vertical_disturbance_n": -0.05},
        {"kind": "edge", "initial_altitude_m": 0.15, "vertical_disturbance_n": 0.0},
        {"kind": "edge", "initial_altitude_m": 0.15, "vertical_disturbance_n": -0.05},
    ]
    for _ in range(4):
        cases.append(
            {
                "kind": "seeded_random",
                "initial_altitude_m": rng.uniform(0.10, 0.15),
                "vertical_disturbance_n": rng.uniform(-0.05, 0.0),
            }
        )
    return cases


def build_record(
    seed: int, source_hash: str, entries: list[dict[str, Any]]
) -> dict[str, Any]:
    suite = scenario_suite(seed)
    if len(entries) != len(suite):
        raise ValueError("Campaign entries must account for every scenario")
    matched = 0
    failures = 0
    corrupt = False
    mismatched = False
    violations = []
    model_hashes = None
    runtime_identity = None
    for index, (scenario, entry) in enumerate(zip(suite, entries, strict=True)):
        if entry.get("scenario") != scenario:
            raise ValueError("Scenario order or parameters do not match the suite")
        result = entry.get("result")
        if result is None:
            failures += 1
            if entry.get("cleanup_succeeded") is False:
                corrupt = True
            continue
        try:
            if (
                entry.get("cleanup_succeeded") is not True
                or result["controller_sha256"] != source_hash
            ):
                corrupt = True
                continue
            if (
                result["source_kind"] != "guest_controller"
                or not result["guest_runner_sha256"]
            ):
                corrupt = True
                continue
            if (
                result["initial_altitude_m"] != scenario["initial_altitude_m"]
                or result["vertical_disturbance_n"]
                != scenario["vertical_disturbance_n"]
            ):
                corrupt = True
                continue
            if model_hashes is None:
                model_hashes = result["model_hashes_sha256"]
            if not model_hashes or result["model_hashes_sha256"] != model_hashes:
                corrupt = True
                continue
            identity = (
                result["runtime_version"],
                result["guest_image"],
                result["mujoco_version"],
                result["timestep_s"],
                result["guest_runner_sha256"],
                result["integration_signature"],
            )
            if runtime_identity is None:
                runtime_identity = identity
            if (
                identity != runtime_identity
                or not math.isfinite(identity[3])
                or identity[3] <= 0
                or identity[5] != INTEGRATION_SIGNATURE
            ):
                corrupt = True
                continue
            steps = result["steps"]
            original = np.asarray(result["states"], dtype=np.float64)
            replay = np.asarray(result["replay_states"], dtype=np.float64)
            actions = np.asarray(result["actions"], dtype=np.float64)
            integration = np.asarray(result["integration_states"], dtype=np.float64)
            replay_integration = np.asarray(
                result["replay_integration_states"], dtype=np.float64
            )
            if (
                type(steps) is not int
                or steps != 200
                or original.shape != (steps + 1, 13)
                or replay.shape != original.shape
                or actions.shape != (steps, 4)
                or integration.ndim != 2
                or integration.shape[0] != steps + 1
                or not 14 <= integration.shape[1] <= 4096
                or replay_integration.shape != integration.shape
                or not np.isfinite(original).all()
                or not np.isfinite(replay).all()
                or not np.isfinite(actions).all()
                or not np.isfinite(integration).all()
                or not np.isfinite(replay_integration).all()
            ):
                corrupt = True
                continue
            if (
                original[0, 2] != scenario["initial_altitude_m"]
                or not np.array_equal(integration[:, 1:14], original)
                or not np.array_equal(replay_integration[:, 1:14], replay)
            ):
                corrupt = True
                continue
            maximum = max(
                float(np.max(np.abs(original - replay))),
                float(np.max(np.abs(integration - replay_integration))),
            )
            reported = result["replay_max_abs_difference"]
            if (
                not isinstance(reported, (int, float))
                or not math.isfinite(reported)
                or abs(maximum - reported) > 1e-15
            ):
                corrupt = True
                continue
            if maximum > REPLAY_TOLERANCE:
                mismatched = True
                continue
            matched += 1
            minimum = float(np.min(replay[:, 2]))
            if minimum < ALTITUDE_LIMIT_M:
                violations.append(
                    {
                        "scenario_index": index,
                        "minimum_altitude_m": minimum,
                        "margin_m": minimum - ALTITUDE_LIMIT_M,
                    }
                )
        except (KeyError, TypeError, ValueError, OverflowError):
            corrupt = True

    if corrupt or mismatched:
        finding = "INVALID"
    elif violations:
        finding = "VIOLATION_FOUND"
    elif failures or matched != len(suite):
        finding = "INCONCLUSIVE"
    else:
        finding = "NO_VIOLATION_FOUND"
    replay_status = "DIVERGED" if mismatched else "MATCHED" if matched else "NOT_RUN"
    return {
        "schema_version": "feasibility-2",
        "scope": "synthetic_altitude_campaign",
        "controller_sha256": source_hash,
        "campaign": {
            "seed": seed,
            "scenario_budget": len(suite),
            "completed": matched,
            "failed": failures,
            "scenarios": entries,
        },
        "flight": {
            "finding": finding,
            "altitude_limit_m": ALTITUDE_LIMIT_M,
            "violations": violations,
            "qualification": "INCONCLUSIVE",
        },
        "replay": {
            "status": replay_status,
            "matched_scenarios": matched,
            "tolerance": REPLAY_TOLERANCE,
        },
        "containment": {"status": "NOT_TESTED"},
        "provenance": {
            "status": "INVALID" if corrupt else "INCOMPLETE",
            "reason": "Complete mission provenance and protected event anchoring are not implemented.",
        },
        "limitations": [
            "Synthetic altitude cases only; mission completion was not evaluated.",
            "The actuator model is not physically calibrated.",
            "Finite tests do not prove safety or predict hardware behavior.",
        ],
    }
