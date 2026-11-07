# DÓMNIR V3: Multi-Agent Engineering Orchestration, Repair Loop, and Acceptance Protocol

**Input:** Current repository snapshot corresponding to `domnir(3).zip`, root `AGENTS.md`, `docs/DOMNIR_IMPLEMENTATION_PLAN.md`, and `Upgrade_Plan.md`.

**Mission:** Convert Dómnir's newly implemented research modules into one safe, reproducible, scientifically valid system. Preserve existing working code; fix verified defects; integrate and validate the full controller synthesis → isolation → falsification → minimization → repair → retest → independent verification workflow. Do not add promotional or decorative features in lieu of real functionality.

**Source-of-truth rule:** Inspect the actual checked-out repository before acting. Paths and failure descriptions below are audit hypotheses from the supplied V3 snapshot, not permission to blindly edit by line number. Reproduce each issue and adapt if the repository has changed. Do not invent test results, URLs, runtime capabilities, deployment status, citations, physical parameters, or model behavior.

## 0. Non-negotiable invariants

1. **Untrusted code never executes on the trusted host.** Python controller source from an LLM, API user, Court Record, CI invocation, Guardian test, uncertainty test, or adversarial experiment must only run through an approved, constrained sandbox. Static parsing, hashing, and packaging are allowed on the host; `exec`, `eval`, imports of user modules, or subprocess execution of the untrusted program on the host are forbidden. Use a trusted static-analysis path for L0 verification and a sandbox for optional execution-based verification.
2. **Simulation is authoritative for physics.** The untrusted controller proposes actions; a trusted host validates actions, owns MuJoCo state, advances the plant, and measures predicates. Neither an LLM nor a 3D viewer nor the controller can assign a safety verdict.
3. **Three outcomes are different:** `VIOLATED` / `FALSIFIED`, `SATISFIED` / `NOT_FALSIFIED_WITHIN_BUDGET`, and `INVALID` / `INCOMPLETE`. Invalid, truncated, timed-out, or failed sandbox evaluations are never counted as counterexamples, and `NOT_FALSIFIED` never means globally `SAFE`.
4. **Preserve the legacy baseline.** Do not rewrite working modules, rename schemas, upgrade pins, reformat unrelated files, replace evidence history, weaken tests, or change CLI/API contracts unnecessarily. Prefer adapters and migrations. Any modification to a protected trust boundary requires its owner and an independent reviewer to approve the precise diff.
5. **Keep public judge access anonymous but bounded.** Standard experiment workflows need no sign-in. Privileged containment/administrative endpoints require operator authorization. Apply server-side per-request, per-visitor, campaign-level, and global inference/compute budgets. Never trust arbitrary `X-Forwarded-For` headers.
6. **Only Vultr Serverless Inference for hackathon model calls.** No Gemini Robotics ER 2, NVIDIA NIM, or silent alternate-provider fallback.
7. **Scientific claims follow evidence.** Local SHA-256 chain validation is not a digital signature or independent attestation. Action-trace replay within tolerance is not bit-for-bit controller rerun. A selected microVM backend is not independently verified containment. Model uncertainty cannot be claimed if parameter variants were ignored by evaluation.
8. **No fake green checkmarks, tests, records, samples, or animations.** Demo samples must be labeled synthetic. The UI may visualize only recorded trajectories as empirical simulation results.
9. **No infinite autonomous loops.** Every development task and experiment has explicit budgets and stopping criteria. A blocked gate remains blocked until evidence is available.
10. **Existing design remains:** Rune Dawn (warm) and Rune Dusk (cool), realistic Blender/GLB Crazyflie, dual-entry Ragnarok Knowledge Oracle, guided workflow and documentation. UI improvements must not obscure results or increase clutter.

## 1. Operating model: coordinator + specialist agents + independent acceptance

A **Lead Orchestrator (O0)** owns the task graph, branching strategy, integration, evidence ledger, and final sign-off. It delegates to specialists, enforces file ownership, and does not mark its own changes accepted without an independent review.

Agents should use isolated worktrees/branches or similarly isolated change sets. Do not let two agents edit the same file concurrently. A specialist may submit a proposed patch for another agent's owned file; its owner integrates it after review. Maintain a single `INTEGRATION_LEDGER.md` with task ID, owner, commit, touched paths, tests, results, reviewer, and current status.

