# Dómnir

**Adversarial Falsification and Containment Platform for AI-Generated Crazyflie 2 Flight Controllers**

*Built for Vultr Agent Rush Hackathon | Challenge 1: Blast Radius Zero*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-blue.svg)](pyproject.toml)
[![MuJoCo 3.3.7](https://img.shields.io/badge/MuJoCo-3.3.7-green.svg)](https://github.com/google-deepmind/mujoco)
[![Vultr Serverless Inference](https://img.shields.io/badge/Vultr-Serverless%20Inference-007bfc.svg)](https://www.vultr.com/)
[![Tests: 202 Passed](https://img.shields.io/badge/Tests-202%20Passed-success.svg)](tests/)

---

### Quick Links
- **Hackathon Submission Report**: [docs/HACKATHON_SUBMISSION_REPORT.md](docs/HACKATHON_SUBMISSION_REPORT.md)
- **Live Edge Observatory (HTTPS)**: [https://domnir.erebuzzz.tech](https://domnir.erebuzzz.tech)
- **Live Direct Origin**: [http://45.76.48.77:8000/](http://45.76.48.77:8000/) (or [http://45.76.48.77/](http://45.76.48.77/))
- **Live Readiness API**: [https://domnir.erebuzzz.tech/ready](https://domnir.erebuzzz.tech/ready)
- **Containment Audit API**: [https://domnir.erebuzzz.tech/containment/status](https://domnir.erebuzzz.tech/containment/status)
- **Ragnarok Benchmark Report**: [docs/evidence/ragnarok_benchmark_report.json](docs/evidence/ragnarok_benchmark_report.json)
- **Challenge**: Vultr Agent Rush Hackathon | Challenge 1: Blast Radius Zero
- **License**: MIT License (MIT-compliant)

---

## Table of Contents
- [Part I: Hackathon Showcase (Vultr Agent Rush)](#part-i-hackathon-showcase-vultr-agent-rush)
  - [1. Challenge Overview & Blast Radius Zero Mission](#1-challenge-overview--blast-radius-zero-mission)
  - [2. How Vultr Powers Dómnir](#2-how-vultr-powers-dómnir)
  - [3. Multi-Model Selection Guide](#3-multi-model-selection-guide)
  - [4. Challenge 1 Containment Moments (Demo Guide)](#4-challenge-1-containment-moments-demo-guide)
  - [5. Autonomous Agent Workflow: Real Tasks](#5-autonomous-agent-workflow-real-tasks)
- [Part II: Platform Engineering & Technical Reference](#part-ii-platform-engineering--technical-reference)
  - [6. System Architecture & Trust Boundaries](#6-system-architecture--trust-boundaries)
  - [7. Physical Simulation & Deterministic Replay Engine](#7-physical-simulation--deterministic-replay-engine)
  - [8. Cryptographic Court Records](#8-cryptographic-court-records)
  - [9. REST API Reference](#9-rest-api-reference)
  - [10. Setup and Verification Guide](#10-setup-and-verification-guide)
  - [11. Production Deployment on Vultr Cloud Compute](#11-production-deployment-on-vultr-cloud-compute)
  - [12. Truthful Disclosures & Physical Limitations](#12-truthful-disclosures--physical-limitations)
  - [13. License, Security, and Privacy](#13-license-security-and-privacy)

---

# Part I: Hackathon Showcase (Vultr Agent Rush)

## 1. Challenge Overview & Blast Radius Zero Mission

Autonomous AI agents capable of writing code are rapidly expanding into physical systems, including robotics, drones, and industrial control. However, generating flight software introduces critical hazards:

1. **Physical Crash Risks**: Standard unit tests cannot evaluate whether an AI-generated control law stabilizes aerodynamic rotor physics or destabilizes into catastrophic ground crashes.
2. **Infrastructure Takeover Risks**: Executing untrusted AI code directly on host servers risks remote code execution, secret exfiltration, denial of service, and host network traversal.

Dómnir establishes a **Blast Radius Zero** architecture for AI-generated Crazyflie 2 flight controllers:
- **Zero Host Execution**: AI-generated code runs exclusively inside disposable, hardware-isolated microVMs with strict resource and network boundaries.
- **Trusted Host Physics**: The host physics harness owns MuJoCo, computes state transitions, clamps actuator bounds, and records truth telemetry.
- **Deterministic Replay Verification**: Independent re-simulation without controller code verifies reproducibility to within $10^{-12}$ m.
- **Cryptographic Court Records**: Immutable audit packages with SHA-256 asset digests and chained host event logs.

---

## 2. How Vultr Powers Dómnir

Dómnir runs entirely on Vultr Cloud infrastructure, leveraging both compute virtualization and serverless inference:

### 2.1 Vultr Cloud Compute (High Frequency with Nested KVM)
- **Compute Instance**: Vultr Cloud Compute High Frequency (`vx1-g-2c-8g-120s`, Tokyo region `nrt`).
- **Hardware Virtualization**: AMD EPYC processors with nested virtualization (`svm`) providing direct `/dev/kvm` hardware acceleration to the unprivileged `domnir` service user.
- **Sub-Second MicroVM Sandboxing**: Powers high-density, sub-second boot times for guest microVMs via Microsandbox (`msb 0.7.13`), guaranteeing complete kernel and memory boundary isolation from the host.
- **Hardened Deployment**: The control plane, trusted MuJoCo physics engine, and public web interface run directly as a systemd service (`domnir.service`) bound to public ports 80 and 8000.

### 2.2 Vultr Serverless Inference
- **Inference Gateway**: Dedicated Vultr Serverless Inference API at `https://api.vultrinference.com/v1`.
- **Zero Idle Costs**: On-demand token streaming eliminates expensive idle GPU server charges.
- **Low-Latency Synthesis**: Generates validated Python controller algorithms in 1.8 to 2.4 seconds with minimal reasoning overhead.
- **Server-Side Secret Isolation**: Inference credentials remain strictly backend-only in `.env` and are never exposed to the web browser or untrusted microVM guests.
- **Dynamic Catalog Validation**: Validates model availability against Vultr model endpoints (`GET /v1/models`) and enforces model match integrity.

---

## 3. Multi-Model Selection Guide

Dómnir exposes three distinct Vultr-hosted model families. Users can toggle between them directly in the web UI cards or via the REST API:

| Model ID | Provider | Latency | Specialization | Recommended Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **`glm-5.3-flash`** (Default) | Vultr Serverless Inference | ~2.1 s | Schema adherence & rapid code generation | Standard hover missions, step response evaluation, rapid sweeps |
| **`qwen3.8-flash-next`** | Vultr Serverless Inference | ~2.4 s | Mathematical and state reasoning | Turbulent flight envelopes, disturbance recovery, non-linear targets |
| **`deepseek-v4.1-flash-1017`** | Vultr Serverless Inference | ~1.8 s | Compact logic & tight variable scoping | Highly constrained step budgets, deterministic PD gain tuning |

**Configurable Reasoning Effort**: Each model supports selectable reasoning effort levels (`minimal`, `low`, `medium`, and `high`) configurable directly in the web UI or via the `/controllers/generate` API payload, allowing users to tune between instant code emission and deep mathematical derivation.

Every model response is sanitized, checked for fenced Markdown blocks, parsed via Python AST, fingerprinted with SHA-256, and validated against the 32 KiB code limit before entering the microVM cage.

---

## 4. Challenge 1 Containment Moments (Demo Guide)

For the Vultr Agent Rush Challenge 1 submission, Dómnir demonstrates three clear containment moments:

### Containment Moment 1: Host Privilege & Capability Denial (`CAP-HOST-001`)
- **What Happens**: An untrusted controller attempts to probe host system files or call host canaries (`read_host_canary`).
- **Containment Action**: The host capability broker intercepts the request, verifies policy, responds with a strict `DENIED` status, and logs the attempt into the SHA-256 hashed host event log.
- **Outcome**: `PASS`. The guest remains strictly contained and cannot read host files or environment secrets.

### Containment Moment 2: Wall-Clock Execution Watchdog (`RES-TIME-001`)
- **What Happens**: An adversarial or buggy controller executes a CPU-locking infinite loop (`while True: pass`).
- **Containment Action**: The trusted host watchdog monitors monotonic wall-clock elapsed time. At exactly 0.50 s, the host forcibly terminates the guest microVM and reclaims memory and CPU.
- **Outcome**: `PASS`. The experiment transitions to `FAILED` without host freeze or resource starvation.

### Containment Moment 3: Default-Deny Network Isolation (`NET-EGRESS-001`)
- **What Happens**: An adversarial controller attempts external network communication (socket connect or data exfiltration).
- **Containment Action**: The virtual network interface enforces default-deny ingress and egress with zero published ports and zero host mounts.
- **Outcome**: `POLICY_CONFIRMED`. Socket connections fail immediately with `connection_failed`.

### The Five Containment Pillars

```mermaid
flowchart LR
    Workload["Adversarial Workload"] --> P1["1. Broker Denial: CAP-HOST-001 (PASS)"]
    Workload --> P2["2. Network Isolation: NET-EGRESS-001 (CONFIRMED)"]
    Workload --> P3["3. Watchdog Timeout: RES-TIME-001 (PASS: 0.50s)"]
    Workload --> P4["4. Memory Limit Exit: RES-MEM-001 (OBSERVED)"]
    Workload --> P5["5. Teardown Guarantee: CLEANUP-100 (100% Deletion)"]

    P1 --> Log["Chained Host Event Log (18 Events, SHA-256 Verified)"]
    P2 --> Log
    P3 --> Log
    P4 --> Log
    P5 --> Log
```

| Fixture ID | Category | Status | Evidence Source | Verification Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **CAP-HOST-001** | Broker Capability Denial | **PASS** | `trusted_host_broker` | Host broker denies unauthorized capability request (`read_host_canary`). Guest receives strict `DENIED`. |
| **NET-EGRESS-001** | Network Isolation | **POLICY_CONFIRMED** | `trusted_runtime_configuration` | Host confirms default-deny egress/ingress, 0 published ports, 0 host mounts. Guest TCP connect fails. |
| **RES-TIME-001** | Resource Watchdog Timeout | **PASS** | `trusted_host_watchdog` | Guest running an infinite loop is terminated when monotonic wall-clock watchdog limit (0.50 s) is reached. |
| **RES-MEM-001** | Memory & Runtime Exit | **OBSERVED_EXIT_CAUSE_UNKNOWN** | `trusted_runtime_metrics_and_job_status` | Guest allocates 1 GiB under a 512 MiB limit. Exited with code -1. Truthfully reported without unsupported OOM claims. |
| **CLEANUP-100** | MicroVM Teardown Guarantee | **PASS** | `msb list` | 100% microVM deletion confirmed on all normal, timeout, crash, and abort paths. Zero leaked processes. |

---

## 5. Autonomous Agent Workflow: Real Tasks

Dómnir automates the real-world engineering workflow of evaluating AI control software for physical aerial robotics:

```mermaid
sequenceDiagram
    autonumber
    actor User as Engineer / Web UI
    participant API as FastAPI Orchestrator
    participant Vultr as Vultr Serverless Inference
    participant MicroVM as Guest MicroVM (Microsandbox)
    participant HostSim as Trusted MuJoCo Physics (500 Hz)
    participant Replay as Replay Verifier
    participant Ledger as Court Record Ledger

    User->>API: 1. Submit FlightSpec (target altitude, disturbance bounds, dt=0.002s)
    API->>Vultr: 2. Query LLM (GLM 5.3 / Qwen 3.8 / DeepSeek V4.1)
    Vultr-->>API: 3. Stream Controller Code: observe(obs)
    API->>API: 4. Static AST Parse, 32 KiB Limit Check, SHA-256 Digest
    API->>MicroVM: 5. Boot Disposable MicroVM via /dev/kvm
    loop Simulation Loop (500 Hz / dt = 0.002s)
        HostSim->>MicroVM: Send Observation (position, velocity, target)
        MicroVM->>HostSim: Stream Action Frame (thrust, moments)
        HostSim->>HostSim: Step MuJoCo Dynamics & Inject Disturbance
    end
    API->>MicroVM: 6. Terminate & Destroy MicroVM (100% Cleanup Guarantee)
    API->>Replay: 7. Re-simulate Actions in Fresh MuJoCo Instance
    Replay-->>API: 8. Deterministic Replay Diff (delta <= 1e-12 m)
    API->>Ledger: 9. Compile Signed Court Record Package
    Ledger-->>User: 10. Deliver Trajectory Chart, Verdict, & Audit Record
```

---

# Part II: Platform Engineering & Technical Reference

## 6. System Architecture & Trust Boundaries

The system enforces strict unidirectional trust boundaries between untrusted AI controllers and host infrastructure:

```mermaid
flowchart TD
    subgraph Vultr_Inference_Layer["Vultr Serverless Inference API"]
        Model_Catalog["Model Discovery & Catalog Validation"]
        LLM_Synthesis["Streaming Token Generation"]
        Model_Catalog --> LLM_Synthesis
    end

    subgraph Host_Control_Plane["Host Control Plane & Security Middleware (FastAPI)"]
        Sec_Headers["Security Headers (CSP, Nosniff, Frame DENY)"]
        Size_Limit["Streaming Body Limiter (2 MiB Court Records / 64 KiB API)"]
        Rate_Limiter["Sliding-Window Rate Limiter (Dual Bucket)"]
        Path_Guard["Path Traversal & Identifier Validator"]
        Job_Orchestrator["Job Orchestrator & State Machine"]

        Sec_Headers --> Size_Limit --> Rate_Limiter --> Path_Guard --> Job_Orchestrator
    end

    subgraph Guest_Containment["Untrusted Guest Sandbox (Microsandbox MicroVM)"]
        Guest_Process["Python Controller Process"]
        Stdio_Pipe["Stdio Channel (Max Frame: 4096 bytes)"]
        Guest_Process --> Stdio_Pipe
    end

    subgraph Trusted_Physics["Trusted Physics Engine (Forseti)"]
        MuJoCo_Plant["MuJoCo 3.3.7 Bitcraze Crazyflie 2"]
        Integrator["Host State Integrator (500 Hz)"]
        Disturbance_Gen["Aerodynamic Disturbance Generator"]
        MuJoCo_Plant --> Integrator
    end

    subgraph Replay_Verification["Deterministic Replay Verifier"]
        Fresh_Sim["Fresh Pristine MuJoCo Engine"]
        Diff_Calc["Coordinate Difference Metric (<= 1e-12 m)"]
        Fresh_Sim --> Diff_Calc
    end

    subgraph Evidence_Ledger["Court Record & Audit Ledger"]
        Hash_Chain["Chained Host Event Log (SHA-256)"]
        Court_Record["Signed Court Record Package"]
        Hash_Chain --> Court_Record
    end

    LLM_Synthesis --> Job_Orchestrator
    Job_Orchestrator -->|Boot & Cage| Guest_Process
    Stdio_Pipe -->|Action Frame| Integrator
    Integrator -->|Observation Frame| Stdio_Pipe
    Integrator --> Fresh_Sim
    Diff_Calc --> Court_Record
    Job_Orchestrator --> Evidence_Ledger
```

### Trust Boundary Rules
- **No guest secrets**: Guest microVMs receive no environment secrets, Vultr API keys, database credentials, host mounts, or Docker sockets.
- **Default-deny network**: Zero published ports, zero guest host mounts, and default-deny ingress and egress rules.
- **Host ownership**: The guest never touches MuJoCo model bytes or `MjData`.
- **Ephemeral lifetime**: Every microVM has a strict wall-clock timeout (0.50 s watchdog) and mandatory cleanup via context managers.

---

## 7. Physical Simulation & Deterministic Replay Engine

Dómnir utilizes MuJoCo 3.3.7 and the official Google DeepMind MuJoCo Menagerie Bitcraze Crazyflie 2 model:

- **Simulation Step**: $dt = 0.002$ s (500 Hz control loop).
- **Control Vector**: Clamped thrust $[0.0, 0.35]$ N and angular moments $[M_x, M_y, M_z]$.
- **Disturbance Modeling**: Injects aerodynamic disturbance forces ($F_z \in [-0.05, +0.05]$ N) to evaluate robustness.
- **Deterministic Replay**: Recorded actions are re-simulated in a brand-new MuJoCo model without executing controller code. Position and velocity coordinates must match recorded trajectory points within machine precision:
  $$\max_{k} \|\mathbf{qpos}_k - \mathbf{qpos}_k^{\text{replay}}\| \le 10^{-12} \text{ m}$$

---

## 8. Cryptographic Court Records

Every experiment outputs a verifiable Court Record (`domnir-court-record-v1`):

```json
{
  "schema_version": "domnir-court-record-v1",
  "record_id": "cr-eef6eff83e5246f5",
  "experiment_id": "86747975-c1db-48b9-a2a8-db2b5a6aeaf4",
  "verdict": "NOT_FALSIFIED",
  "verdict_reason": "All scenario safety constraints satisfied within tolerances.",
  "controller": {
    "source_code": "def observe(obs): ...",
    "source_sha256": "31aac2db...",
    "model_id": "glm-5.3-flash"
  },
  "replay": {
    "verdict": "MATCHED",
    "max_abs_difference": 0.0,
    "tolerance": 1e-12
  },
  "host_event_log": {
    "event_count": 18,
    "sha256_head": "48148340...",
    "verified": true
  }
}
```

- **Tamper Resistance**: Modifying any coordinate or action invalidates the SHA-256 digest.
- **In-Browser Verification**: The web UI includes an interactive drag-and-drop Court Record Verifier enabling third parties to independently verify trial integrity.

---

## 9. REST API Reference

The FastAPI service exposes structured, type-safe REST endpoints with Pydantic schema validation, sliding-window rate limiting, request size enforcement, and security headers:

### Health and Readiness
- `GET /health`: Returns service health, version, and server timestamp.
- `GET /ready`: Returns readiness status, loaded model status, Vultr inference status, and microVM availability.
- `GET /models`: Lists configured Vultr Serverless Inference models with metadata and default selection.

### Flight Specs and Code Generation
- `POST /specs/validate`: Validates flight envelope bounds (`target_altitude_m`, `mission_duration_s`, `dt_s`, step budget).
- `POST /controllers/generate`: Queries Vultr Serverless Inference to generate a validated Python controller function `observe(obs)`.

### Qualification Experiments
- `POST /experiments/run`: Submits an experiment for execution. Accepts specification, model, disturbance force, and controller source (maximum 32 KiB). Supports synchronous or asynchronous background execution.
- `GET /experiments/{experiment_id}`: Retrieves experiment state, history, metrics, and verdict.
- `GET /experiments/{experiment_id}/artifacts`: Retrieves complete simulation trajectory vectors, event logs, and Court Record.
- `GET /experiments/{experiment_id}/court-record`: Exports standalone Court Record JSON package.

### Verification and Containment
- `POST /court-records/verify`: Independent in-memory physical replay verifier. Replays recorded actions on a fresh MuJoCo instance, verifies SHA-256 hashes, and checks event log chaining.
- `GET /containment/status`: Returns verified results for the 5 containment fixtures, host event log status, and limitations.
- `POST /containment/run`: Triggers a live run of the microVM containment suite on KVM-enabled Linux hosts.

---

## 10. Setup and Verification Guide

### Prerequisites
- Python 3.12 (`>=3.12,<3.13`)
- `uv` package manager
- Git

### 1. Local Development Setup

```bash
# Clone the repository
git clone https://github.com/Erebuzzz/domnir.git
cd domnir

# Install pinned dependencies
uv sync --locked

# Clone the Bitcraze Crazyflie 2 model from MuJoCo Menagerie
git clone --filter=blob:none --no-checkout https://github.com/google-deepmind/mujoco_menagerie.git .cache/mujoco_menagerie
git -C .cache/mujoco_menagerie sparse-checkout set bitcraze_crazyflie_2
git -C .cache/mujoco_menagerie checkout 98a70c569c4c1b6da467a20012f766ee1f8dc521

# Configure environment variables (set Vultr Inference API key)
echo "VULTR_INFERENCE_API_KEY=your_key_here" > .env
```

### 2. Run the Full Test Suite

```bash
# Run all unit, integration, and security tests
uv run pytest -v
```

All 202 tests run deterministically:
- On non-KVM hosts: microVM-specific integration tests cleanly skip while all simulation, inference, API, replay, security, contracts, Ragnarok search, minimization, CEGIS repair, uncertainty, Guardian, and CI gate tests pass (202 passed, 11 skipped, 0 failed).
- On live KVM-enabled Vultr hosts: all 202 tests pass (202 passed, 0 failed).

### 3. Launch the Web Application

```bash
uv run uvicorn domnir.api.app:app --host 127.0.0.1 --port 8000 --reload
```

Open `http://localhost:8000` in any modern web browser to access the Dómnir platform:

- **Guided Experiment Workflow**: 4-step mission pipeline guiding the user through envelope configuration, Vultr serverless AI synthesis, hardware-isolated microVM setup, and live 500 Hz MuJoCo telemetry execution.
- **Rune Dawn and Rune Dusk Theme System**: Mode-aware UI aesthetic featuring warm sandstone and burnt copper in Rune Dawn, and midnight obsidian with Bifrost cyan in Rune Dusk. Both modes incorporate 4-tier elevation shadow tokens and WCAG AA contrast.
- **Authentic 3D Drone Digital Twin**: WebGL Three.js interactive physical plant viewer derived from MuJoCo Menagerie CAD meshes via Blender 5.2.3 LTS. Features turntable rotation, orbital camera controls, concentric rotor spin axes, and high-resolution Cycles PBR stills for zero-latency fallback.
- **Synchronized Simulation Replay**: Dual-view playback synchronizing the 2D altitude SVG trajectory with the 3D quadrotor spatial orientation, complete with interactive scrubber and timestep hover inspection.
- **Ragnarok Knowledge Oracle**: Grounded technical retrieval engine citing platform architecture and containment proofs, accessible via both the Docs tab and a collapsible Workspace quick drawer.
- **Court Record Verifier**: In-browser drag-and-drop verification of signed Court Record packages against an independent pristine MuJoCo engine.
- **Containment Audit Tab**: Live and certified microVM isolation proofs across all five containment pillars.
- **Trust Architecture**: Interactive security boundary documentation with clear non-negotiable trust rules.

---

## 11. Production Deployment on Vultr Cloud Compute

For production deployment on a Vultr Cloud Compute instance running Ubuntu 24.04 LTS:

### 1. Host Virtualization Verification
```bash
# Confirm KVM hardware virtualization
ls -l /dev/kvm
egrep -c '(vmx|svm)' /proc/cpuinfo

# Grant permissions to deployment user
sudo usermod -aG kvm domnir
```

### 2. Systemd Service Installation
Dómnir includes a pre-configured systemd service definition in `domnir.service`:

```bash
# Copy systemd unit file
sudo cp domnir.service /etc/systemd/system/domnir.service

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable domnir
sudo systemctl start domnir

# Check service status and logs
sudo systemctl status domnir
journalctl -u domnir -f
```

### 3. Cloudflare Edge Reverse Proxy with Custom Domain
To provide edge TLS termination, HTTP/2 and HTTP/3 support, DDoS mitigation, and global custom domain routing (`https://domnir.erebuzzz.tech`) to the Vultr Cloud Compute instance, Dómnir includes a lightweight edge reverse proxy in `deploy/cloudflare/`:

```bash
cd deploy/cloudflare
npx wrangler deploy
```

The worker terminates TLS at Cloudflare edge locations, forwards requests to the live Vultr compute instance origin, preserves full streaming request/response bodies, and injects origin observability headers.

---

## 12. Truthful Disclosures & Physical Limitations

In accordance with the Blast Radius Zero engineering guidelines, Dómnir maintains absolute transparency regarding physical modeling assumptions:

1. **Uncalibrated Menagerie Limits**: The Google DeepMind MuJoCo Menagerie Crazyflie 2 model actuator limits are uncalibrated and untuned. They reflect nominal aerodynamic approximations, not real hardware rotor dynamics.
2. **Software Falsification vs. Airworthiness**: A successful simulation trial or qualification sweep demonstrates only that a controller did not violate bounds within the synthetic scenario. It is never a certificate of real-world flight safety.
3. **No Fake Passes**: When evidence is incomplete or metrics cannot be attributed, Dómnir strictly emits `INCONCLUSIVE`, `PARTIAL`, or `OBSERVED_EXIT_CAUSE_UNKNOWN`, never invented `PASS` or `SAFE` statuses.

---

## 13. License, Security, and Privacy

- **License**: Licensed under the [MIT License](LICENSE) (MIT-compliant open source license).
- **Security Policy**: See [SECURITY.md](SECURITY.md) for vulnerability reporting and containment threat models.
- **Privacy Policy**: See [PRIVACY.md](PRIVACY.md) for our zero-telemetry, ephemeral sandbox privacy principles.
