"""Stage deadline semantics for MissionProgressTracker and MissionSafetyMonitor.

A stage only counts as COMPLETED if its arrival condition (and dwell) is met
at or before its deadline. Late arrivals, stalls and missed landings must all
end in TIMED_OUT/ABORTED and a NOT_COMPLETED mission verdict.
"""

import pytest
from pydantic import ValidationError

from domnir.missions import (
    MAX_MISSION_STAGES,
    MissionProgressTracker,
    MissionSpecV2,
    MissionStage,
    MissionStageKind,
    StageStatus,
    StageTimeoutPolicy,
)
from domnir.safety.mission_monitor import MissionSafetyMonitor
from domnir.worlds import open_field_world

TARGET = [0.0, 0.0, 0.20]
AWAY = [1.0, 1.0, 1.0]
STILL = [0.0, 0.0, 0.0]


def _waypoint(stage_id, deadline, target=TARGET, dwell=0.0):
    return MissionStage(
        id=stage_id,
        kind=MissionStageKind.WAYPOINT,
        target_position_m=target,
        tolerance_m=0.05,
        dwell_s=dwell,
        completion_deadline_s=deadline,
    )


def _spec(stages, policy=StageTimeoutPolicy.ABORT):
    return MissionSpecV2(mission_id="deadline-test", stages=stages, stage_timeout_policy=policy)


def _statuses(tracker):
    return [(s["stage_id"], s["status"]) for s in tracker.stage_history]


def _evaluate(spec, history):
    trajectory = [{
        "step_index": 0,
        "sim_time_s": 0.0,
        "position_m": [0.0, 0.0, 0.5],
        "velocity_mps": STILL,
        "orientation_quat_wxyz": [1.0, 0.0, 0.0, 0.0],
        "active_stage_id": spec.stages[0].id,
    }]
    return MissionSafetyMonitor.evaluate(spec, open_field_world(), trajectory, [], history)


def test_late_arrival_is_timed_out_not_completed():
    spec = _spec([_waypoint("w", 0.10)])
    tracker = MissionProgressTracker(spec)

    res = tracker.update(0.20, 100, TARGET, STILL)

    assert res["deadline_exceeded"] is True
    assert res["is_completed"] is False
    assert _statuses(tracker) == [("w", "TIMED_OUT")]
    assert "completed_at_s" not in tracker.stage_history[0]
    evaluation = _evaluate(spec, tracker.finalize(0.20))
    assert evaluation.mission_verdict == "NOT_COMPLETED"
    assert evaluation.stages_completed == 0
    assert evaluation.total_stages == 1
    assert "TIMED_OUT" in evaluation.mission_failure_reason


def test_arrival_exactly_at_deadline_counts_with_float_drift():
    spec = _spec([_waypoint("w", 0.80)])
    tracker = MissionProgressTracker(spec)
    # 400 MuJoCo steps of 0.002 s accumulate to 0.8000000000000003, not 0.8.
    t = 0.0
    for _ in range(400):
        t += 0.002
    assert t > 0.80

    res = tracker.update(t, 400, TARGET, STILL)

    assert res["is_completed"] is True
    assert _statuses(tracker) == [("w", "COMPLETED")]
    evaluation = _evaluate(spec, tracker.finalize(t))
    assert evaluation.mission_verdict == "COMPLETED"
    assert evaluation.stages_completed == 1


def test_arrival_one_step_after_deadline_times_out():
    spec = _spec([_waypoint("w", 0.80)])
    tracker = MissionProgressTracker(spec)

    tracker.update(0.802, 401, TARGET, STILL)

    assert _statuses(tracker) == [("w", "TIMED_OUT")]


def test_dwell_must_finish_before_deadline():
    spec = _spec([_waypoint("w", 0.10, dwell=0.05)])
    tracker = MissionProgressTracker(spec)
    # In the region from t=0.08 but dwell would only complete at t=0.13.
    t = 0.08
    while t < 0.14:
        tracker.update(t, int(t / 0.01), TARGET, STILL, dt_s=0.01)
        t += 0.01

    assert _statuses(tracker) == [("w", "TIMED_OUT")]