| Agent | Role and exclusive primary ownership | Mission | Independent acceptance |
|---|---|---|---|
| **O0: Orchestrator / Architect** | Dependency graph, merge gate, integration ledger | Establish baseline, assign tasks, resolve interfaces, order merges, run integrated E2E | QA agent audits merge evidence; no green status from narratives alone |
| **A1: Security & Trust Boundary** | New approved-controller-execution adapter; `tests/test_security.py`, `tests/test_sandbox.py`; review of all execution sites | Eliminate host execution in all production-facing paths; validate KVM and sandbox policy; audit public/privileged operations | A8 adversarial tests; A6 audits verifier; A5 audits API |
| **A2: Physical Semantics & Contracts** | `domnir/contracts/stl.py`, new scenario/telemetry schema modules, related tests; source-level recommendations for `api/jobs.py` | Correct invalid outcomes, complete telemetry/horizon checks, time-varying disturbance semantics, canonical units and timebase | A8 metamorphic checks; A3 integration tests; A7 replay checks |
| **A3: Search & Benchmarks** | `domnir/ragnarok/search.py`, `minimize.py`, `benchmark.py`, relevant tests | Valid-only counterexamples, real random/Sobol/DE comparison, nontrivial benchmarks, witness minimization | A8 independent seeded tests and fake-evaluator attacks |
| **A4: Repair & Red/Blue Arena** | `domnir/ragnarok/repair.py`, new Arena orchestration modules, repair tests | Counterexample-guided repair, unbiased fresh holdouts, regression gates, co-evolution over new attacks | A8 independent repair-sabotage tests; A7 evidence lineage review |
| **A5: API / Orchestration / Budgets** | `domnir/api/app.py`, `jobs.py`, `models.py`, `security.py`, API tests | Integrate scenario schedules and controllers through only approved execution; campaign queue, quotas, readiness, cleanup, unauthenticated judge workflow | A1 security review; A8 concurrency/end-to-end tests |
| **A6: Portable Evidence & CI** | `domnir/verify.py`, `court_record.py`, `ci/gate.py`, evidence/CI tests | Make verifier non-executing by default; L0-L3 semantics; provenance chain; proper hashes; CLI/CI gate | A1 signs off on every source execution route; A8 tamper tests |
| **A7: Guardian, Uncertainty & Visualization** | `domnir/guardian/*`, `uncertainty/*`, `domnir/web/*` after UX scope is separated; related tests | Canonical actuator/observation semantics; actual model uncertainty; accurate 3D visualization, Failure Atlas, Rune UX/Oracle consistency | A2 checks dynamics; A6 checks evidence semantics; A8 browser/physics checks |
| **A8: Independent QA / Red Team** | New regression, property, fuzz, browser and E2E tests; READ-ONLY review of production modules | Attempt to break every claimed fix; audit failed cases, compare measured evidence; refuse unjustified passes | O0 records unresolved blockers; A8 does not secretly patch and approve its own findings |

**Conflict rule:** `api/jobs.py` is owned by A5, even if A2 requires disturbance or timebase changes. `verify.py`/`court_record.py` are owned by A6; A1 reviews them. `web/*` is owned by A7. Shared changes go through the owning agent. An agent cannot silently broaden its task to another owner's file.

**Delegation format for every task:** `TASK-ID`, current observed failure, hypothesis, owned file set, non-goals, acceptance tests, proof artifacts, dependencies, and maximum allowed retry/revision cycles.

## 2. Preflight Gate G0: baseline, test reproducibility, and trust map

O0 must first:

- Read `AGENTS.md`, `Upgrade_Plan.md`, the actual implementation plan, and the latest branch state. Create an interface map: controller generation, validation, guest communication, trusted MuJoCo, trajectory, safety contract, Court Record, verifier, API, UI.
- Capture `git status`, commit SHA, runtime/dependency pins, public route inventory, test collection count, exact frontend asset hashes, and current deployed/version identifier if verified.
- Run available syntax/static checks and targeted unit tests. On the correct pinned environment run the full suite; **do not claim a pass from the previous submission report**. Examples: `node --check domnir/web/app.js`, `python -m compileall -q domnir`, `uv run pytest -q` when the pinned environment supports it.
- Inventory all sources of direct host `exec`, `eval`, dynamic import, subprocess execution, and any code paths receiving controller source; inventory all resource-consuming endpoints.
- Produce `G0_BASELINE.md` with **observed results** and `BLOCKERS.md` with issues reproducible only on the Vultr/KVM deployment.

**G0 passes when:** a baseline exists, current tests are recorded accurately, each trust boundary is mapped, and task/ownership dependency issues are resolved. If source parses but live KVM is unavailable locally, mark physical tests blocked here and schedule them on the real host; never substitute mocks and call the gate complete.

## 3. First integration wave: correctness and isolation (G1)

Tasks may proceed in parallel in separate worktrees, then merge in dependency order.

### SEC-01: Universal sandbox-backed evaluator (A1; A5 and A6 integration)

Audit at minimum `domnir/verify.py`, `domnir/uncertainty/simulator.py`, `domnir/guardian/supervisor.py`, `domnir/ci/gate.py`, `domnir/benchmark.py`, and `domnir/api/jobs.py` for paths that execute controller source. Build or reuse **one typed interface** to execute untrusted controllers inside the approved guest. Avoid coupling the verifier to a live web server. Preserve a trusted built-in-controller test harness separately and make its trust assumption explicit.

**Expected:** L0 integrity verification of an adversarial Court Record never executes bundled source. L2 controller rerun requires explicit opt-in and a functioning approved sandbox. Missing sandbox fails closed. A harmless test payload that would create a host marker file if executed never creates that marker. Return a precise `UNAVAILABLE`/`NOT_VERIFIED` outcome, not `PASS`, when the host lacks virtualization.

