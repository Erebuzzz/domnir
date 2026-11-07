"""Unit tests for the research benchmark suite (Stage J)."""

import json
from pathlib import Path
import pytest
from domnir.benchmark import (
    BENCHMARK_CONTROLLERS,
    make_analytical_evaluator,
    run_benchmark_suite,
)
from domnir.contracts.stl import SafetyContract
from domnir.ragnarok.search import ScenarioParameter


def test_benchmark_controllers_syntax_and_executability():
    contract = SafetyContract()
    for name, code in BENCHMARK_CONTROLLERS.items():
        eval_fn = make_analytical_evaluator(code, contract)
        scenario = ScenarioParameter(initial_altitude_m=0.10, disturbance_force_z=0.0)
        res = eval_fn(scenario)
        assert res.verdict in ("SATISFIED", "VIOLATED")
        assert isinstance(res.min_robustness, float)


def test_run_benchmark_suite_execution():
    report = run_benchmark_suite(budget=8, seeds=[42])

    assert len(report.search_results) == 2
    assert len(report.minimization_results) >= 1
    assert len(report.uncertainty_results) >= 1
    assert len(report.guardian_results) >= 2
    assert report.ci_gate_status in ("RELEASE_APPROVED", "AWAITING_REVIEW")
    assert report.mean_search_speedup > 0.0

    # Serialization test
    report_dict = report.to_dict()
    assert "search_benchmarks" in report_dict
    assert "guardian_benchmarks" in report_dict
    assert "mean_search_speedup" in report_dict


def test_guardian_benchmarks_in_report():
    report = run_benchmark_suite(budget=6, seeds=[42])
    # Open loop weak should violate unshielded but be shielded or mitigated
    weak_res = next(r for r in report.guardian_results if r.controller_name == "open_loop_weak")
    assert weak_res.unshielded_verdict == "VIOLATED"
    assert weak_res.interventions_count > 0


def test_zero_em_dashes_in_benchmark_files():
    benchmark_path = Path("domnir/benchmark.py")
    test_path = Path("tests/test_benchmark.py")

    for path in (benchmark_path, test_path):
        content = path.read_text(encoding="utf-8")
        assert "\u2014" not in content, f"Em dash found in {path}"
        assert "\u2013" not in content, f"En dash found in {path}"
