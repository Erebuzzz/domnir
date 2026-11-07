# Dómnir V3: Integration Ledger

| Task ID | Owner | Branch / Worktree | Touched Paths | Tests Executed | Reviewer | Status |
|---|---|---|---|---|---|---|
| G0-PREFLIGHT | O0 | main | `docs/audits/G0_BASELINE.md`, `docs/audits/TASK_GRAPH.md` | `pytest --collect-only` (213 tests), `pytest -q` (202 pass, 11 skip) | A8 | ACCEPTED |
| SEC-01 | A1 | main | `domnir/evaluator.py`, `domnir/verify.py`, `domnir/ci/gate.py`, `domnir/guardian/supervisor.py`, `domnir/uncertainty/simulator.py`, `domnir/benchmark.py`, `tests/test_security.py` | `tests/test_security.py` (15 passed), `tests/test_verify_cli.py` (12 passed), `tests/test_benchmark.py` (4 passed) | A8 | ACCEPTED |
| SEM-01 | A2 | main | `domnir/contracts/stl.py`, `tests/test_contracts.py` | `tests/test_contracts.py` (12 passed) | A8 | ACCEPTED |
| PHY-01 | A2 | main | `domnir/scenario.py`, `tests/test_scenario.py`, `domnir/ragnarok/search.py`, `tests/test_ragnarok_search.py` | `tests/test_scenario.py` (7 passed), `tests/test_ragnarok_search.py` (5 passed) | A8 | ACCEPTED |
| API-01 | A5 | main | `domnir/api/models.py`, `domnir/api/jobs.py`, `domnir/api/app.py`, `domnir/api/security.py`, `domnir/court_record.py`, `domnir/inference/vultr.py`, `tests/test_court_record.py` | `tests/test_court_record.py` (25 passed), `tests/test_api.py` (23 passed), `tests/test_ragnarok_api.py` (3 passed) | A1, A8 | ACCEPTED |
| GATE-G1 | O0 | main | Wave 1 closure and baseline verification | `pytest -q` (216 passed, 11 skipped, 0 failures) | A8 | SIGNED OFF |
| SEARCH-01 | A3 | main | `domnir/ragnarok/search.py`, `domnir/benchmark.py`, `tests/test_ragnarok_search.py`, `tests/test_benchmark.py` | `tests/test_ragnarok_search.py` (8 passed), `tests/test_benchmark.py` (4 passed) | A8 | ACCEPTED |
| MINI-01 | A3 | main | `domnir/ragnarok/minimize.py`, `tests/test_ragnarok_minimize.py` | `tests/test_ragnarok_minimize.py` (3 passed) | A2, A8 | ACCEPTED |
| EVD-01 | A6 | main | `domnir/verify.py`, `domnir/court_record.py`, `tests/test_verify_cli.py`, `tests/test_court_record.py` | `tests/test_verify_cli.py` (12 passed), `tests/test_court_record.py` (25 passed) | A1, A8 | ACCEPTED |
| UNC-01 | A7 | main | `domnir/uncertainty/simulator.py`, `domnir/guardian/supervisor.py`, `tests/test_uncertainty.py`, `tests/test_guardian.py` | `tests/test_uncertainty.py` (10 passed), `tests/test_guardian.py` (10 passed) | A2, A8 | ACCEPTED |
| GATE-G2 | O0 | main | Wave 2 closure and research benchmark verification | `pytest -q` (220 passed, 11 skipped, 0 failures) | A8 | SIGNED OFF |
| REPAIR-01 | A4 | main | `domnir/ragnarok/repair.py`, `domnir/ragnarok/arena.py`, `tests/test_ragnarok_repair.py`, `tests/test_ragnarok_arena.py` | `tests/test_ragnarok_repair.py` (3 passed), `tests/test_ragnarok_arena.py` (3 passed) | A8 | ACCEPTED |
| GATE-G3 | O0 | main | Wave 3 closure and 12-step co-evolution arena loop | `pytest -q` (223 passed, 11 skipped, 0 failures) | A8 | SIGNED OFF |
| UI-01 | A7 | main | `domnir/web/app.js`, `domnir/web/styles.css` | `tests/test_web.py` (27 passed) | A8 | ACCEPTED |
| ORACLE-01 | A7 | main | `domnir/web/app.js`, `domnir/web/index.html` | `tests/test_web.py` (27 passed) | A6, A8 | ACCEPTED |
| CI-01 | A6 | main | `domnir/ci/gate.py`, `tests/test_ci_gate.py` | `tests/test_ci_gate.py` (9 passed) | A5, A8 | ACCEPTED |
| GATE-G4 | O0 | main | Wave 4 closure (UI, Oracle, and Robotics CI Gate) | `pytest -q` (225 passed, 11 skipped, 0 failures) | A8 | SIGNED OFF |
| G5-PROD | O0 | main | Full integration, production proof & release gate | `pytest -q` (225 passed, 11 skipped, 0 failures), `docs/audits/G5_PRODUCTION_PROOF.md` | A8 | SIGNED OFF |