### SEM-01: Result-state correctness and trajectory validation (A2; A3 downstream)

Require complete finite telemetry, monotonically valid timestamps, normalized quaternion within tolerance, a known controller-rate/physics-rate contract, and the required scenario horizon for each applicable predicate. Define typed outcomes `VIOLATED`, `SATISFIED`, `INVALID` and quantitative margins with units. Never serialize NaN/±infinity as ordinary JSON numeric results. Preserve legacy fields via versioned compatibility adapters if necessary.

**Expected:** five deliberately invalid evaluations produce **zero counterexamples**, five invalid counts, and zero false successes. A truncated but apparently safe trajectory cannot be `SATISFIED`.

### PHY-01: Disturbance schedule and canonical dynamics semantics (A2; A5 integration)

Make initial altitude, force, pulse start, pulse duration, and optional later waveform parameters part of a single validated **trusted scenario schema**. Apply forces according to the schedule in the production MuJoCo stepping loop, not just in an analytical mock. Record the applied schedule and physics/control timestamps and include it in independent replay and Court Records. Define one motor-command representation, units and motor order. If a controller operates at 100 Hz while physics integrates at 500 Hz, document and implement zero-order hold and check that all evaluators share it.

**Expected:** with identical controller/initial altitude/force, distinct non-overlapping pulse schedules produce different logged applied-force traces and, when the modeled system responds, different state trajectories; an out-of-range schedule is rejected; replay reproduces the same schedule; identical schedules reproduce within tolerance.

### API-01: Threat-limited campaign lifecycle (A5; A1 review)

Bound `/ragnarok/falsify`, `/ragnarok/minimize`, `/ragnarok/repair` and any Arena/Guardian/CI routes with campaign-level physics evaluations, Vultr inference tokens/cost, global concurrency, per-visitor request budgets, wall-clock timeout, storage retention and cancellation cleanup. Execute campaigns as jobs with typed states; do not occupy an unbounded synchronous API handler. Privileged containment is operator-only, even without configured credentials. Fix arbitrary forwarded-header trust. Report configured and truly verified readiness separately.

**Expected:** forged forwarded headers do not bypass quotas; an anonymous judge can complete a normal bounded experiment; privileged containment is denied without operator authorization; a request exceeding the campaign budget is rejected before runaway compute; cancellation and timeouts clean all guests; readiness never claims live inference solely because a key exists.

**G1 passes when:** sandbox-only execution, validity semantics, production disturbance application, and campaign resource controls are all independently tested, including negative/adversarial cases. **Do not advance to benchmark or repair claims while G1 is red.**

## 4. Second wave: research fidelity and trustworthy evidence (G2)

### SEARCH-01: Comparable search methods (A3)

Rename the existing pseudorandom `SobolBaselineFalsifier` or implement a real Sobol sequence. Maintain separately named Uniform Random, Sobol, and Differential Evolution methods. Ensure that each uses the same scenario bounds, the same controller and evaluator, the same number of *valid physics evaluations*, and an explicitly reported invalid-run count. Add independent seeds, evaluated scenario IDs, search trace, first-valid-failure evaluation index, and stopping reason. For nontrivial comparisons select a benchmark where the first sample does **not** always fail. Report uncertainty and missing results, not manufactured speedup.

**Expected:** Sobol samples match actual Sobol sequence properties/library; random remains correctly labeled. Five INVALID results are never interpreted as success. Search-iteration and objective scores correspond to genuine simulation outcomes. The benchmark clearly differentiates synthetic analytical, trusted MuJoCo, and full isolated-controller tiers.

### MINI-01: Counterexample reduction (A3; A2 review)

Maintain original witness, reduction objective, parameter bounds, and each attempted reduction. Use terminology **locally reduced counterexample** unless formal minimality is supported. Independently rerun/replay the reduced witness and validate its original constraints and admissible initial conditions.

**Expected:** final reduction remains a valid violation; no proposed witness leaves scenario bounds; the report shows original/reduced parameter values, evaluation count, actual result and limitation of the minimization claim.

### EVD-01: Portable verifier and CI provenance (A6; A1 review)

Separate L0 (structure/hash), L1 (recorded-action physics replay), L2 (explicit sandboxed controller rerun), L3 (bounded trusted-host containment evidence). No source execution during default portable checks. Use hashes of actual evidence bytes, not hashes of labels or scores pretending to be Court Record hashes. Emit machine-readable per-tier status `PASS/FAIL/NOT_RUN/INCOMPLETE` and reasons, tool/model versions, trust assumptions and measured tolerances. Optional signatures must include real signing keys and verification, otherwise omit signing claims.

**Expected:** untampered Court Record passes applicable structural checks; changing one artifact fails L0; malice embedded in the controller source is never executed by L0/L1; L2 without approved guest does not run; CI reports cannot claim artifact hashes when there are no artifacts.

### UNC-01: Real uncertainty + Guardian validity (A7; A2 and A1 review)

