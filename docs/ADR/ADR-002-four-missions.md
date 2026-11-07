# ADR-002: Four-Mission Architecture, 3D Flight Dynamics, WorldSpec, and Coordinated Trust Boundaries

- **Status:** Accepted
- **Date:** 2026-11-08
- **Deciders:** Lead Engineering Orchestrator (O0), Controls Working Group (C1), Physics Authority (P1), Mission & Safety (M1)
- **Consulted:** Vultr Serverless Inference Team, Forseti Simulation Team, Security Working Group (S1)

---

## 1. Context and Problem Statement

Dómnir V4 demonstrated rigorous single-axis (altitude-only) flight falsification, deterministic replay, microVM isolation, and tamper-evident Court Records. However, real physical drone missions require six-degree-of-freedom (6-DoF) motion:
1. 3D waypoint navigation and trajectory tracking.
2. Obstacle avoidance through physical gates and corridors.
3. Admissible environmental disturbances (3D wind gusts) and observation/actuator faults.
4. Precision landing on designated pads with touchdown dynamics and safe recovery.

We require a backwards-compatible architectural evolution from `FlightSpec` (V1) to `MissionSpecV2` and `WorldSpecV1` while strictly preserving:
- Non-negotiable microVM isolation (no host execution of untrusted controller code).
- Exclusive Vultr Serverless Inference backend routing.
- Low-level action frame contract: collective thrust and body moments (`thrust`, `moment_x`, `moment_y`, `moment_z`).
- Deterministic MuJoCo physics ownership by Forseti on the trusted host.
- RFC 8785 canonical Court Record verification.

---

## 2. Action Protocol & Coordinate Frames

### 2.1 Action Frame Contract (Protocol 1.0)
The Bitcraze Crazyflie 2.0 MuJoCo model (`cf2.xml`) exposes four generalized actuator channels:
1. `body_thrust`: Range $[0.0, 0.35]$ N along body Z-axis.
2. `x_moment`: Range $[-1.0, 1.0]$ roll moment gear.
3. `y_moment`: Range $[-1.0, 1.0]$ pitch moment gear.
4. `z_moment`: Range $[-1.0, 1.0]$ yaw moment gear.

```json
{
  "schema_version": "1.0",
  "trial_id": "trial-uuid",
  "step_index": 42,
  "thrust": 0.26487,
  "moment_x": 0.0,
  "moment_y": 0.0,
  "moment_z": 0.0
}
```
**Invariant:** Actuator channels represent collective thrust and body attitude moments, NOT individual rotor motor thrusts.

### 2.2 Coordinate Frames
- **World Frame:** Right-handed Cartesian frame, $+X$ East/Forward, $+Y$ North/Left, $+Z$ Up (against gravity $\mathbf{g} = [0, 0, -9.81]$ m/s$^2$).
- **Body Frame:** Centered at vehicle center of mass, $+X$ forward arm axis, $+Y$ left arm axis, $+Z$ upward normal through top deck.
- **Orientation:** Unit quaternions in MuJoCo WXYZ format $[w, x, y, z]$.
- **Three.js Conversion:** Three.js uses right-handed Y-up coordinates. The client-side visualizer maps MuJoCo $[x, y, z]$ to Three.js $[x, z, -y]$ via a tested adapter. The physics engine remains the sole spatial authority.

---

## 3. Data Models: MissionSpecV2 and WorldSpecV1

### 3.1 MissionSpecV2
`MissionSpecV2` extends mission definition from a scalar altitude target into an ordered sequence of typed flight stages:
- `TAKEOFF`: Ascend from launch surface to safe cruising altitude.
- `WAYPOINT`: Timed navigation to spatial sphere with tolerance radius and dwell requirement.
- `CORRIDOR`: Constrained corridor transit with minimum obstacle clearance boundaries.
- `LANDING`: Controlled approach, descent, and touchdown onto an admissible landing pad.
- `RECOVERY`: Contingency stabilization or safe abort upon perturbation.

### 3.2 WorldSpecV1
`WorldSpecV1` defines declarative physical scenes compiled into native MuJoCo MJCF:
- `Obstacle`: Static bounding boxes, cylinders, and walls with collision classes.
- `Gate`: True open aperture frames composed of 4 boundary bars, ensuring physical passability through the center opening.
- `LandingPad`: Permitted touchdown geometry with distinct collision filtering (`allowed-touchdown`).
- `DynamicObstacle`: Time-dependent kinematic obstacles with deterministic paths.

---

## 4. Trust Boundaries & Execution Lifecycle

1. **Guest Isolation:** Controller source code executes exclusively inside a Microsandbox microVM with default-deny network and memory/CPU quotas.
2. **Observation Ingestion:** The guest receives versioned observation payloads (`position_m`, `velocity_mps`, `orientation_quat_wxyz`, `body_angular_velocity_rps`, `target_position_m`, `stage_id`).
3. **Sensor Fault Invariance:** Observation noise, bias, delay, and dropouts are applied strictly inside the guest observation adapter. Safety monitors evaluate ground-truth state.
4. **Disturbance Invariance:** 3D wind gusts and environmental forces are applied directly to the MuJoCo plant on the host via `data.xfrc_applied`.
5. **Adjudication Separation:** Safety evaluation separates **physical violation status** (`FALSIFIED`, `NOT_FALSIFIED`, `INVALID`) from **mission completion status** (`COMPLETED`, `NOT_COMPLETED`, `ABORTED`).

---

## 5. Consequences & Backwards Compatibility

- **V1 Preserved:** Existing `FlightSpec` requests and historic Court Records remain fully functional and verifiable.
- **Compiler Determinism:** World compilation and scenario generation are completely reproducible from integer seeds.
- **Evidence Integrity:** Court Record V2 extends the trajectory dataset with 3D positions, contacts, stage transitions, and fault logs, serialized with RFC 8785 canonical encoding.
