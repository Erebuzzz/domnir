# Ragnarök Gauntlet calibration

**Date:** 2026-11-08
**Re-run:** `python scripts/calibrate_gauntlet.py` (exits 1 if the default Gauntlet no longer completes or any deadline has no margin)

## Why the Gauntlet was recalibrated

Once stage deadlines were enforced (V7 audit item P0-A), the default Gauntlet returned `NOT_COMPLETED` (1/5 stages). Measuring the baseline with relaxed deadlines turned up three separate problems:

1. **The baseline yaw loop had the wrong sign.** `cf2.xml` gives all three moment actuators a gear of `-1e-5`. Roll and pitch flipped the sign to compensate, but yaw did not, so the yaw loop was positive feedback. Yaw stayed at zero until pad contact disturbed it. Then it diverged, the vehicle flipped, and it fell through the floor. With relaxed deadlines it reached z = −90 m.
2. **Attitude gains were about 100× too small for the model.** Full moment command (1e-5 N·m) on Ixx = 2.3951e-5 kg·m² gives only about 0.42 rad/s² of angular acceleration. With kp_att = 0.35, attitude tracking was much slower than the position loop. The vehicle drifted rather than flew: it took 2.6 s to reach the slalom waypoint and overshot the pad by more than 0.4 m.
3. **The landing geometry could not be satisfied.**
   - The landing target was z = 0.02 m, the pad's centre, which is inside the pad box (top at z = 0.04 m).
   - The approach waypoint was 0.15 m short of the pad, so the vehicle arrived with horizontal speed and slid past.
   - Waypoint tolerances of 0.20–0.25 m let stages "complete" well away from the intended path.

## Changes

**Baseline controller** (`domnir/controls/baseline_3d.py`). Gains are derived from the pinned model instead of hand-picked:

| Loop | Natural frequency | Damping | Gains |
|---|---:|---:|---|
| Roll/pitch attitude | 4.0 rad/s | 0.9 | kp = 38.32, kd = 17.245 |
| Yaw attitude | 1.5 rad/s | 0.9 | kp = 7.278, kd = 8.734 (sign fixed) |
| Horizontal position | 1.2 rad/s | 0.9 | kp = 1.44, kd = 2.16 |
| Vertical position | unchanged | | kp = 6.5, kd = 3.2 |

The tilt limit drops from 0.60 rad to 0.30 rad, which keeps the outer loop well inside the attitude bandwidth. The derivation is kp = wn²·I / 1e-5 and kd = 2·zeta·wn·I / 1e-5.

**Default Gauntlet mission** (`domnir/missions/defaults.py`):

| Stage | Target (m) | Tolerance (m) | Old deadline | New deadline | Baseline arrival | Margin |
|---|---|---:|---:|---:|---:|---:|
| takeoff | (0, 0, 0.25) | 0.10 | 0.80 s | 0.80 s | 0.542 s | +0.258 s (48%) |
| slalom_pillar | (0.35, −0.05, 0.35) | 0.20 → **0.12** | 1.80 s | **2.80 s** | 2.176 s | +0.624 s (29%) |
| transit_gate | (0.70, −0.05, 0.38) | 0.20 → **0.10** | 2.80 s | **5.00 s** | 4.084 s | +0.916 s (22%) |
| approach_pad | (1.00, −0.02, 0.25) → **(1.15, 0, 0.25)** | 0.20 → **0.08** | 3.60 s | **7.50 s** | 6.164 s | +1.336 s (22%) |
| precision_touchdown | (1.15, 0, 0.02) → **(1.15, 0, 0.06)** | 0.25 → **0.10** | 4.50 s | **9.00 s** | 7.436 s | +1.564 s (21%) |

Tolerances were tightened, not relaxed, so a stage only counts when the vehicle is actually at the waypoint. Each deadline sits about 20–30% after the baseline's measured arrival.

## Result with the defaults

- `mission_verdict = COMPLETED` (5/5 stages on time). `physical_verdict = NOT_FALSIFIED`. Minimum robustness 0.040 m (altitude floor).
- 236 pad contacts, maximum touchdown speed 0.062 m/s against a 1.5 m/s limit. Zero obstacle contacts.
- The vehicle crosses the gate plane inside the aperture and passes south of the pillar. `tests/test_gauntlet_calibration_and_rate.py` checks both.
- Precision-landing still completes (2/2). The other mission tests in the repo pass unchanged.

## Limits

- The margins only hold for the nominal, wind-free course. Measured with a 1.5 s lateral gust starting at t = 1.5 s:

  | Gust F_y | Mission | Physical | Note |
  |---:|---|---|---|
  | +0.010 N | NOT_COMPLETED (1/5) | FALSIFIED | pushed into the pillar (51 obstacle contacts) |
  | −0.010 N | NOT_COMPLETED (1/5) | NOT_FALSIFIED | misses the slalom deadline |
  | +0.015 N | NOT_COMPLETED (1/5) | FALSIFIED | collision, then speed limit breached |
  | −0.015 N | NOT_COMPLETED (1/5) | NOT_FALSIFIED | misses the slalom deadline, 0.004 m pillar clearance |

  Even a 0.01 N gust (about 4% of hover thrust) defeats the baseline, so the gust-loaded Gauntlet is an open problem for the controller, not a calibrated pass.
- The open-field default was recalibrated separately. Its deadlines are now 0.85 / 2.20 / 3.10 s (were 0.25 / 0.60 / 0.90 s), against baseline arrivals of 0.644 / 1.738 / 2.450 s, which leaves 26–32% margin. Targets and tolerances are unchanged. `gate-corridor` and `wind-tunnel` share this default, so their missions never go near the gate or between the walls. They need missions of their own.
- The gains are derived from an uncalibrated simulation model (see `docs/MODEL_CALIBRATION.md`). They say nothing about the real Crazyflie.