Make every reported uncertainty case actually modify the evaluated physical or observation model (mass, latency, noise, etc.) and record its applied parameters. Remove heuristic interpretation of four motor commands as collective thrust and moments. Use an explicit actuator schema and validated conversion/allocation before Guardian action interventions. Report requested vs applied actions separately. Do not claim the Guardian can always prevent physically unavoidable violations.

**Expected:** a controlled change in mass or actuator latency produces a measurable, directionally interpretable change in a suitable test case. Guardian cannot misinterpret a motor-command vector; its intervention and non-intervention cases are replayable and the trusted simulator owns the verdict.

**G2 passes when:** the numerical benchmark is nontrivial, measurements are valid, evidence is portable without host execution, and Guardian/uncertainty claims match actual behavior.

## 5. Third wave: autonomous adversarial engineering loop (G3)

A4 owns the **product's Red/Blue controller-development loop**; A3 supplies search and minimization; A2 supplies contracts; A5 supplies bounded execution; A6 supplies evidence. Do not simulate success.

### Arena iteration state machine

1. **Specify:** validate mission, scenario admissibility, finite horizon, hard safety contracts, allowed repair scope, and frozen initial benchmark suite. User approves the mission/constraints. Keep the holdout suite private from the repairing agent.
2. **Synthesize (Blue):** generate or select versioned controller `C_k` via Vultr. Validate schema and hash. No host execution.
3. **Baseline:** run known nominal tests and existing discovered-regression suite in the approved guest with trusted MuJoCo. Invalid evaluations are errors, not failures of physics.
4. **Attack (Red):** propose bounded scenario regions or parameters. Run adaptive numerical search; measure quantitative robustness. Red can propose but **cannot assign verdicts**.
5. **Verify:** if a genuine violation exists, independently rerun/replay the candidate and establish a versioned, cited witness. Reject irreproducible and invalid candidate attacks.
6. **Minimize:** locally reduce the witness under admissibility bounds. Preserve original and reduced artifacts, both independently checked.
7. **Diagnose:** send **only relevant trusted evidence** to the Vultr repair agent; it proposes a patch or new controller version. Preserve source before/after, model ID, prompt/version provenance and allowed change scope.
8. **Regression:** run original nominal cases and all previously discovered witnesses under identical conditions. Hard safety evaluation is gate-like: **zero observed violations in the designated acceptance suite** for acceptance; do not convert this finite test result into universal safety.
9. **Holdout:** test newly generated/secret seeded scenarios that Blue has not seen, with equal budgets and independent scoring. Record validity, performance, and remaining uncertainty. Do not leak holdout before revision selection.
10. **Co-evolve:** Red attacks newly accepted Blue revision with fresh scenarios, not only recycled witnesses. Each round adds verified regressions to a versioned corpus.
11. **Decide:** accept improvement only when defined gates pass and measured performance is non-regressive; otherwise reject/revise. Stop at configured round, inference and physics budgets or when no supported progress. `NO COUNTEREXAMPLE FOUND WITHIN BUDGET` is a legitimate result.
12. **Publish:** create full provenance graph: `controller_version → trial → scenario → verdict → counterexample → repair → regression → holdout → decision`, with links to evidence and reproducible commands.

**Expected G3 proof:** At least one reproducible end-to-end campaign where a nominal case, a genuine nontrivial searched scenario, optional minimized witness, proposed repair and independent regression/holdout are all backed by actual sandbox/MuJoCo artifacts. The system correctly handles and reports unsuccessful repair, invalid simulation, no discovered failure, and exhausted budget. Do not promise that a repair must succeed.

## 6. Fourth wave: product, visualization, knowledge, CI (G4)

### UI-01: Failures explained, not decorated (A7)

Maintain Rune Dawn/Dusk, glyphs and Blender/GLB asset. Expose the Arena loop as a guided sequence rather than a giant dashboard: mission → controller → baseline → adversarial search → confirmed witness → repair/regression → evidence. Provide a side-by-side synchronized replay for identical scenarios, a Failure Atlas where **tested** points are clickable and **untested** space is marked unknown, genuine failure-time annotation, and an honest progress/cancellation state. Fix overflow and browser errors. Never compute a “speedup” from a search iteration alone. Use actual baseline comparisons.

**Expected:** at 390/768/1280/1440 widths, no app-level overflow or clipped controls, both themes work, code remains selectable, 3D replay uses actual coordinates/orientation/timestamps where present, missing telemetry is visibly identified, and a user can navigate one genuine experiment without being overwhelmed.

### ORACLE-01: Evidence-grounded help (A7; A6 review)

Maintain full Documentation Oracle and collapsible Workspace helper, sharing one source index. Verify every indexed file and statement exists in actual repository/evidence. Local keyword search must be labeled documentation search. Use Vultr retrieval-plus-generation only if a real grounded generative flow is wired, with real navigable citations and explicit unknown-answer behavior. Oracle is not allowed to change verdicts or trigger privileged tools.

**Expected:** all citations resolve, unknown queries do not invent results, both entry points share consistent sources, and the experiment flow works if Oracle inference is unavailable.

