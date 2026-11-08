"""Calibrated Ragnarök Gauntlet defaults, controller rate (zero-order hold)
and canonical action encoding."""

import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domnir.api.app import app
from domnir.controls import Baseline3DController
from domnir.missions import MissionSpecV2, MissionStage, MissionStageKind, run_mission_simulation
from domnir.missions.simulator import encode_action_payload
from domnir.protocol import InvalidFrame
from domnir.worlds import get_world, open_field_world

MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
needs_model = pytest.mark.skipif(not MODEL_PATH.exists(), reason="MuJoCo cf2.xml model not available")
client = TestClient(app)


@pytest.fixture(scope="module")
def gauntlet():
    resp = client.post("/missions/run", json={"world_id": "ragnarok-gauntlet"})
    assert resp.status_code == 200
    return resp.json()


@needs_model
def test_default_gauntlet_is_completed_by_the_baseline(gauntlet):
    assert gauntlet["physical_verdict"] == "NOT_FALSIFIED"
    assert gauntlet["mission_verdict"] == "COMPLETED"
    assert gauntlet["stages_completed"] == gauntlet["total_stages"] == 5
    assert [s["stage_id"] for s in gauntlet["stage_results"]] == [
        "takeoff", "slalom_pillar", "transit_gate", "approach_pad", "precision_touchdown",
    ]


@needs_model
def test_default_open_field_is_completed_with_margin():
    data = client.post("/missions/run", json={"world_id": "open-field"}).json()
    assert data["mission_verdict"] == "COMPLETED"
    assert data["physical_verdict"] == "NOT_FALSIFIED"
    assert data["stages_completed"] == data["total_stages"] == 3
    for stage in data["stage_results"]:
        assert stage["completion_deadline_s"] - stage["completed_at_s"] >= 0.15, stage["stage_id"]


@needs_model
def test_default_gate_corridor_is_completed_with_margin_and_aperture_geometry():
    data = client.post("/missions/run", json={"world_id": "gate-corridor"}).json()
    assert data["mission_verdict"] == "COMPLETED"
    assert data["physical_verdict"] == "NOT_FALSIFIED"
    assert data["stages_completed"] == data["total_stages"] == 4
    assert [s["stage_id"] for s in data["stage_results"]] == [
        "takeoff", "approach_gate", "transit_gate", "exit_corridor",
    ]
    assert data["contacts_by_class"].get("obstacle", 0) == 0

    # Deadlines must keep >= 20% margin
    for stage in data["stage_results"]:
        margin = stage["completion_deadline_s"] - stage["completed_at_s"]
        margin_pct = 100 * margin / stage["completed_at_s"]
        assert margin_pct >= 20.0, f"{stage['stage_id']} margin {margin_pct:.1f}% is below 20%"

    # Flown trajectory must cross gate plane inside the aperture
    world = get_world("gate-corridor")
    gate = world.get_entity("gate-1")
    gx = gate.pose.position_m[0]
    gy = gate.pose.position_m[1]
    gz = gate.pose.position_m[2]
    half_w = gate.aperture_m[0] / 2.0
    half_h = gate.aperture_m[1] / 2.0

    traj = data["trajectory"]
    crossing = next(
        (b for a, b in zip(traj, traj[1:]) if a["position_m"][0] < gx <= b["position_m"][0]),
        None,
    )
    assert crossing is not None, "Flight never crossed gate x-plane"
    assert abs(crossing["position_m"][1] - gy) < half_w, "Gate crossing y is outside aperture"
    assert abs(crossing["position_m"][2] - gz) < half_h, "Gate crossing z is outside aperture"


@needs_model
def test_default_wind_tunnel_is_completed_with_margin_and_stays_within_walls():
    data = client.post("/missions/run", json={"world_id": "wind-tunnel"}).json()
    assert data["mission_verdict"] == "COMPLETED"
    assert data["physical_verdict"] == "NOT_FALSIFIED"
    assert data["stages_completed"] == data["total_stages"] == 4
    assert [s["stage_id"] for s in data["stage_results"]] == [
        "takeoff", "corridor_entry", "corridor_mid", "corridor_exit",
    ]
    assert data["contacts_by_class"].get("obstacle", 0) == 0

    # Deadlines must keep >= 20% margin
    for stage in data["stage_results"]:
        margin = stage["completion_deadline_s"] - stage["completed_at_s"]
        margin_pct = 100 * margin / stage["completed_at_s"]
        assert margin_pct >= 20.0, f"{stage['stage_id']} margin {margin_pct:.1f}% is below 20%"

    # Flown trajectory must stay strictly within the corridor walls (y = +-0.45, inner face +-0.425)
    world = get_world("wind-tunnel")
    wall_left = world.get_entity("wall-left")
    wall_right = world.get_entity("wall-right")
    inner_left_y = wall_left.pose.position_m[1] - wall_left.dimensions_m[1] / 2.0
    inner_right_y = wall_right.pose.position_m[1] + wall_right.dimensions_m[1] / 2.0

    for pt in data["trajectory"]:
        y = pt["position_m"][1]
        assert inner_right_y < y < inner_left_y, f"Trajectory point y={y:.3f} penetrated corridor wall boundary [{inner_right_y}, {inner_left_y}]"


@needs_model
def test_gauntlet_deadlines_keep_margin_over_the_baseline_flight(gauntlet):
    # Deadlines were set from the measured baseline flight with margin. If
    # the baseline gets slower this fails before the demo silently degrades.
    for stage in gauntlet["stage_results"]:
        margin = stage["completion_deadline_s"] - stage["completed_at_s"]
        assert margin >= 0.2, f"{stage['stage_id']} has only {margin:.3f}s of deadline margin"


