"""Measure the built-in baseline on a default mission and report deadline margins.

The default Gauntlet deadlines (domnir/missions/defaults.py) are meant to be
achievable by the trusted baseline with margin. This script flies the same
course with every deadline relaxed, records when the baseline actually
reaches each stage, and compares that with the configured deadlines.

The same check works for any registered world with --world (default
ragnarok-gauntlet).

Usage:
    python scripts/calibrate_gauntlet.py [--world WORLD_ID] [--model-path PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domnir.controls import Baseline3DController  # noqa: E402
from domnir.missions import run_mission_simulation  # noqa: E402
from domnir.missions.defaults import default_mission  # noqa: E402
from domnir.worlds import get_world  # noqa: E402

RELAXED_STEP_S = 5.0


def measure(model_path: Path, world_id: str = "ragnarok-gauntlet") -> dict:
    mission, init_pos = default_mission(world_id)
    world = get_world(world_id)

    relaxed = mission.model_copy(deep=True)
    for i, stage in enumerate(relaxed.stages):
        stage.completion_deadline_s = RELAXED_STEP_S * (i + 1)
    relaxed = type(mission).model_validate(relaxed.model_dump())

    ctrl = Baseline3DController()
    free = run_mission_simulation(model_path, relaxed, world, lambda o: ctrl.compute_action(o), initial_pos_m=init_pos)
    ctrl = Baseline3DController()
    actual = run_mission_simulation(model_path, mission, world, lambda o: ctrl.compute_action(o), initial_pos_m=init_pos)

    rows = []
    for stage, measured in zip(mission.stages, free.evaluation.stage_results):
        arrival = measured.get("completed_at_s")
        rows.append({
            "stage_id": stage.id,
            "baseline_arrival_s": None if arrival is None else round(arrival, 3),
            "deadline_s": stage.completion_deadline_s,
            "margin_s": None if arrival is None else round(stage.completion_deadline_s - arrival, 3),
            "margin_pct": None if not arrival else round(100 * (stage.completion_deadline_s - arrival) / arrival, 1),
        })
    pad_contacts = [c for c in actual.contacts if c.contact_class == "allowed-touchdown"]
    return {
        "world_id": world_id,
        "total_stages": len(mission.stages),
        "stages": rows,
        "default_mission_verdict": actual.evaluation.mission_verdict,
        "default_physical_verdict": actual.evaluation.physical_verdict,
        "default_stages_completed": actual.evaluation.stages_completed,
        "pad_contacts": len(pad_contacts),
        "max_touchdown_speed_mps": max((c.impact_velocity_mps for c in pad_contacts), default=None),
        "obstacle_contacts": sum(1 for c in actual.contacts if c.contact_class == "obstacle"),
        "min_robustness": actual.evaluation.min_robustness,
        "critical_predicate": actual.evaluation.critical_predicate,
        "final_position_m": [round(v, 4) for v in actual.trajectory[-1]["position_m"]],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-path", default=".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
    parser.add_argument("--world", default="ragnarok-gauntlet")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    model_path = Path(args.model_path)
    if not model_path.is_file():
        print(f"Model not found: {model_path}", file=sys.stderr)
        return 2
    report = measure(model_path, args.world)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"{'stage':22s} {'arrival':>9s} {'deadline':>9s} {'margin':>8s}")
        for r in report["stages"]:
            arrival = "-" if r["baseline_arrival_s"] is None else f"{r['baseline_arrival_s']:.3f}s"
            margin = "-" if r["margin_s"] is None else f"{r['margin_s']:+.3f}s ({r['margin_pct']}%)"
            print(f"{r['stage_id']:22s} {arrival:>9s} {r['deadline_s']:>8.2f}s {margin}")
        print(f"default mission: {report['default_mission_verdict']} "
              f"({report['default_stages_completed']}/{report['total_stages']}), physical {report['default_physical_verdict']}, "
              f"pad contacts {report['pad_contacts']}, obstacle contacts {report['obstacle_contacts']}")
    ok = report["default_mission_verdict"] == "COMPLETED" and all(
        r["margin_s"] is not None and r["margin_s"] > 0 for r in report["stages"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