### CI-01: Real release gating (A6; A5 integration)

Add an example CLI/GitHub Actions integration that accepts a controller version and selected, versioned evidence suite; compares baseline versus candidate using exact test budgets; reports regressions and errors; emits a machine-readable artifact that external CI can consume. Do not pretend synthetic score hashes are Court Records. Explicitly label models that remain uncalibrated and conditions that cannot be validated on the CI runner without KVM.

**Expected:** a seeded good/known-bad controller fixture produces different CI outcomes for a real measured reason, a missing sandbox does not silently bypass the gate, and evidence links resolve to real artifacts.

**G4 passes when:** the experimental evidence is understandable to judges, the Oracle has no phantom references, the CI uses real report semantics, and the web experience has been tested in actual browsers.

## 7. Fifth wave: independent production proof and release gate (G5)

A8 conducts an adversarial acceptance audit *after* changes are merged. A5 runs the deployment; O0 decides release based on recorded evidence. Run on the actual intended Vultr host; do not use local-only mocks as substitutes.

**One complete judge journey:** anonymous browser → validate mission → real Vultr model synthesis → validated controller → actual microVM guest → trusted MuJoCo baseline → actual adversarial campaign → valid counterexample (if one exists) → independent action replay → minimized witness (if present) → bounded repair attempt → regression + hidden holdout → Court Record download → portable verifier → cleanup. Test negative outcomes too.

**Security exercises:** malformed observations/actions; host-file marker payloads; network/prohibited-capability attempts where test scope permits; missing KVM; forged rate-limit headers; unauthenticated privileged endpoint access; tampered records; jobs cancelled mid-sandbox; concurrent campaign load. Keep all exercises isolated and authorized.

**Scientific audit:** benchmark controller selection; invalid-count accounting; temporal horizons and units; actual disturbance timings; real uncertainty perturbations; independent test seeds; no cherry-picked success claim; honest no-counterexample behavior; calibrated vs provisional physical assumptions clearly distinguished.

**G5 passes only when:** target live environment is independently exercised, no open P0 issues remain, evidence-backed claims match results, full suite outcome is recorded, and the owner receives a concise unresolved-risks register. If a gate fails, report **NOT READY** rather than deploying a cosmetically green product.

## 8. The development loop: exact execution algorithm

For **every** agent task, follow this loop. O0 executes it repeatedly across G0 → G5:

```
READ actual code + requirements
    ↓
REPRODUCE issue / write failing regression test
    ↓
DESIGN smallest patch and confirm file ownership
    ↓
IMPLEMENT only scoped change in isolated branch
    ↓
RUN focused tests + contract tests + static checks
    ↓
ADVERSARIAL QA challenges the fix independently
    ↓
REVIEW security, scientific semantics, evidence provenance
    ↓
PASS? ── no → root-cause report → revise (bounded cycles)
    │
   yes
    ↓
MERGE through coordinator + rerun integration checks
    ↓
CAPTURE artifacts, hash, observed results, open limitations
    ↓
UNLOCK dependent task / next gate
```

The independent QA reviewer must be different from the implementer. If the same defect recurs after **three** revisions, stop this task, produce a clear blocker/root-cause dossier, and have O0 re-plan its dependency or interface. Do not hide the defect or mark the gate complete. A task may remain `BLOCKED_BY_ENV` when real KVM, inference credentials, or deployment access is unavailable; the rest of the independently testable work can continue, but no live gate is claimed complete.

Statuses: `TODO`, `REPRODUCED`, `IMPLEMENTING`, `TESTING`, `REVIEW_PENDING`, `ACCEPTED`, `REJECTED`, `BLOCKED_BY_ENV`, `DEFERRED_WITH_REASON`.

### Example task handoff

```
TASK-ID: SEARCH-INVALID-01
Owner: A3 Search; Reviewer: A8 QA; Dependency: SEM-01
Observed issue: INVALID empty trajectory currently increments physical violation count
Scope: domnir/ragnarok/search.py and associated test file only
Failing test: evaluator returns 5 INVALID trajectories
Required outcome: 0 violations, 5 invalid results, no 'FALSIFIED' witness,
                  no non-finite JSON robustness
Non-goals: change MuJoCo backend or redesign UI
Evidence: test command/output, source diff, one serialized sample result
Exit: A8 reproduces fixed result independently and O0 merges
```

## 9. Required tests and expected outcomes

