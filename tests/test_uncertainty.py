"""Unit tests for plant uncertainty, FIFO actuator latency, sensor noise, and sensitivity analysis."""

from pathlib import Path
import numpy as np
import pytest
from pydantic import ValidationError

from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.spec import GeneratedController
from domnir.uncertainty import (
    ActuatorDelayQueue,
    ParameterizedSuite,
    PlantUncertaintyConfig,
    SensitivityAnalyzer,
    SensitivityMetric,
    UncertaintyReport,
    UncertaintySimulationWrapper,
)


def test_plant_uncertainty_config_defaults_and_custom():
    default_cfg = PlantUncertaintyConfig()
    assert default_cfg.mass_scale == 1.0
    assert default_cfg.thrust_scale == 1.0
    assert default_cfg.drag_scale == 1.0
    assert default_cfg.position_noise_std_m == 0.0
    assert default_cfg.velocity_noise_std_mps == 0.0
    assert default_cfg.actuator_delay_steps == 0
    assert default_cfg.seed == 42

    custom_cfg = PlantUncertaintyConfig(
        mass_scale=1.10,
        thrust_scale=0.90,
        drag_scale=1.20,
        position_noise_std_m=0.01,
        velocity_noise_std_mps=0.03,
        actuator_delay_steps=3,
        seed=123,
    )
    assert custom_cfg.mass_scale == 1.10
    assert custom_cfg.thrust_scale == 0.90
    assert custom_cfg.drag_scale == 1.20
    assert custom_cfg.position_noise_std_m == 0.01
    assert custom_cfg.velocity_noise_std_mps == 0.03
    assert custom_cfg.actuator_delay_steps == 3
    assert custom_cfg.seed == 123


def test_plant_uncertainty_config_validation_bounds():
    # mass_scale: [0.85, 1.20]
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(mass_scale=0.80)
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(mass_scale=1.25)

    # thrust_scale: [0.80, 1.25]
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(thrust_scale=0.75)
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(thrust_scale=1.30)

    # drag_scale: [0.70, 1.50]
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(drag_scale=0.65)
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(drag_scale=1.55)

    # position_noise_std_m: [0.0, 0.05]
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(position_noise_std_m=-0.001)
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(position_noise_std_m=0.06)

    # velocity_noise_std_mps: [0.0, 0.10]
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(velocity_noise_std_mps=-0.01)
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(velocity_noise_std_mps=0.15)

    # actuator_delay_steps: [0, 5]
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(actuator_delay_steps=-1)
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(actuator_delay_steps=6)

    # seed: >= 0
    with pytest.raises(ValidationError):
        PlantUncertaintyConfig(seed=-1)


def test_parameterized_suite_configurations():
    suite = ParameterizedSuite.get_suite()
    assert set(suite.keys()) == {
        "nominal",
        "heavy_payload",
        "battery_depleted",
        "turbulent_drag",
        "noisy_sensors",
        "actuator_latency",
    }

    nom = suite["nominal"]
    assert nom.mass_scale == 1.0
    assert nom.thrust_scale == 1.0
    assert nom.drag_scale == 1.0
    assert nom.position_noise_std_m == 0.0
    assert nom.velocity_noise_std_mps == 0.0
    assert nom.actuator_delay_steps == 0

    heavy = suite["heavy_payload"]
    assert heavy.mass_scale == 1.12
    assert heavy.thrust_scale == 0.96

    battery = suite["battery_depleted"]
    assert battery.thrust_scale == 0.88

    drag = suite["turbulent_drag"]
    assert drag.drag_scale == 1.35

    sensors = suite["noisy_sensors"]
    assert sensors.position_noise_std_m == 0.008
    assert sensors.velocity_noise_std_mps == 0.02

    latency = suite["actuator_latency"]
    assert latency.actuator_delay_steps == 2

    # Direct classmethod calls
    assert ParameterizedSuite.nominal().mass_scale == 1.0
    assert ParameterizedSuite.heavy_payload().mass_scale == 1.12
    assert ParameterizedSuite.battery_depleted().thrust_scale == 0.88
    assert ParameterizedSuite.turbulent_drag().drag_scale == 1.35
    assert ParameterizedSuite.noisy_sensors().position_noise_std_m == 0.008
    assert ParameterizedSuite.actuator_latency().actuator_delay_steps == 2
    assert len(ParameterizedSuite.all_variants()) == 6