def test_stalled_stage_aborts_later_stages_under_abort_policy():
    spec = _spec([_waypoint("a", 0.10), _waypoint("b", 0.20, target=[0.5, 0.0, 0.2]), _waypoint("c", 0.30)])
    tracker = MissionProgressTracker(spec)

    tracker.update(0.05, 25, AWAY, STILL)
    tracker.update(0.12, 60, AWAY, STILL)
    # Reaching later targets after an abort changes nothing.
    tracker.update(0.15, 75, [0.5, 0.0, 0.2], STILL)
    tracker.finalize(0.30)

    assert _statuses(tracker) == [("a", "TIMED_OUT"), ("b", "ABORTED"), ("c", "ABORTED")]
    assert tracker.is_aborted is True
    assert tracker.stages_completed == 0


def test_advance_policy_moves_on_and_judges_each_stage():
    spec = _spec(
        [_waypoint("a", 0.10), _waypoint("b", 0.30, target=[0.5, 0.0, 0.2])],
        policy=StageTimeoutPolicy.ADVANCE,
    )
    tracker = MissionProgressTracker(spec)

    tracker.update(0.12, 60, AWAY, STILL)  # a times out, b becomes active
    tracker.update(0.20, 100, [0.5, 0.0, 0.2], STILL)  # b reached on time
    evaluation = _evaluate(spec, tracker.finalize(0.30))

    assert _statuses(tracker) == [("a", "TIMED_OUT"), ("b", "COMPLETED")]
    assert evaluation.stages_completed == 1
    assert evaluation.mission_verdict == "NOT_COMPLETED"


def test_landing_without_pad_contact_times_out_at_flight_end():
    pad = [1.15, 0.0, 0.02]
    spec = _spec([
        _waypoint("approach", 0.20, target=[1.15, 0.0, 0.10]),
        MissionStage(
            id="touchdown",
            kind=MissionStageKind.LANDING,
            target_position_m=pad,
            tolerance_m=0.25,
            dwell_s=0.0,
            completion_deadline_s=0.50,
        ),
    ])
    tracker = MissionProgressTracker(spec)

    tracker.update(0.10, 50, [1.15, 0.0, 0.10], STILL)
    # Over the pad but never touching it; the final step is before the deadline.
    tracker.update(0.498, 249, pad, STILL, pad_contact=False)
    history = tracker.finalize(0.50)

    assert _statuses(tracker) == [("approach", "COMPLETED"), ("touchdown", "TIMED_OUT")]
    assert "Flight ended" in history[1]["reason"]
    evaluation = _evaluate(spec, history)
    assert evaluation.mission_verdict == "NOT_COMPLETED"
    assert evaluation.stages_completed == 1
    assert evaluation.total_stages == 2


def test_finalize_records_unreached_stages_as_aborted():
    spec = _spec([_waypoint("a", 0.10), _waypoint("b", 0.20)])
    tracker = MissionProgressTracker(spec)

    tracker.update(0.05, 25, AWAY, STILL)
    tracker.finalize(0.08)
    tracker.finalize(0.08)  # idempotent

    assert _statuses(tracker) == [("a", "TIMED_OUT"), ("b", "ABORTED")]


def test_monitor_rejects_completed_status_recorded_after_deadline():
    # Defence in depth: even a hand-built history claiming COMPLETED is not
    # counted if completed_at_s is past the stage deadline.
    spec = _spec([_waypoint("w", 0.10)])
    history = [{
        "stage_id": "w",
        "stage_index": 0,
        "kind": "waypoint",
        "entered_at_s": 0.0,
        "status": "COMPLETED",
        "completed_at_s": 0.25,
    }]

    evaluation = _evaluate(spec, history)

    assert evaluation.mission_verdict == "NOT_COMPLETED"
    assert evaluation.stages_completed == 0


def test_monitor_requires_an_outcome_for_every_stage():
    spec = _spec([_waypoint("a", 0.10), _waypoint("b", 0.20)])
    history = [{"stage_id": "a", "status": "COMPLETED", "completed_at_s": 0.05}]

    evaluation = _evaluate(spec, history)

    assert evaluation.mission_verdict == "NOT_COMPLETED"
    assert evaluation.stages_completed == 1


def test_stage_deadlines_must_be_non_decreasing():
    with pytest.raises(ValidationError, match="non-decreasing"):
        _spec([_waypoint("a", 0.50), _waypoint("b", 0.20)])


def test_stage_count_is_capped():
    stages = [_waypoint(f"s{i}", 0.1 * (i + 1)) for i in range(MAX_MISSION_STAGES + 1)]
    with pytest.raises(ValidationError):
        _spec(stages)


def test_stage_status_values_are_the_documented_set():
    assert {s.value for s in StageStatus} == {"ENTERED", "COMPLETED", "TIMED_OUT", "ABORTED"}