| ID | Scenario | Required outcome |
|---|---|---|
| T01 | Five invalid/truncated trials in falsifier | Zero reported counterexamples, invalid count five; no fabricated negative-infinity witness |
| T02 | Record embeds arbitrary controller source | Default L0/L1 verification does not execute source on host |
| T03 | Optional L2 controller rerun without sandbox | Fails closed with `NOT_VERIFIED`/`UNAVAILABLE` |
| T04 | Valid controller attempts forbidden guest operation | Containment records actual observed result; host not compromised |
| T05 | Two legal pulse schedules with equal force | Applied-force trace changes and dynamics respond when expected |
| T06 | Replayed timed-disturbance trial | Recorded actions/schedule reproduce expected state within specified tolerance |
| T07 | Missing final telemetry or invalid quaternion | Safety contract returns INVALID, not satisfied |
| T08 | Same search budget for random, Sobol and DE | Real methods executed; valid evaluations and invalids reported separately |
| T09 | Existing easy-failure benchmark | Marked degenerate/uninformative, not evidence of search superiority |
| T10 | Nontrivial benchmark across seeded problems | First valid violation varies; metrics computed from actual observations |
| T11 | Uncertainty mass/latency cases | Perturbation passed to evaluator and influences measurable state where expected |
| T12 | Guardian action-vector format | Explicit actuator schema; motor forces never guessed from magnitude |
| T13 | Candidate repair fixes witness but fails another hard holdout | Repair rejected; failure artifact retained |
| T14 | Repair succeeds all designated cases | Marked 'passed tested acceptance suite', **not universally safe** |
| T15 | New Red attack after Blue repair | Fresh scenario search is executed, not only witness replay |
| T16 | Tamper with Court Record bytes | L0 fails; unchanged original still validates |
| T17 | CI custom evaluator without Court Record | No fabricated Court Record hash or provenance claim |
| T18 | Forged `X-Forwarded-For` | Cannot bypass server-side resource limits |
| T19 | Anonymous judge normal operation | Works without login within quotas |
| T20 | Anonymous privileged containment call | Denied even when operator token unconfigured |
| T21 | Cancel or exhaust running campaign | Guest cleanup, terminal status, no infinite background work |
| T22 | Only configured Vultr key but unreachable provider | Readiness reports configured not live-verified |
| T23 | Failure Atlas unknown cells | Visually unknown, never colored as observed safe |
| T24 | Source links from both Oracle views | Actual existing citations, no phantom files |
| T25 | Real GLB replay where complete pose exists | Positions/orientations/timestamps correspond to recorded data |
| T26 | Browser at 390/768/1280/1440, two themes | No clipped controls, horizontal overflow, or script errors |
| T27 | Full fresh live campaign on intended Vultr host | Real inference, KVM guest, simulation, search, replay, evidence and cleanup |
| T28 | No valid adversarial witness within budget | Honest `NO COUNTEREXAMPLE FOUND WITHIN BUDGET` outcome |
| T29 | External verifier on clean host | Portable L0 works without project secrets or executing untrusted code |
| T30 | Old regression tests | Existing passing behavior remains passing, with explicit accounted exceptions |

All test cases must record `PASS`, `FAIL`, `SKIP`, or `BLOCKED_BY_ENV` with commands and evidence. **Do not hardcode the number of tests** based on historical static counts; obtain actual collection/exit status.

## 10. Deliverables and required reporting

Create these project documents/artifacts in the repository under an appropriate `docs/audits/` or `reports/` folder without overwriting historical evidence:

1. `G0_BASELINE.md`: SHA, repository inventory, environment, observed test collection and failure reproduction.
2. `TASK_GRAPH.md`: dependency graph, file ownership, merge order, task IDs, agents and exit criteria.
3. `INTEGRATION_LEDGER.md`: every changed file, motivation, commit, reviewer and tests.
4. `TRUST_BOUNDARY_AUDIT.md`: all controller execution paths, isolation properties, authorized exceptions and verified host observations.
5. `PHYSICS_CONTRACT.md`: action/observation schemas, units, frames, timing, actuator layout, disturbance schedules and simulation assumptions.
6. `BENCHMARK_PROTOCOL.md` and `BENCHMARK_RESULTS.md`: test tier, problem selection, seeds, evaluation budgets, baseline methods, invalid rate, statistical comparisons and limitations. Never prefill results.
7. `ARENA_RUN_REPORT.md`: controller versions, Red scenarios, Blue repairs, known witnesses, holdout outcomes and stopping reason with evidence refs.
8. `PORTABLE_VERIFIER_REPORT.md`: L0-L3 semantics, signed-vs-hashed claims, malicious-source tests and artifacts.
9. `UI_QA_REPORT.md`: representative screenshots and real browser outcomes in both themes and four viewport widths.
10. `RELEASE_READINESS.md`: gates G0-G5, outstanding P0/P1, exact live deployment verification and final yes/no decision.

After each agent turn, O0 reports:

```
Gate / task:
Agent and reviewed files:
Issue reproduced (command + observed behavior):
Smallest change (file paths + why):
Tests run (commands + pass/fail/skip):
Independent reviewer finding:
Security/scientific claim implications:
Artifacts and hashes:
Remaining blocker:
Next task unlocked:
```

Do not say 'all done' or 'release ready' until relevant gate evidence exists. If a specialist cannot obtain KVM or Vultr access, submit reproducible commands for the designated operator to run, but keep the gate unverified until returned logs establish results.

## 11. Coordinator startup instructions (paste into the agent tool)