def test_actuator_delay_queue_fifo():
    # Test zero delay: pass-through
    q0 = ActuatorDelayQueue(delay_steps=0, action_dim=4)
    assert len(q0) == 0
    action_a = np.array([0.1, 0.2, 0.3, 0.4])
    res0 = q0.push_and_pop(action_a)
    np.testing.assert_array_equal(res0, action_a)

    # Test 2 steps delay
    q2 = ActuatorDelayQueue(delay_steps=2, action_dim=4)
    assert len(q2) == 2

    act1 = np.array([0.1, 0.0, 0.0, 0.0])
    act2 = np.array([0.2, 0.0, 0.0, 0.0])
    act3 = np.array([0.3, 0.0, 0.0, 0.0])
    act4 = np.array([0.4, 0.0, 0.0, 0.0])

    # Step 0: pushes act1, returns default (zeros)
    out0 = q2.push_and_pop(act1)
    np.testing.assert_array_equal(out0, np.zeros(4))
    assert len(q2) == 2

    # Step 1: pushes act2, returns default (zeros)
    out1 = q2.push_and_pop(act2)
    np.testing.assert_array_equal(out1, np.zeros(4))
    assert len(q2) == 2

    # Step 2: pushes act3, returns act1 (delayed by 2 steps)
    out2 = q2.push_and_pop(act3)
    np.testing.assert_array_equal(out2, act1)

    # Step 3: pushes act4, returns act2 (delayed by 2 steps)
    out3 = q2.push_and_pop(act4)
    np.testing.assert_array_equal(out3, act2)

    # Test reset restores default queue
    q2.reset()
    assert len(q2) == 2
    out_after_reset = q2.push_and_pop(act1)
    np.testing.assert_array_equal(out_after_reset, np.zeros(4))


def test_deterministic_seeded_sensor_noise():
    cfg_a = PlantUncertaintyConfig(position_noise_std_m=0.01, velocity_noise_std_mps=0.02, seed=42)
    cfg_b = PlantUncertaintyConfig(position_noise_std_m=0.01, velocity_noise_std_mps=0.02, seed=42)
    cfg_other_seed = PlantUncertaintyConfig(position_noise_std_m=0.01, velocity_noise_std_mps=0.02, seed=999)

    w_a = UncertaintySimulationWrapper(config=cfg_a)
    w_b = UncertaintySimulationWrapper(config=cfg_b)
    w_other = UncertaintySimulationWrapper(config=cfg_other_seed)

    base_obs = {
        "step_index": 5,
        "position_m": [0.0, 0.0, 0.10],
        "velocity_mps": [0.0, 0.0, 0.0],
        "other_field": "preserved",
    }

    obs_a_seq = [w_a.perturb_observation(base_obs) for _ in range(5)]
    obs_b_seq = [w_b.perturb_observation(base_obs) for _ in range(5)]
    obs_other_seq = [w_other.perturb_observation(base_obs) for _ in range(5)]

    # Identical seeds must produce exact identical sequences
    for oa, ob in zip(obs_a_seq, obs_b_seq, strict=True):
        assert oa["position_m"] == ob["position_m"]
        assert oa["velocity_mps"] == ob["velocity_mps"]
        assert oa["other_field"] == "preserved"

    # Different seed must produce different noise values
    assert obs_a_seq[0]["position_m"] != obs_other_seq[0]["position_m"]

    # Zero noise standard deviation leaves observation unchanged
    cfg_zero = PlantUncertaintyConfig(position_noise_std_m=0.0, velocity_noise_std_mps=0.0)
    w_zero = UncertaintySimulationWrapper(config=cfg_zero)
    obs_zero = w_zero.perturb_observation(base_obs)
    assert obs_zero["position_m"] == base_obs["position_m"]
    assert obs_zero["velocity_mps"] == base_obs["velocity_mps"]


def test_process_action_latency_and_thrust_scale():
    cfg = PlantUncertaintyConfig(thrust_scale=0.80, actuator_delay_steps=1)
    wrapper = UncertaintySimulationWrapper(config=cfg)

    act1 = [0.20, 0.0, 0.0, 0.0]
    act2 = [0.30, 0.0, 0.0, 0.0]

    # Step 0: delayed, returns zeros scaled by 0.80 -> 0.0
    out0 = wrapper.process_action(act1)
    np.testing.assert_array_equal(out0, np.zeros(4))

    # Step 1: returns act1 scaled by 0.80 -> 0.16
    out1 = wrapper.process_action(act2)
    assert pytest.approx(out1[0], abs=1e-6) == 0.16
    assert pytest.approx(out1[1], abs=1e-6) == 0.0


