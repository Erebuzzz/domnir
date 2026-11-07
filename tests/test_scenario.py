"""Unit tests for ScenarioParameter and disturbance force pulse schedule."""

import math
import pytest
from domnir.scenario import ScenarioParameter, calculate_applied_disturbance


def test_scenario_parameter_creation_and_defaults():
    sp = ScenarioParameter()
    assert sp.initial_altitude_m == 0.10
    assert sp.disturbance_force_z == 0.0
    assert sp.pulse_start_s == 0.0
    assert sp.pulse_duration_s == 0.0


def test_scenario_parameter_custom_and_bounds():
    sp = ScenarioParameter(
        initial_altitude_m=0.15,
        disturbance_force_z=-0.05,
        pulse_start_s=0.08,
        pulse_duration_s=0.04,
    )
    assert sp.initial_altitude_m == 0.15
    assert sp.disturbance_force_z == -0.05
    assert sp.pulse_start_s == 0.08
    assert sp.pulse_duration_s == 0.04

    # Negative altitude invalid
    with pytest.raises(Exception):
        ScenarioParameter(initial_altitude_m=-0.1)

    # Negative pulse start invalid
    with pytest.raises(Exception):
        ScenarioParameter(pulse_start_s=-0.05)


def test_scenario_vector_and_dict_serialization():
    sp = ScenarioParameter(
        initial_altitude_m=0.12,
        disturbance_force_z=0.03,
        pulse_start_s=0.05,
        pulse_duration_s=0.02,
    )
    vec = sp.to_vector()
    assert len(vec) == 4
    assert vec == [0.12, 0.03, 0.05, 0.02]

    restored = ScenarioParameter.from_vector(vec)
    assert restored.initial_altitude_m == 0.12
    assert restored.disturbance_force_z == 0.03
    assert restored.pulse_start_s == 0.05
    assert restored.pulse_duration_s == 0.02

    d = sp.to_dict()
    assert d["disturbance_force_z"] == 0.03
    restored_dict = ScenarioParameter.from_dict(d)
    assert restored_dict == sp

    # Also supports legacy vertical_disturbance_n key
    legacy_d = {"initial_altitude_m": 0.15, "vertical_disturbance_n": -0.04}
    legacy_sp = ScenarioParameter.from_dict(legacy_d)
    assert legacy_sp.disturbance_force_z == -0.04


def test_calculate_applied_disturbance_continuous_fallback():
    # Legacy scenario with pulse_start_s=0.0 and pulse_duration_s=0.0
    sp = ScenarioParameter(disturbance_force_z=-0.05, pulse_start_s=0.0, pulse_duration_s=0.0)
    assert calculate_applied_disturbance(sp, 0.0) == -0.05
    assert calculate_applied_disturbance(sp, 0.10) == -0.05
    assert calculate_applied_disturbance(sp, 0.40) == -0.05


def test_calculate_applied_disturbance_pulse_schedule():
    # Pulse from t=0.10s to t=0.15s (duration 0.05s)
    sp = ScenarioParameter(
        disturbance_force_z=-0.08,
        pulse_start_s=0.10,
        pulse_duration_s=0.05,
    )
    # Before pulse
    assert calculate_applied_disturbance(sp, 0.0) == 0.0
    assert calculate_applied_disturbance(sp, 0.099) == 0.0

    # During pulse
    assert calculate_applied_disturbance(sp, 0.10) == -0.08
    assert calculate_applied_disturbance(sp, 0.12) == -0.08
    assert calculate_applied_disturbance(sp, 0.149) == -0.08

    # After pulse
    assert calculate_applied_disturbance(sp, 0.15) == 0.0
    assert calculate_applied_disturbance(sp, 0.20) == 0.0


def test_calculate_applied_disturbance_non_finite_time():
    sp = ScenarioParameter(disturbance_force_z=-0.05, pulse_start_s=0.0, pulse_duration_s=0.0)
    assert calculate_applied_disturbance(sp, float("nan")) == 0.0
    assert calculate_applied_disturbance(sp, float("inf")) == 0.0


def test_non_overlapping_pulse_schedules_produce_different_force_profiles():
    # T05: Two legal pulse schedules with equal force produce different force traces
    sp1 = ScenarioParameter(disturbance_force_z=-0.05, pulse_start_s=0.05, pulse_duration_s=0.05)
    sp2 = ScenarioParameter(disturbance_force_z=-0.05, pulse_start_s=0.15, pulse_duration_s=0.05)

    timesteps = [i * 0.002 for i in range(100)]
    trace1 = [calculate_applied_disturbance(sp1, t) for t in timesteps]
    trace2 = [calculate_applied_disturbance(sp2, t) for t in timesteps]

    assert trace1 != trace2
    # At t=0.06s (step 30), trace1 is active and trace2 is zero
    assert trace1[30] == -0.05
    assert trace2[30] == 0.0
    # At t=0.16s (step 80), trace1 is zero and trace2 is active
    assert trace1[80] == 0.0
    assert trace2[80] == -0.05