You are **O0, Lead Orchestrator** for Dómnir V3. Read the complete multi-agent protocol in `DOMNIR_MULTI_AGENT_EXECUTION_LOOP.md`, root `AGENTS.md`, `Upgrade_Plan.md`, and the current repository. Your mission is to integrate and scientifically validate all existing upgrade modules, not to rewrite them.

First complete G0 and issue `TASK_GRAPH.md`. Delegate G1 tasks to isolated specialist agents according to the ownership matrix. Enforce parallel work only where source files and interfaces do not collide. Ask each specialist to reproduce its target defect, write a failing regression, make the smallest compatible patch, and return exact commands and outputs. Assign independent A8 review before accepting or merging any change. Then advance through G1, G2, G3, G4 and G5 in dependency order.

Implement both loops: the **engineering agent loop** of reproduce → patch → test → adversarial review → integrate, and the **product Arena loop** of specify → synthesize → attack → verify → minimize → repair → regression → secret holdout → attack again → evidence. Never conflate product outcomes with development-agent assurances.

Ensure no production path executes untrusted controller code on the host; INVALID never counts as a discovered violation; pulse schedules affect the real MuJoCo API path; public campaigns have enforceable budgets; benchmarks use actual sampled methods and nontrivial problems; repairs must pass hard-safety regression and hidden holdout checks; portable verification remains safe by default; and the judge workflow stays accessible without login.

Preserve working legacy code, preserve the approved Rune Dawn/Dusk and Blender design, retain only Vultr inference, and report every gate's evidence honestly. Do not request permission for ordinary scoped implementations, but obtain explicit owner approval before changing the fundamental threat model, replacing microVM isolation with another technology, changing a protected contract incompatibly, or publishing/deploying to a user-facing environment.

Begin with G0 now. Provide a compact initial delegation table, task dependencies, and the first reproducible failures before changing source code.

## Appendix A. Ready-to-dispatch specialist prompts

O0 should copy the appropriate block into each specialist task, then fill in the **current commit SHA**, task ID, baseline evidence and branch/worktree name. These are implementation assignments, not invitations to redesign other people's work.

### Dispatch to A1 — Security & Isolation

> You own the security execution boundary for Dómnir V3. Read `AGENTS.md`, `DOMNIR_MULTI_AGENT_EXECUTION_LOOP.md`, and G0's trust map. Starting from the actual repository, enumerate every path that consumes untrusted controller source, including portable verifier, uncertainty, Guardian, CI, benchmark and API. Reproduce any direct host execution in an isolated authorized test. Propose a single typed sandbox-backed execution adapter without rewriting the original working simulator/guest protocol. Coordinate proposed edits to `verify.py` with A6 and to `api/jobs.py` with A5. Test missing KVM, guest failure, timeout, forbidden capability, cancellation and cleanup. **Expected:** no production-facing untrusted controller runs on host; safe default verification cannot execute embedded source; missing sandbox fails closed. Return exact changed files, tests, outputs and blocked deployment checks. Do not mark containment universally verified.

### Dispatch to A2 — Physics & Formal Contracts

> You own trusted scenario, telemetry and predicate semantics. Reproduce INVALID trajectories being treated as valid violations, truncated horizons passing constraints, and pulse start/duration being ignored by the real public execution path. Define typed outcomes and finite per-property robustness margins with units; validate timestamps, frames and sample horizons. Define scenario forces as time-indexed schedules and an explicit actuator/timebase contract. Do not edit `api/jobs.py` directly; provide a precise integration patch/interface request to A5. **Expected:** invalid data is never a counterexample, pulse schedules change actual applied forces, physics/replay use the same schedule, actuator commands are unambiguous. Supply numerical tests and full expected vs observed traces. Preserve legacy records through compatibility adapters.

### Dispatch to A3 — Falsification & Research Benchmarks

> You own search, minimization and benchmark methodology. Read the actual existing implementations before editing. Fix misleading Sobol naming (implement genuine Sobol or rename), count only completed valid violated trials, create meaningful seeded benchmarks where the first evaluation is not invariably a failure, and distinguish analytical, trusted-MuJoCo and isolated-MuJoCo tiers. Add consistent search budgets, stopping reasons, invalid counters, non-finite handling, and reproducible sampling. The minimizer may claim locally reduced counterexamples only with verified final witnesses. **Expected:** independent seeded random/Sobol/DE runs produce grounded comparable metrics; invalids never become physical violations; benchmarks cannot fabricate search speedups. Return data files plus code and test evidence.

### Dispatch to A4 — Autonomous Repair & Arena

> You own the Red/Blue controller revision loop. First verify A1/A2/A3 interfaces are stable. Preserve every controller version, verified attack, reduced witness and decision. Red proposes admissible regions and uses real trusted evaluation; Blue receives evidence and proposes patches through Vultr. Run all previous hard-safety regressions plus sealed seeded holdouts that Blue has not seen; reject repairs with observed hard violations even if a percentage threshold passes. After each accepted Blue revision, Red must conduct **new** search against that revision. **Expected:** real integrated run demonstrating success or truthful unsuccessful repair with regression/holdout artifacts, no hidden controller execution on host, bounded model and physics budgets, complete version lineage. Do not claim universal safety.

