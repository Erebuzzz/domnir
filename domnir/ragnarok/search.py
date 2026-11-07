"""Ragnarok adaptive adversarial search engine for automated controller falsification."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence
from pydantic import BaseModel, Field

from domnir.contracts.stl import SafetyContract, STLRobustnessResult
from domnir.scenario import ScenarioParameter, calculate_applied_disturbance


@dataclass(frozen=True)
class RagnarokSearchSpace:
    alt_min_m: float
    alt_max_m: float
    force_min_n: float
    force_max_n: float
    pulse_start_min_s: float = 0.0
    pulse_start_max_s: float = 0.20
    pulse_duration_min_s: float = 0.0
    pulse_duration_max_s: float = 0.15

    @classmethod
    def from_contract(cls, contract: SafetyContract) -> RagnarokSearchSpace:
        # Keep initial altitude strictly within safety floor and ceiling
        margin_z = 0.02
        alt_min = contract.min_allowed_altitude_m + margin_z
        alt_max = max(alt_min + 0.01, contract.target_altitude_m * 1.5)
        alt_max = min(alt_max, contract.max_allowed_altitude_m - margin_z)

        force_min = getattr(contract, "disturbance_force_z_min", -0.05)
        force_max = getattr(contract, "disturbance_force_z_max", 0.05)
        if force_min >= force_max:
            force_min, force_max = -0.05, 0.05

        return cls(
            alt_min_m=alt_min,
            alt_max_m=alt_max,
            force_min_n=force_min,
            force_max_n=force_max,
            pulse_start_min_s=0.05,
            pulse_start_max_s=max(0.06, contract.mission_duration_s * 0.6),
            pulse_duration_min_s=0.02,
            pulse_duration_max_s=max(0.03, contract.mission_duration_s * 0.3),
        )

    def clamp(self, vec: list[float]) -> list[float]:
        return [
            max(self.alt_min_m, min(self.alt_max_m, vec[0])),
            max(self.force_min_n, min(self.force_max_n, vec[1])),
            max(self.pulse_start_min_s, min(self.pulse_start_max_s, vec[2])),
            max(self.pulse_duration_min_s, min(self.pulse_duration_max_s, vec[3])),
        ]

    def point_to_scenario(self, point: Sequence[float]) -> ScenarioParameter:
        p0 = max(0.0, min(1.0, float(point[0])))
        p1 = max(0.0, min(1.0, float(point[1])))
        p2 = max(0.0, min(1.0, float(point[2])))
        p3 = max(0.0, min(1.0, float(point[3])))
        return ScenarioParameter(
            initial_altitude_m=self.alt_min_m + p0 * (self.alt_max_m - self.alt_min_m),
            disturbance_force_z=self.force_min_n + p1 * (self.force_max_n - self.force_min_n),
            pulse_start_s=self.pulse_start_min_s + p2 * (self.pulse_start_max_s - self.pulse_start_min_s),
            pulse_duration_s=self.pulse_duration_min_s + p3 * (self.pulse_duration_max_s - self.pulse_duration_min_s),
        )

    def random_sample(self, rng: random.Random) -> ScenarioParameter:
        return ScenarioParameter(
            initial_altitude_m=rng.uniform(self.alt_min_m, self.alt_max_m),
            disturbance_force_z=rng.uniform(self.force_min_n, self.force_max_n),
            pulse_start_s=rng.uniform(self.pulse_start_min_s, self.pulse_start_max_s),
            pulse_duration_s=rng.uniform(self.pulse_duration_min_s, self.pulse_duration_max_s),
        )


def generate_sobol_points(n_points: int, dimension: int = 4, seed: int = 42) -> list[list[float]]:
    """Generate authentic 4D low-discrepancy Sobol sequence with Cranley-Patterson shift."""
    L = 32
    dim = min(4, max(1, dimension))
    V = [[0] * L for _ in range(4)]

    # Direction numbers (Joe & Kuo)
    for j in range(L):
        V[0][j] = 1 << (31 - j)

    m1 = [1] * L
    for j in range(1, L):
        m1[j] = (2 * m1[j - 1]) ^ m1[j - 1]
    for j in range(L):
        V[1][j] = (m1[j] << (31 - j)) & 0xFFFFFFFF

    m2 = [1, 3] + [0] * (L - 2)
    for j in range(2, L):
        m2[j] = (m2[j - 1] << 1) ^ (m2[j - 2] << 2) ^ m2[j - 2]
    for j in range(L):
        V[2][j] = (m2[j] << (31 - j)) & 0xFFFFFFFF

    m3 = [1, 3, 7] + [0] * (L - 3)
    for j in range(3, L):
        m3[j] = (m3[j - 1] << 1) ^ (m3[j - 3] << 3) ^ m3[j - 3]
    for j in range(L):
        V[3][j] = (m3[j] << (31 - j)) & 0xFFFFFFFF

    shift_rng = random.Random(seed)
    shift = [shift_rng.random() for _ in range(dim)]

    points: list[list[float]] = []
    X = [0] * 4
    for i in range(1, n_points + 1):
        c = 0
        val = i - 1
        while val & 1:
            val >>= 1
            c += 1
        c = min(c, L - 1)
        pt: list[float] = []
        for d in range(dim):
            X[d] ^= V[d][c]
            base_val = X[d] / (1 << 32)
            shifted = (base_val + shift[d]) % 1.0
            pt.append(shifted)
        points.append(pt)
    return points


@dataclass(frozen=True)
class FalsificationCandidate:
    candidate_id: str
    iteration: int
    scenario: ScenarioParameter
    robustness: float
    satisfied: bool
    critical_predicate: str
    critical_time_s: float


@dataclass(frozen=True)
class FalsificationCampaignResult:
    strategy: str
    evaluations_count: int
    first_violation_iteration: int | None
    violations_found: int
    min_robustness: float
    best_scenario: ScenarioParameter
    critical_witness: FalsificationCandidate | None
    all_candidates: list[FalsificationCandidate] = field(default_factory=list)
    summary: str = ""
    invalid_evaluations_count: int = 0


# Evaluator function signature: takes a scenario proposal and returns the STL robustness result
ScenarioEvaluator = Callable[[ScenarioParameter], STLRobustnessResult]


class UniformRandomFalsifier:
    """Pure uniform pseudorandom search policy (Monte Carlo baseline)."""

    def __init__(self, search_space: RagnarokSearchSpace, seed: int = 42) -> None:
        self.search_space = search_space
        self.rng = random.Random(seed)

    def run(self, evaluator: ScenarioEvaluator, max_evaluations: int = 25) -> FalsificationCampaignResult:
        candidates: list[FalsificationCandidate] = []
        first_violation: int | None = None
        min_rho = float("inf")
        best_scenario: ScenarioParameter | None = None
        witness: FalsificationCandidate | None = None
        violations_count = 0
        invalids_count = 0

        for i in range(max_evaluations):
            scenario = self.search_space.random_sample(self.rng)
            res = evaluator(scenario)

            candidate = FalsificationCandidate(
                candidate_id=f"uniform-{i:03d}",
                iteration=i + 1,
                scenario=scenario,
                robustness=res.min_robustness,
                satisfied=res.satisfied,
                critical_predicate=res.critical_predicate,
                critical_time_s=res.critical_timestamp_s,
            )
            candidates.append(candidate)

            is_valid_result = getattr(res, "is_valid", True) and res.verdict != "INVALID"

            if is_valid_result and res.min_robustness < min_rho:
                min_rho = res.min_robustness
                best_scenario = scenario

            if is_valid_result and res.verdict == "VIOLATED":
                violations_count += 1
                if first_violation is None:
                    first_violation = i + 1
                    witness = candidate
            elif not is_valid_result:
                invalids_count += 1

        summary = (
            f"Uniform Random evaluated {max_evaluations} scenarios. "
            f"Found {violations_count} violations (min robustness: {min_rho:.4f})."
        )
        if first_violation is not None:
            summary += f" First violation detected at iteration {first_violation}."
        else:
            summary += " Not falsified within evaluation budget."

        return FalsificationCampaignResult(
            strategy="uniform_random",
            evaluations_count=max_evaluations,
            first_violation_iteration=first_violation,
            violations_found=violations_count,
            min_robustness=min_rho if min_rho != float("inf") else 0.0,
            best_scenario=best_scenario or self.search_space.random_sample(self.rng),
            critical_witness=witness,
            all_candidates=candidates,
            summary=summary,
            invalid_evaluations_count=invalids_count,
        )


class SobolBaselineFalsifier:
    """Authentic low-discrepancy Sobol quasi-random sequence baseline search policy."""

    def __init__(self, search_space: RagnarokSearchSpace, seed: int = 42) -> None:
        self.search_space = search_space
        self.seed = seed

    def run(self, evaluator: ScenarioEvaluator, max_evaluations: int = 25) -> FalsificationCampaignResult:
        candidates: list[FalsificationCandidate] = []
        first_violation: int | None = None
        min_rho = float("inf")
        best_scenario: ScenarioParameter | None = None
        witness: FalsificationCandidate | None = None
        violations_count = 0
        invalids_count = 0

        sobol_pts = generate_sobol_points(max_evaluations, dimension=4, seed=self.seed)

        for i, pt in enumerate(sobol_pts):
            scenario = self.search_space.point_to_scenario(pt)
            res = evaluator(scenario)

            candidate = FalsificationCandidate(
                candidate_id=f"sobol-{i:03d}",
                iteration=i + 1,
                scenario=scenario,
                robustness=res.min_robustness,
                satisfied=res.satisfied,
                critical_predicate=res.critical_predicate,
                critical_time_s=res.critical_timestamp_s,
            )
            candidates.append(candidate)

            is_valid_result = getattr(res, "is_valid", True) and res.verdict != "INVALID"

            if is_valid_result and res.min_robustness < min_rho:
                min_rho = res.min_robustness
                best_scenario = scenario

            if is_valid_result and res.verdict == "VIOLATED":
                violations_count += 1
                if first_violation is None:
                    first_violation = i + 1
                    witness = candidate
            elif not is_valid_result:
                invalids_count += 1

        summary = (
            f"Sobol Quasi-Random evaluated {max_evaluations} scenarios. "
            f"Found {violations_count} violations (min robustness: {min_rho:.4f})."
        )
        if first_violation is not None:
            summary += f" First violation detected at iteration {first_violation}."
        else:
            summary += " Not falsified within evaluation budget."

        default_scen = self.search_space.point_to_scenario(sobol_pts[0]) if sobol_pts else ScenarioParameter(0.1, 0.0)
        return FalsificationCampaignResult(
            strategy="sobol_quasi_random",
            evaluations_count=max_evaluations,
            first_violation_iteration=first_violation,
            violations_found=violations_count,
            min_robustness=min_rho if min_rho != float("inf") else 0.0,
            best_scenario=best_scenario or default_scen,
            critical_witness=witness,
            all_candidates=candidates,
            summary=summary,
            invalid_evaluations_count=invalids_count,
        )


class DifferentialEvolutionFalsifier:
    """Adaptive Differential Evolution (DE) search policy minimizing robustness."""

    def __init__(
        self,
        search_space: RagnarokSearchSpace,
        *,
        population_size: int = 8,
        f_mutation: float = 0.65,
        cr_crossover: float = 0.70,
        seed: int = 42,
    ) -> None:
        self.search_space = search_space
        self.pop_size = max(4, population_size)
        self.f_mutation = f_mutation
        self.cr_crossover = cr_crossover
        self.rng = random.Random(seed)

    def run(self, evaluator: ScenarioEvaluator, max_evaluations: int = 30) -> FalsificationCampaignResult:
        # 1. Initialize population
        pop: list[list[float]] = []
        fitness: list[float] = []
        candidates: list[FalsificationCandidate] = []
        eval_count = 0
        first_violation: int | None = None
        witness: FalsificationCandidate | None = None
        violations_count = 0
        invalids_count = 0

        for i in range(self.pop_size):
            scenario = self.search_space.random_sample(self.rng)
            res = evaluator(scenario)
            eval_count += 1
            rho = res.min_robustness

            cand = FalsificationCandidate(
                candidate_id=f"de-init-{i:03d}",
                iteration=eval_count,
                scenario=scenario,
                robustness=rho,
                satisfied=res.satisfied,
                critical_predicate=res.critical_predicate,
                critical_time_s=res.critical_timestamp_s,
            )
            candidates.append(cand)
            pop.append(scenario.to_vector())
            fitness.append(rho)

            is_valid_result = getattr(res, "is_valid", True) and res.verdict != "INVALID"

            if is_valid_result and res.verdict == "VIOLATED":
                violations_count += 1
                if first_violation is None:
                    first_violation = eval_count
                    witness = cand
            elif not is_valid_result:
                invalids_count += 1

            if eval_count >= max_evaluations:
                break

        # 2. Evolutionary loop
        while eval_count < max_evaluations:
            for i in range(self.pop_size):
                if eval_count >= max_evaluations:
                    break

                # Mutation: pick 3 distinct individuals different from i
                indices = [idx for idx in range(self.pop_size) if idx != i]
                r1, r2, r3 = self.rng.sample(indices, 3)

                # Mutant vector v = x_r1 + F * (x_r2 - x_r3)
                mutant = [
                    pop[r1][d] + self.f_mutation * (pop[r2][d] - pop[r3][d])
                    for d in range(4)
                ]

                # Binomial crossover
                trial = [
                    mutant[d] if self.rng.random() < self.cr_crossover or d == self.rng.randint(0, 3)
                    else pop[i][d]
                    for d in range(4)
                ]

                clamped_trial = self.search_space.clamp(trial)
                trial_scenario = ScenarioParameter.from_vector(clamped_trial)

                res = evaluator(trial_scenario)
                eval_count += 1
                trial_rho = res.min_robustness

                cand = FalsificationCandidate(
                    candidate_id=f"de-gen-{eval_count:03d}",
                    iteration=eval_count,
                    scenario=trial_scenario,
                    robustness=trial_rho,
                    satisfied=res.satisfied,
                    critical_predicate=res.critical_predicate,
                    critical_time_s=res.critical_timestamp_s,
                )
                candidates.append(cand)

                is_valid_result = getattr(res, "is_valid", True) and res.verdict != "INVALID"

                # Objective is minimization of robustness (finding hardest violation)
                if is_valid_result and trial_rho <= fitness[i]:
                    pop[i] = clamped_trial
                    fitness[i] = trial_rho

                if is_valid_result and res.verdict == "VIOLATED":
                    violations_count += 1
                    if first_violation is None:
                        first_violation = eval_count
                        witness = cand
                elif not is_valid_result:
                    invalids_count += 1

        best_idx = min(range(len(fitness)), key=lambda idx: fitness[idx])
        min_rho = fitness[best_idx]
        best_scenario = ScenarioParameter.from_vector(pop[best_idx])

        summary = (
            f"Differential Evolution completed {eval_count} evaluations. "
            f"Found {violations_count} violations (min robustness: {min_rho:.4f})."
        )
        if first_violation is not None:
            summary += f" First violation detected at iteration {first_violation}."
        else:
            summary += " Not falsified within evaluation budget."

        return FalsificationCampaignResult(
            strategy="differential_evolution",
            evaluations_count=eval_count,
            first_violation_iteration=first_violation,
            violations_found=violations_count,
            min_robustness=min_rho if min_rho != float("inf") else 0.0,
            best_scenario=best_scenario,
            critical_witness=witness,
            all_candidates=candidates,
            summary=summary,
            invalid_evaluations_count=invalids_count,
        )


def compare_falsification_policies(
    search_space: RagnarokSearchSpace,
    evaluator: ScenarioEvaluator,
    evaluations_budget: int = 20,
    seed: int = 42,
) -> dict[str, Any]:
    """Empirically compare adaptive DE search vs Sobol and uniform random baselines on identical budget."""
    uniform = UniformRandomFalsifier(search_space, seed=seed)
    uniform_res = uniform.run(evaluator, max_evaluations=evaluations_budget)

    sobol = SobolBaselineFalsifier(search_space, seed=seed)
    sobol_res = sobol.run(evaluator, max_evaluations=evaluations_budget)

    de = DifferentialEvolutionFalsifier(search_space, seed=seed)
    de_res = de.run(evaluator, max_evaluations=evaluations_budget)

    # Calculate empirical discovery efficiency
    sobol_first = sobol_res.first_violation_iteration or (evaluations_budget + 1)
    de_first = de_res.first_violation_iteration or (evaluations_budget + 1)

    speedup = (sobol_first / de_first) if de_first > 0 else 1.0

    return {
        "budget": evaluations_budget,
        "uniform_random": {
            "strategy": uniform_res.strategy,
            "evaluations": uniform_res.evaluations_count,
            "first_violation": uniform_res.first_violation_iteration,
            "violations_found": uniform_res.violations_found,
            "min_robustness": uniform_res.min_robustness,
            "summary": uniform_res.summary,
        },
        "sobol": {
            "strategy": sobol_res.strategy,
            "evaluations": sobol_res.evaluations_count,
            "first_violation": sobol_res.first_violation_iteration,
            "violations_found": sobol_res.violations_found,
            "min_robustness": sobol_res.min_robustness,
            "summary": sobol_res.summary,
        },
        "differential_evolution": {
            "strategy": de_res.strategy,
            "evaluations": de_res.evaluations_count,
            "first_violation": de_res.first_violation_iteration,
            "violations_found": de_res.violations_found,
            "min_robustness": de_res.min_robustness,
            "summary": de_res.summary,
        },
        "discovery_efficiency_ratio": round(speedup, 3),
        "falsification_achieved": de_res.violations_found > 0 or sobol_res.violations_found > 0 or uniform_res.violations_found > 0,
    }