@needs_model
def test_gauntlet_touchdown_is_on_the_pad_without_obstacle_contact(gauntlet):
    classes = {c["contact_class"] for c in gauntlet["contacts"]}
    assert "allowed-touchdown" in classes
    assert "obstacle" not in classes
    pad = get_world("ragnarok-gauntlet").get_entity("gauntlet-pad")
    final = gauntlet["trajectory"][-1]["position_m"]
    half = pad.dimensions_m[0] / 2
    assert abs(final[0] - pad.pose.position_m[0]) <= half
    assert abs(final[1] - pad.pose.position_m[1]) <= half
    # Per-class totals cover every contact, not just the capped sample.
    assert sum(gauntlet["contacts_by_class"].values()) == gauntlet["contacts_total"]
    assert gauntlet["contacts_by_class"].get("obstacle", 0) == 0
    touchdowns = [c for c in gauntlet["contacts"] if c["contact_class"] == "allowed-touchdown"]
    assert max(c["impact_velocity_mps"] for c in touchdowns) <= gauntlet["mission"]["constraints"]["max_landing_impact_speed_mps"]


@needs_model
def test_gauntlet_flies_through_the_gate_aperture_and_south_of_the_pillar(gauntlet):
    world = get_world("ragnarok-gauntlet")
    gate = world.get_entity("gauntlet-gate")
    pillar = world.get_entity("slalom-pillar")
    traj = gauntlet["trajectory"]

    crossing = next(
        (b for a, b in zip(traj, traj[1:]) if a["position_m"][0] < gate.pose.position_m[0] <= b["position_m"][0]),
        None,
    )
    assert crossing is not None, "flight never crossed the gate plane"
    gy, gz = gate.pose.position_m[1], gate.pose.position_m[2]
    half_w, half_h = gate.aperture_m[0] / 2, gate.aperture_m[1] / 2
    assert abs(crossing["position_m"][1] - gy) < half_w
    assert abs(crossing["position_m"][2] - gz) < half_h

    near_pillar = [p for p in traj if abs(p["position_m"][0] - pillar.pose.position_m[0]) < 0.05]
    assert near_pillar
    assert all(p["position_m"][1] < pillar.pose.position_m[1] - pillar.dimensions_m[0] / 2 for p in near_pillar)


@needs_model
def test_gauntlet_chart_inputs_come_from_the_mission(gauntlet):
    mission = gauntlet["mission"]
    assert mission["constraints"]["max_altitude_m"] == pytest.approx(1.20)
    assert mission["stages"][-1]["completion_deadline_s"] == pytest.approx(9.0)
    ref = gauntlet["reference_path"]
    assert len(ref) > 10
    assert ref[-1]["position_m"] == pytest.approx([1.15, 0.0, 0.06])


# --- Controller rate (P2-H) ---------------------------------------------------


def _hover_mission(controller_dt_s, mission_id="rate-test"):
    return MissionSpecV2(
        mission_id=mission_id,
        controller_dt_s=controller_dt_s,
        stages=[MissionStage(id="hold", kind=MissionStageKind.WAYPOINT,
                             target_position_m=[0.0, 0.0, 0.10], tolerance_m=0.5, dwell_s=0.0,
                             completion_deadline_s=0.20)],
    )


@needs_model
@pytest.mark.parametrize("controller_dt_s,period", [(0.002, 1), (0.01, 5), (0.02, 10)])
def test_controller_runs_once_per_period_with_zero_order_hold(controller_dt_s, period):
    spec = _hover_mission(controller_dt_s)
    ctrl = Baseline3DController()
    calls = []

    def controller(obs):
        calls.append((obs["step_index"], obs["dt_s"]))
        return ctrl.compute_action(obs)

    res = run_mission_simulation(MODEL_PATH, spec, open_field_world(), controller)

    assert [s for s, _ in calls] == list(range(0, spec.physics_steps, period))
    assert all(dt == pytest.approx(controller_dt_s) for _, dt in calls)
    assert res.controller_invocations == len(calls) == len(res.controller_actions)
    assert res.effective_controller_hz == pytest.approx(1.0 / controller_dt_s)
    # The held action is applied unchanged for every physics step in a period.
    for i in range(0, spec.physics_steps, period):
        block = res.actions[i:i + period]
        assert all(a == block[0] for a in block)
    assert len(res.actions) == spec.physics_steps
    assert res.replay_matched is True


def test_controller_period_must_be_a_whole_number_of_physics_steps():
    with pytest.raises(ValueError, match="whole multiple"):
        _hover_mission(0.003)


# --- Canonical action encoding -----------------------------------------------


def test_dict_actions_are_encoded_with_a_real_json_encoder():
    payload = encode_action_payload({"trial_id": "pilot's run", "thrust": 0.2})
    assert payload == b'{"trial_id":"pilot\'s run","thrust":0.2}'


def test_guest_text_is_validated_byte_for_byte():
    raw = '{"a":1,"a":2}'
    assert encode_action_payload(raw) == raw.encode("utf-8")


def test_non_json_actions_are_rejected_as_invalid_frames():
    with pytest.raises(InvalidFrame):
        encode_action_payload({"thrust": float("nan")})
    with pytest.raises(InvalidFrame):
        encode_action_payload({"thrust": object()})


@needs_model
def test_mission_id_with_apostrophe_flies_normally():
    # The old str(dict).replace("'", '"') encoder corrupted any action whose
    # trial_id contained an apostrophe.
    spec = _hover_mission(0.002, mission_id="pilot's-run")
    ctrl = Baseline3DController()
    res = run_mission_simulation(MODEL_PATH, spec, open_field_world(), lambda o: ctrl.compute_action(o))
    assert res.replay_matched is True
    assert math.isfinite(res.evaluation.min_robustness)
