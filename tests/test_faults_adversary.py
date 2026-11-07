"""Tests for Capability C: Admissible Environmental Disturbances and Fault Injection."""

from pathlib import Path
import pytest

from domnir.controls.baseline_3d import Baseline3DController
from domnir.faults import (
    ActuatorFaultSchedule,
    FaultInjector,
    MissionFaultSchedule,
    SensorFaultSchedule,
    WindGust3D,
)
from domnir.missions import (
    MissionConstraints,
    MissionSpecV2,
    MissionStage,
    MissionStageKind,
    run_mission_simulation,
)
from domnir.worlds import open_field_world


MODEL_PATH = Path("domnir/.cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")
if not MODEL_PATH.exists():
    MODEL_PATH = Path(".cache/mujoco_menagerie/bitcraze_crazyflie_2/cf2.xml")


def test_fault_injector_wind_vector():
    gust1 = WindGust3D(force_x_n=0.05, force_y_n=-0.02, start_s=0.10, duration_s=0.20)
    gust2 = WindGust3D(force_x_n=0.03, force_z_n=0.01, start_s=0.20, duration_s=0.20)
    schedule = MissionFaultSchedule(wind_gusts=[gust1, gust2])
    injector = FaultInjector(schedule)

    assert injector.get_applied_wind_force_n(0.05) == [0.0, 0.0, 0.0]
    # At t=0.15, only gust1 is active
    assert injector.get_applied_wind_force_n(0.15) == [0.05, -0.02, 0.0]
    # At t=0.25, both gust1 and gust2 are active
    assert injector.get_applied_wind_force_n(0.25) == [0.08, -0.02, 0.01]
    # At t=0.35, only gust2 is active
    assert injector.get_applied_wind_force_n(0.35) == [0.03, 0.0, 0.01]
    # At t=0.45, neither is active
    assert injector.get_applied_wind_force_n(0.45) == [0.0, 0.0, 0.0]


def test_sensor_fault_injection_bias_and_noise():
    sf = SensorFaultSchedule(
        bias_pos_m=[0.05, -0.02, 0.01],
        noise_pos_std_m=0.005,
        start_s=0.10,
        duration_s=0.50,
    )
    schedule = MissionFaultSchedule(sensor_faults=[sf])
    injector = FaultInjector(schedule, seed=123)

    raw_obs = {
        "position_m": [0.0, 0.0, 0.20],
        "velocity_mps": [0.0, 0.0, 0.0],
    }

    # Before start_s
    obs_clean = injector.apply_sensor_faults(raw_obs, 0.05)
    assert obs_clean["position_m"] == [0.0, 0.0, 0.20]

    # During fault: biased and noisy
    obs_faulted = injector.apply_sensor_faults(raw_obs, 0.20)
    assert abs(obs_faulted["position_m"][0] - 0.05) < 0.03
    assert abs(obs_faulted["position_m"][1] - (-0.02)) < 0.03
    # Original true observation is untouched
    assert raw_obs["position_m"] == [0.0, 0.0, 0.20]


def test_actuator_derating_multipliers():
    af = ActuatorFaultSchedule(
        thrust_multiplier=0.60,
        moment_multiplier=0.80,
        start_s=0.20,
        duration_s=0.30,
    )
    schedule = MissionFaultSchedule(actuator_faults=[af])
    injector = FaultInjector(schedule)

    clean_act = (0.26, 0.10, -0.10, 0.05)
    # Outside active window
    derated_early = injector.apply_actuator_derating(clean_act, 0.10)
    assert derated_early == clean_act

    # Inside active window
    derated_active = injector.apply_actuator_derating(clean_act, 0.30)
    assert derated_active[0] == pytest.approx(0.26 * 0.60)
    assert derated_active[1] == pytest.approx(0.10 * 0.80)
    assert derated_active[2] == pytest.approx(-0.10 * 0.80)
    assert derated_active[3] == pytest.approx(0.05 * 0.80)


def test_wind_gust_adversary_deflects_trajectory_and_replays():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    stages = [
        MissionStage(
            id="hover",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.0, 0.0, 0.20],
            completion_deadline_s=0.40,
        )
    ]
    spec = MissionSpecV2(
        mission_id="wind-test",
        stages=stages,
        constraints=MissionConstraints(
            min_altitude_m=0.05,
            max_altitude_m=0.50,
            max_tilt_deg=60.0,
        ),
    )
    world = open_field_world()
    ctrl = Baseline3DController()

    # 1. Baseline simulation without wind
    res_clean = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.0, 0.0, 0.20],
    )

    # 2. Simulation with lateral wind gust pushing in +X direction
    wind = WindGust3D(force_x_n=0.06, start_s=0.05, duration_s=0.20)
    faults = MissionFaultSchedule(wind_gusts=[wind])
    res_wind = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.0, 0.0, 0.20],
        faults=faults,
    )

    # Lateral displacement in +X must be measurably higher under wind
    max_x_clean = max(step["position_m"][0] for step in res_clean.trajectory)
    max_x_wind = max(step["position_m"][0] for step in res_wind.trajectory)
    assert max_x_wind > max_x_clean + 0.02

    # Deterministic replay with wind must reproduce state trajectory
    assert res_wind.replay_matched is True


def test_actuator_failure_falsifies_altitude_safety():
    if not MODEL_PATH.exists():
        pytest.skip(f"MuJoCo cf2.xml model not found at {MODEL_PATH}")

    stages = [
        MissionStage(
            id="hover",
            kind=MissionStageKind.WAYPOINT,
            target_position_m=[0.0, 0.0, 0.25],
            completion_deadline_s=0.40,
        )
    ]
    spec = MissionSpecV2(
        mission_id="thrust-loss-test",
        stages=stages,
        constraints=MissionConstraints(min_altitude_m=0.10),
    )
    world = open_field_world()
    ctrl = Baseline3DController()

    # Severe motor failure derating thrust by 75%
    derate = ActuatorFaultSchedule(thrust_multiplier=0.25, start_s=0.05, duration_s=0.35)
    faults = MissionFaultSchedule(actuator_faults=[derate])

    res = run_mission_simulation(
        MODEL_PATH,
        spec,
        world,
        lambda obs: ctrl.compute_action(obs),
        initial_pos_m=[0.0, 0.0, 0.25],
        faults=faults,
    )

    assert res.evaluation.physical_verdict == "FALSIFIED"
    assert "altitude_floor" in res.evaluation.summary
    assert res.replay_matched is True
