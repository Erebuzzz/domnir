"""Unit tests for Ragnarok adaptive adversarial search engine."""

import pytest
from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.ragnarok.search import (
    DifferentialEvolutionFalsifier,
    RagnarokSearchSpace,
    ScenarioParameter,
    SobolBaselineFalsifier,
    compare_falsification_policies,
)


def test_search_space_initialization_and_bounds():
    contract = SafetyContract(
        target_altitude_m=0.10,
        min_allowed_altitude_m=0.05,
        max_allowed_altitude_m=1.00,
        mission_duration_s=0.40,
    )
    space = RagnarokSearchSpace.from_contract(contract)

    # Initial altitude must be strictly inside safety boundaries
    assert space.alt_min_m > contract.min_allowed_altitude_m
    assert space.alt_max_m < contract.max_allowed_altitude_m

    # Clamping test
    out_of_bounds = [0.01, 10.0, -1.0, 5.0]
    clamped = space.clamp(out_of_bounds)
    assert clamped[0] >= space.alt_min_m
    assert clamped[1] <= space.force_max_n
    assert clamped[2] >= space.pulse_start_min_s
    assert clamped[3] <= space.pulse_duration_max_s


def test_sobol_baseline_sampling():
    contract = SafetyContract()
    space = RagnarokSearchSpace.from_contract(contract)
    sobol = SobolBaselineFalsifier(space, seed=123)

    # Mock evaluator: violates if disturbance force < -0.08 N
    def mock_evaluator(scenario: ScenarioParameter) -> STLRobustnessResult:
        # Distance to failure boundary: force - (-0.08)
        rho = scenario.disturbance_force_z - (-0.08)
        satisfied = rho >= 0.0
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=rho,
            critical_timestamp_s=0.15,
            critical_step_index=75,
            critical_predicate="floor",
            critical_actual_value=scenario.initial_altitude_m,
            critical_threshold=0.05,
            summary="Mock evaluation",
            timeline=[],
        )

    res = sobol.run(mock_evaluator, max_evaluations=15)
    assert res.evaluations_count == 15
    assert len(res.all_candidates) == 15
    # Since force_min_n is -0.15, some samples will be < -0.08
    assert res.violations_found > 0
    assert res.first_violation_iteration is not None
    assert res.critical_witness is not None


def test_differential_evolution_falsification():
    contract = SafetyContract()
    space = RagnarokSearchSpace.from_contract(contract)
    de = DifferentialEvolutionFalsifier(space, population_size=6, seed=42)

    # Mock non-linear landscape: narrow failure region where F_z < -0.10 and altitude < 0.08
    def mock_evaluator(scenario: ScenarioParameter) -> STLRobustnessResult:
        z = scenario.initial_altitude_m
        f = scenario.disturbance_force_z
        # Combined penalty: violates when both altitude is low and force is strongly downward
        rho = (z - 0.075) * 2.0 + (f - (-0.09)) * 4.0
        satisfied = rho >= 0.0
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=rho,
            critical_timestamp_s=0.20,
            critical_step_index=100,
            critical_predicate="floor",
            critical_actual_value=z,
            critical_threshold=0.05,
            summary="DE test evaluation",
            timeline=[],
        )

    res = de.run(mock_evaluator, max_evaluations=20)
    assert res.evaluations_count == 20
    assert res.min_robustness < 0.0
    assert res.violations_found > 0
    assert res.first_violation_iteration is not None


def test_compare_falsification_policies_reporting():
    contract = SafetyContract()
    space = RagnarokSearchSpace.from_contract(contract)

    def mock_evaluator(scenario: ScenarioParameter) -> STLRobustnessResult:
        # Violation when force is negative
        rho = scenario.disturbance_force_z
        satisfied = rho >= 0.0
        return STLRobustnessResult(
            satisfied=satisfied,
            verdict="SATISFIED" if satisfied else "VIOLATED",
            min_robustness=rho,
            critical_timestamp_s=0.10,
            critical_step_index=50,
            critical_predicate="floor",
            critical_actual_value=0.05,
            critical_threshold=0.05,
            summary="Comparison mock",
            timeline=[],
        )

    comp = compare_falsification_policies(space, mock_evaluator, evaluations_budget=12, seed=99)
    assert "budget" in comp
    assert comp["budget"] == 12
    assert "sobol" in comp
    assert "differential_evolution" in comp
    assert "discovery_efficiency_ratio" in comp
    assert comp["falsification_achieved"] is True
