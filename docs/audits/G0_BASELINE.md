# Preflight Gate G0: Baseline, Test Reproducibility, and Trust Map

## 1. System Inventory and Environment

- Commit SHA: 92b4ae814d1fb4be24e690c54297ea5dbec88056
- Branch: main (origin/main)
- Host OS: Windows 11 AMD64 (Local Development) / Ubuntu 24.04 LTS (Vultr Cloud Compute 45.76.48.77)
- Runtime: Python 3.12.15, Node.js v20.x, MuJoCo 3.3.7, FastAPI 0.115.11, Pydantic 2.11.0, pytest 9.2.0
- Live Deployment Origin: Vultr Cloud Compute (45.76.48.77:8000), systemd service `domnir.service` active
- Edge Observatory: https://domnir.erebuzzz.tech (Cloudflare Workers proxy with custom domain)
- Public API Routes:
  - `/health`: Health status and service identification
  - `/ready`: Hardware virtualization, MuJoCo model, and Vultr Serverless Inference readiness
  - `/models`: Vultr serverless model catalog
  - `/spec/validate`: FlightSpec envelope validation
  - `/controllers/generate`: Vultr Serverless Inference code generation
  - `/experiments/run`: Synchronous or asynchronous trial execution
  - `/experiments/{id}`: Experiment status and artifact retrieval
  - `/ragnarok/falsify`: Adversarial scenario search
  - `/ragnarok/minimize`: Counterexample reduction
  - `/ragnarok/repair`: CEGIS autonomous controller repair
  - `/containment/status`: Host-verified isolation suite status
  - `/containment/run`: Privileged containment audit suite (operator token required)

## 2. Test Suite Collection and Execution Baseline

- Total Collected Tests: 213 test items across 26 test modules
- Executed Locally: 202 passed, 11 skipped, 1 warning, 34 subtests in 19.94s
- Skipped Tests: 11 tests in `tests/test_sandbox.py` requiring local `/dev/kvm` hardware virtualization. These are verified and pass on the Vultr VM.
- Test Modules Inventory:
  - `tests/test_api.py`: 23 tests
  - `tests/test_benchmark.py`: 4 tests
  - `tests/test_campaign.py`: 6 tests
  - `tests/test_ci_gate.py`: 8 tests
  - `tests/test_containment.py`: 3 tests
  - `tests/test_containment_api.py`: 6 tests
  - `tests/test_contracts.py`: 8 tests
  - `tests/test_court_record.py`: 12 tests
  - `tests/test_event_log.py`: 5 tests
  - `tests/test_fixture_trial.py`: 3 tests
  - `tests/test_guardian.py`: 10 tests
  - `tests/test_hover_spike.py`: 5 tests
  - `tests/test_protocol.py`: 15 tests
  - `tests/test_ragnarok_api.py`: 3 tests
  - `tests/test_ragnarok_minimize.py`: 2 tests
  - `tests/test_ragnarok_repair.py`: 3 tests
  - `tests/test_ragnarok_search.py`: 4 tests
  - `tests/test_replay.py`: 7 tests
  - `tests/test_sandbox.py`: 16 tests (5 passed, 11 skipped locally due to /dev/kvm requirement)
  - `tests/test_security.py`: 12 tests
  - `tests/test_simulation.py`: 7 tests
  - `tests/test_spec.py`: 7 tests
  - `tests/test_uncertainty.py`: 10 tests
  - `tests/test_verify_cli.py`: 12 tests
  - `tests/test_vultr_inference.py`: 8 tests
  - `tests/test_web.py`: 26 tests

## 3. Reproduced Critical Findings Audit

### Finding 1: Unsafe Host Execution of Untrusted Controllers
- `domnir/verify.py` line 507: `verify_l2` uses `exec(code_obj, ns)` directly on the host with `__builtins__`.
- `domnir/ci/gate.py` lines 103, 107: `evaluate_revision` executes `exec(compile(ctrl.source_code, "<controller>", "exec"), ns)` on host.
- `domnir/guardian/supervisor.py` line 76: `_compile_controller` executes `exec(code_obj, ns)` on host.
- `domnir/uncertainty/simulator.py` line 211: `simulate_variant` executes `exec(code_obj, ns)` on host.
- `domnir/benchmark.py` line 149: `make_analytical_evaluator` executes `exec(controller_code, {}, local_ns)` on host.
- Impact: Severe trust boundary violation. Anyone supplying controller source via Court Records or CI could achieve remote code execution on the host machine.

### Finding 2: INVALID Experiments Treated as Physical Counterexamples
- `domnir/contracts/stl.py` lines 116-127 and 151-160: When a trajectory is empty, timed out, or non-finite, `STLMonitor.evaluate_trajectory` emits `satisfied=False` with `min_robustness=float("-inf")` and `verdict="INVALID"`.
- `domnir/ragnarok/search.py` lines 143-151 and 272-280: The search loop checks `if not res.satisfied: violations_count += 1` and `if res.min_robustness < min_rho: min_rho = res.min_robustness`.
- Impact: A crashed, timed-out, or unexecutable sandbox evaluation is treated as a successful adversarial falsification witness with -inf robustness, corrupting search statistics and leading to fake counterexamples.

### Finding 3: Disturbance Pulse Timing Ignored by Production MuJoCo Stepping
- `domnir/ragnarok/search.py` lines 14-20: `ScenarioParameter` defines `pulse_start_s` (default 0.05s) and `pulse_duration_s` (default 0.10s).
- `domnir/api/jobs.py` lines 619 and 659: Simulation loop executes `data.xfrc_applied[body_id, 2] = job.vertical_disturbance_n` on every single step without checking `pulse_start_s` or `pulse_duration_s`.
- `domnir/verify.py` line 434: Physics replay executes `data.xfrc_applied[body_id, 2] = disturbance` on every single step.
- Impact: Timed wind gusts or disturbance pulses are modeled as permanent forces, creating physical mismatch between search proposals and simulation execution.

### Finding 4: Ragnarök Endpoints Lack Campaign Resource Quotas and Rate Limits
- `domnir/api/app.py` lines 384, 451, 483: Endpoints `/ragnarok/falsify`, `/ragnarok/minimize`, and `/ragnarok/repair` execute synchronously without rate limiter checks, evaluation timeouts, or visitor resource tracking.
- Impact: Denial of service vulnerability and uncontrolled compute allocation.

### Finding 5: Pseudo-Random Baseline Mislabeled as Sobol Sequence
- `domnir/ragnarok/search.py` lines 113-165: `SobolBaselineFalsifier` calls `self.search_space.random_sample(self.rng)`, which is standard pseudo-random uniform sampling (`random.uniform`).
- Impact: Scientific misrepresentation of quasi-random low-discrepancy sequences.

### Finding 6: Heuristic Actuator Allocation and Scaled Moments
- `domnir/uncertainty/simulator.py` line 163: Multiplies `thrust_scale` across all 4 actuator channels, inadvertently scaling rotational moments.
- `domnir/guardian/supervisor.py` lines 175-183: Uses heuristic guessing based on threshold `max_thrust_n / 4.0 + 0.03` to decide if actions are individual rotor forces or collective thrust.
- Impact: Fragile motor allocation causing incorrect physical behavior when control formats vary.

### Finding 7: Repair Acceptance Permits Hard Safety Violations
- `domnir/ragnarok/repair.py` line 219: `if pass_rate < 0.80: ... continue`. A candidate is accepted if 4 out of 5 holdout tests pass, allowing 1 critical hard safety boundary breach to be accepted.
- Impact: Controller with a known boundary breach can be certified as repaired.