### Dispatch to A5 — API, Jobs & Resource Budgets

> You own API schema, execution orchestration and resource controls. Integrate A2's production disturbance schedule into `jobs.py` while preserving existing endpoints via versioned schema/defaults. Integrate the approved sandbox-backed evaluator. Put `/ragnarok/falsify`, `/minimize`, `/repair`, Guardian/CI and future Arena actions into bounded campaign job processing with cancellation, concurrency, cleanup, retention and total inference/physics budgets. Preserve anonymous normal judge flows; deny privileged containment without operator credentials; never trust arbitrary forwarded headers. Distinguish inference configured from successfully checked live. **Expected:** real API pulse timing works, invalid jobs do not generate witnesses, forged clients cannot bypass budget accounting, jobs terminate and clean up. Return endpoint contract and exact network/security test evidence.

### Dispatch to A6 — Evidence, Portable Verifier & CI

> You own Court Record, portable verifier and CI result semantics. Inspect `domnir/verify.py` and test whether default verification executes untrusted Python; remove that behavior. L0 hashes and structure must be safe offline; L1 recorded-action replay checks physical states; optional L2 rerun calls A1's approved sandbox; L3 describes actual recorded host-side containment checks without overclaiming. Replace synthetic 'Court Record hashes' with genuine artifact hashes or correct field names. Provide a CLI/CI demonstration with real versioned results, strict pass/fail/incomplete semantics and controlled audit output. **Expected:** malicious controller embedded in evidence cannot execute during offline verification, tampering fails, claim labels match evidence tiers, CI reports actual artifacts. Request A1 review before merge.

### Dispatch to A7 — Guardian, Uncertainty, 3D/UI and Oracle

> You own the remaining physical-comparison and product-facing semantics. Coordinate first with A2 for a canonical actuator vector and scenario/timebase, and with A1 for safe evaluator use. Ensure uncertainty configurations actually alter physics or observations and are measured in benchmark reports. Guardian must not guess motor-command meaning; requested and applied actions must remain separate. Preserve Rune Dawn/Dusk, the existing Blender/GLB drone and progressive disclosure, and bind the Failure Atlas and synchronized viewer to genuine trajectories. Audit Knowledge Oracle citations against real files, keep the Workspace panel collapsible, and never permit Oracle text to declare safety verdicts. **Expected:** controlled uncertainty alters observed outcomes, Guardian uses explicit units, replay uses full recorded pose/timing where available, unknown visual regions are labeled unknown, and browser tests pass both themes. No new decorative redesign.

### Dispatch to A8 — Independent QA / Adversarial Reviewer

> You are the independent auditor, not an implementation assistant. For every claimed fix, reproduce the original failure if possible, inspect the diff, attempt adversarial cases, run the targeted tests and review result provenance. Focus on malicious source in verifier, empty/incomplete trajectories, pulse timing identity, fake Sobol baselines, benchmark degenerate cases, repair-on-known-witness overfitting, holdout leakage, quota bypass, cleanup failures, and frontend false green status. Do not approve any change merely because a developer provided a passing log. Record your own reproducible commands, observations and independent pass/fail rationale. You can create separate test fixtures, but never patch and approve the same production fix. **Expected:** a signed-off or rejected acceptance report per task with executable reproduction, not qualitative assurance.

## Appendix B. Example orchestration cycles

### Cycle 1: Fix a false counterexample

O0 assigns SEM-01 to A2 and SEARCH-INVALID-01 to A3, with A3 blocked on A2's final result contract. A2 writes an invalid-trajectory test; the old contract fails it; A2 makes a minimal fix. A8 independently runs the test, including a partially truncated trajectory. O0 merges the contract adapter. A3 then updates the searcher's outcome handling and reproduces the five-invalid-run experiment. A8 checks the serialized API result and confirms **0 false counterexamples**. O0 unlocks public search integration.

### Cycle 2: Close the verifier execution hole

O0 assigns SEC-01 to A1 and EVD-01 to A6; they agree on a typed approved evaluator interface before coding. A6 changes L0/L1 to never execute the source; A1 provides a guest-only adapter for optional L2. A8 constructs a benign marker-creating controller inside a crafted Court Record, runs the default verifier, and confirms the marker is never created. With KVM unavailable, L2 must be `UNAVAILABLE`, not silently run a subprocess. O0 merges only after both negative and normal-record tests pass.

### Cycle 3: Demonstrate actual co-evolution

O0 instructs A4 to start only after search, budget and verifier gates pass. Red tests the Blue controller and finds a **valid** counterexample. Minimization reduces it without changing verdict. Blue proposes a repair. A4 replays the known witness and nominal scenarios, then evaluates previously hidden seeded holdouts. A8 checks the actual evidence provenance. If acceptance passes, Red performs an independent fresh search against the revised controller; if it finds another failure, a new round begins. If no counterexample is found within the budget, output precisely that, with all tested constraints and limits. The final Court Record set links every version and decision. Failure to repair is reported as such, not hidden.
