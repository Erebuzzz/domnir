"""Unit tests for Counterexample Minimizer."""

import pytest
from domnir.contracts.stl import STLRobustnessResult
from domnir.ragnarok.minimize import CounterexampleMinimizer
from domnir.ragnarok.search import ScenarioParameter


def test_minimizer_rejects_passing_scenario():
    minimizer = CounterexampleMinimizer()
    passing_scenario = ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=0.0)

    def passing_eval(s: ScenarioParameter) -> STLRobustnessResult:
        return STLRobustnessResult(
            satisfied=True,
            verdict="SATISFIED",
            min_robustness=0.05,
            critical_timestamp_s=0.20,
            critical_step_index=100,
            critical_predicate="tracking",
            critical_actual_value=0.10,
            critical_threshold=0.05,
            summary="Passing trace",
            timeline=[],
        )

    with pytest.raises(ValueError, match="Cannot minimize a passing scenario"):
        minimizer.minimize(passing_scenario, passing_eval)


def test_minimizer_reduces_disturbance_magnitude():
    minimizer = CounterexampleMinimizer(target_altitude_m=0.10)
    # Severe original disturbance: F_z = -0.20 N
    original = ScenarioParameter(
        initial_altitude_m=0.10,
        disturbance_force_z=-0.20,
        pulse_start_s=0.05,
        pulse_duration_s=0.10,
    )

    # Physical boundary: violation occurs whenever F_z <= -0.06 N
    def mock_evaluator(s: ScenarioParameter) -> STLRobustnessResult:
        violation = s.disturbance_force_z <= -0.06
        rho = s.disturbance_force_z - (-0.06)
        return STLRobustnessResult(
            satisfied=not violation,
            verdict="VIOLATED" if violation else "SATISFIED",
            min_robustness=rho,
            critical_timestamp_s=0.12,
            critical_step_index=60,
            critical_predicate="floor",
            critical_actual_value=0.04,
            critical_threshold=0.05,
            summary="Boundary evaluator",
            timeline=[],
        )

    res = minimizer.minimize(original, mock_evaluator)
    assert res.predicate_preserved is True
    # The disturbance force magnitude should be reduced significantly closer to -0.06 N
    assert res.minimized_scenario.disturbance_force_z > original.disturbance_force_z
    assert abs(res.minimized_scenario.disturbance_force_z) < abs(original.disturbance_force_z)
    assert res.minimized_cost < res.original_cost
    assert res.cost_reduction_ratio > 0.0
    assert res.evaluations_used > 1
