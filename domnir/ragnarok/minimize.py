"""Counterexample minimization and critical-event reduction engine."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable
from domnir.contracts.stl import STLRobustnessResult
from .search import ScenarioParameter


@dataclass(frozen=True)
class MinimizationResult:
    original_scenario: ScenarioParameter
    minimized_scenario: ScenarioParameter
    original_robustness: float
    minimized_robustness: float
    original_cost: float
    minimized_cost: float
    cost_reduction_ratio: float
    evaluations_used: int
    predicate_preserved: bool
    summary: str


class CounterexampleMinimizer:
    """1-minimal coordinate reduction engine for physical counterexample scenarios."""

    def __init__(
        self,
        *,
        target_altitude_m: float = 0.10,
        max_evaluations: int = 25,
        tolerance: float = 0.005,
    ) -> None:
        self.target_altitude_m = target_altitude_m
        self.max_evaluations = max_evaluations
        self.tolerance = tolerance

    def compute_cost(self, s: ScenarioParameter) -> float:
        # Cost penalizes disturbance energy and displacement from nominal target
        force_penalty = abs(s.disturbance_force_z) * max(0.01, s.pulse_duration_s)
        disp_penalty = abs(s.initial_altitude_m - self.target_altitude_m) * 0.25
        return float(force_penalty + disp_penalty)

    def minimize(
        self,
        scenario: ScenarioParameter,
        evaluator: Callable[[ScenarioParameter], STLRobustnessResult],
    ) -> MinimizationResult:
        baseline_res = evaluator(scenario)
        if baseline_res.satisfied:
            raise ValueError(
                "Cannot minimize a passing scenario. Minimization requires a failing counterexample."
            )

        target_predicate = baseline_res.critical_predicate
        original_cost = self.compute_cost(scenario)
        curr = scenario
        curr_res = baseline_res
        eval_count = 1

        # Coordinate Reduction Phase 1: Disturbance Magnitude Reduction
        # Binary search towards zero disturbance while preserving violation
        f_low = 0.0
        f_high = curr.disturbance_force_z

        for _ in range(8):
            if eval_count >= self.max_evaluations:
                break
            f_mid = (f_low + f_high) / 2.0
            if abs(f_high - f_mid) < self.tolerance:
                break

            cand = ScenarioParameter(
                initial_altitude_m=curr.initial_altitude_m,
                disturbance_force_z=f_mid,
                pulse_start_s=curr.pulse_start_s,
                pulse_duration_s=curr.pulse_duration_s,
            )
            res = evaluator(cand)
            eval_count += 1

            if not res.satisfied and res.critical_predicate == target_predicate:
                # Still violates: can reduce further towards 0
                f_high = f_mid
                curr = cand
                curr_res = res
            else:
                # Passes or changed predicate: reduction went too far
                f_low = f_mid

        # Coordinate Reduction Phase 2: Pulse Duration Reduction
        if curr.pulse_duration_s > 0.01:
            dur_low = 0.0
            dur_high = curr.pulse_duration_s

            for _ in range(6):
                if eval_count >= self.max_evaluations:
                    break
                dur_mid = (dur_low + dur_high) / 2.0
                if abs(dur_high - dur_mid) < 0.005:
                    break

                cand = ScenarioParameter(
                    initial_altitude_m=curr.initial_altitude_m,
                    disturbance_force_z=curr.disturbance_force_z,
                    pulse_start_s=curr.pulse_start_s,
                    pulse_duration_s=dur_mid,
                )
                res = evaluator(cand)
                eval_count += 1

                if not res.satisfied and res.critical_predicate == target_predicate:
                    dur_high = dur_mid
                    curr = cand
                    curr_res = res
                else:
                    dur_low = dur_mid

        # Coordinate Reduction Phase 3: Initial Altitude Shift towards Target
        alt_curr = curr.initial_altitude_m
        if abs(alt_curr - self.target_altitude_m) > self.tolerance:
            alt_steps = 4
            step_delta = (self.target_altitude_m - alt_curr) / alt_steps

            for step_i in range(1, alt_steps):
                if eval_count >= self.max_evaluations:
                    break
                test_alt = alt_curr + step_delta * step_i
                cand = ScenarioParameter(
                    initial_altitude_m=test_alt,
                    disturbance_force_z=curr.disturbance_force_z,
                    pulse_start_s=curr.pulse_start_s,
                    pulse_duration_s=curr.pulse_duration_s,
                )
                res = evaluator(cand)
                eval_count += 1

                if not res.satisfied and res.critical_predicate == target_predicate:
                    curr = cand
                    curr_res = res
                else:
                    break

        minimized_cost = self.compute_cost(curr)
        reduction_ratio = (
            (original_cost - minimized_cost) / original_cost
            if original_cost > 0.0 else 0.0
        )

        summary = (
            f"1-minimal counterexample found in {eval_count} evaluations. "
            f"Cost reduced from {original_cost:.4f} to {minimized_cost:.4f} "
            f"({reduction_ratio * 100:.1f}% reduction). "
            f"Target predicate '{target_predicate}' maintained with robustness {curr_res.min_robustness:.4f}."
        )

        return MinimizationResult(
            original_scenario=scenario,
            minimized_scenario=curr,
            original_robustness=baseline_res.min_robustness,
            minimized_robustness=curr_res.min_robustness,
            original_cost=original_cost,
            minimized_cost=minimized_cost,
            cost_reduction_ratio=reduction_ratio,
            evaluations_used=eval_count,
            predicate_preserved=curr_res.critical_predicate == target_predicate,
            summary=summary,
        )