def test_sensitivity_analyzer_ranking_and_report_generation():
    contract = SafetyContract(target_altitude_m=0.10)

    # Mock robustness values for each variant
    # nominal: +0.05
    # heavy_payload: -0.04 (causes violation, sens = 0.09)
    # battery_depleted: -0.02 (causes violation, sens = 0.07)
    # turbulent_drag: +0.03 (sens = 0.02)
    # noisy_sensors: +0.04 (sens = 0.01)
    # actuator_latency: +0.01 (sens = 0.04)
    robustness_map = {
        "nominal": 0.05,
        "heavy_payload": -0.04,
        "battery_depleted": -0.02,
        "turbulent_drag": 0.03,
        "noisy_sensors": 0.04,
        "actuator_latency": 0.01,
    }

    def mock_evaluator(ctrl, config, contract, scenario) -> STLRobustnessResult:
        # Match variant based on config properties
        for name, var_cfg in ParameterizedSuite.get_suite().items():
            if (
                var_cfg.mass_scale == config.mass_scale
                and var_cfg.thrust_scale == config.thrust_scale
                and var_cfg.drag_scale == config.drag_scale
                and var_cfg.actuator_delay_steps == config.actuator_delay_steps
                and var_cfg.position_noise_std_m == config.position_noise_std_m
            ):
                rho = robustness_map[name]
                break
        else:
            rho = 0.0

        satisfied = rho >= 0.0
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=rho,
            critical_timestamp_s=0.20,
            critical_step_index=100,
            critical_predicate="floor",
            critical_actual_value=0.08,
            critical_threshold=0.05,
            summary="Mock test evaluation",
            timeline=[],
        )

    analyzer = SensitivityAnalyzer(contract=contract, evaluator=mock_evaluator)
    report = analyzer.analyze("dummy_controller")

    assert isinstance(report, UncertaintyReport)
    assert report.total_variants_evaluated == 6
    assert report.variants_passing == 4
    assert report.variants_failing == 2
    assert report.min_robustness_across_variants == -0.04
    assert report.worst_variant_name == "heavy_payload"
    assert report.most_sensitive_parameter == "heavy_payload"

    # Sensitivities must be sorted descending by sensitivity_coefficient
    sensitivities = report.parameter_sensitivities
    assert len(sensitivities) == 5  # 5 perturbed variants
    coeffs = [m.sensitivity_coefficient for m in sensitivities]
    assert coeffs == sorted(coeffs, reverse=True)

    # First sensitivity should be heavy_payload with sens = 0.09
    assert sensitivities[0].parameter_name == "heavy_payload"
    assert pytest.approx(sensitivities[0].nominal_robustness, abs=1e-5) == 0.05
    assert pytest.approx(sensitivities[0].perturbed_robustness, abs=1e-5) == -0.04
    assert pytest.approx(sensitivities[0].sensitivity_coefficient, abs=1e-5) == 0.09
    assert sensitivities[0].causes_violation is True

    # Second sensitivity should be battery_depleted with sens = 0.07
    assert sensitivities[1].parameter_name == "battery_depleted"
    assert pytest.approx(sensitivities[1].sensitivity_coefficient, abs=1e-5) == 0.07
    assert sensitivities[1].causes_violation is True

    # Third sensitivity should be actuator_latency with sens = 0.04
    assert sensitivities[2].parameter_name == "actuator_latency"
    assert pytest.approx(sensitivities[2].sensitivity_coefficient, abs=1e-5) == 0.04
    assert sensitivities[2].causes_violation is False

    # Check to_dict serialization
    report_dict = report.to_dict()
    assert report_dict["total_variants_evaluated"] == 6
    assert report_dict["worst_variant_name"] == "heavy_payload"
    assert report_dict["most_sensitive_parameter"] == "heavy_payload"
    assert len(report_dict["parameter_sensitivities"]) == 5

    # Check summary content and strict no em dash rule
    assert "heavy_payload" in report.summary
    assert chr(0x2014) not in report.summary


def test_sensitivity_analyzer_with_real_mujoco_and_altitude_controller():
    # Proportional hover controller
    def hover_controller(obs: dict) -> list[float]:
        z = obs["position_m"][2]
        err = 0.10 - z
        thrust = max(0.0, min(0.35, 0.26487 + 0.30 * err))
        return [thrust, 0.0, 0.0, 0.0]

    contract = SafetyContract(
        target_altitude_m=0.10,
        altitude_tolerance_m=0.08,
        min_allowed_altitude_m=0.04,
        max_allowed_altitude_m=0.50,
        mission_duration_s=0.20,
    )

    analyzer = SensitivityAnalyzer(contract=contract)
    report = analyzer.analyze(hover_controller)

    assert report.total_variants_evaluated == 6
    assert report.variants_passing >= 1
    assert report.worst_variant_name in ParameterizedSuite.get_suite()
    assert report.most_sensitive_parameter in ParameterizedSuite.get_suite()
    assert len(report.parameter_sensitivities) == 5
    assert chr(0x2014) not in report.summary


def test_generated_controller_execution_with_wrapper():
    code = (
        "def observe(observation: dict) -> list[float]:\n"
        "    return [0.26, 0.0, 0.0, 0.0]\n"
    )
    ctrl = GeneratedController.from_source(code, model_id="test_model")

    cfg = PlantUncertaintyConfig(mass_scale=1.05, thrust_scale=0.98)
    wrapper = UncertaintySimulationWrapper(config=cfg)

    contract = SafetyContract(settling_time_s=0.02, mission_duration_s=0.05)
    traj = wrapper.run_simulation(ctrl, contract=contract)

    assert len(traj) > 0
    assert "position_m" in traj[0]
    assert "sim_time_s" in traj[0]


def test_no_em_dashes_in_uncertainty_files():
    uncertainty_dir = Path(__file__).resolve().parents[1] / "domnir" / "uncertainty"
    em_dash_char = chr(0x2014)
    for py_file in uncertainty_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert em_dash_char not in content, f"Em dash found in {py_file.name}"
