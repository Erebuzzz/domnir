"""Default missions for the registered worlds.

The Ragnarök Gauntlet stages are calibrated against the built-in baseline
controller; ``scripts/calibrate_gauntlet.py`` re-measures the baseline flight
and reports the margin left by each deadline (see
docs/audits/GAUNTLET_CALIBRATION.md).
"""

from __future__ import annotations

from domnir.missions.schema import MissionConstraints, MissionSpecV2, MissionStage, MissionStageKind


def default_mission(world_id: str) -> tuple[MissionSpecV2, list[float]]:
    """Return the default mission and initial position for a registered world."""
    if world_id == "precision-landing":
        stages = [
            MissionStage(
                id="approach",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.80, 0.0, 0.08],
                tolerance_m=0.06,
                dwell_s=0.02,
                completion_deadline_s=0.40,
            ),
            MissionStage(
                id="touchdown",
                kind=MissionStageKind.LANDING,
                target_position_m=[0.80, 0.0, 0.02],
                tolerance_m=0.08,
                dwell_s=0.02,
                completion_deadline_s=1.50,
                pad_id="pad-target",
            ),
        ]
        constraints = MissionConstraints(
            min_altitude_m=0.01,
            max_landing_impact_speed_mps=1.0,
            fail_on_unpermitted_contact=True,
        )
        init_pos = [0.80, 0.0, 0.15]
    elif world_id == "ragnarok-gauntlet":
        # Calibrated against the built-in baseline (see
        # docs/audits/GAUNTLET_CALIBRATION.md). Nominal baseline arrival
        # times are 0.54 / 2.18 / 4.08 / 6.16 / 7.44 s; each deadline
        # leaves roughly 20-30% margin over that flight.
        stages = [
            MissionStage(
                id="takeoff",
                kind=MissionStageKind.TAKEOFF,
                target_position_m=[0.0, 0.0, 0.25],
                tolerance_m=0.10,
                dwell_s=0.0,
                completion_deadline_s=0.80,
            ),
            MissionStage(
                # 0.20 m south of the pillar axis (pillar radius 0.06 m).
                id="slalom_pillar",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.35, -0.05, 0.35],
                tolerance_m=0.12,
                dwell_s=0.0,
                completion_deadline_s=2.80,
            ),
            MissionStage(
                # Inside the gate aperture (y in [-0.325, 0.125], z in [0.175, 0.625]).
                id="transit_gate",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.70, -0.05, 0.38],
                tolerance_m=0.10,
                dwell_s=0.0,
                completion_deadline_s=5.00,
            ),
            MissionStage(
                # Directly above the pad so the descent is vertical.
                id="approach_pad",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[1.15, 0.0, 0.25],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=7.50,
            ),
            MissionStage(
                # Pad top is z = 0.04 m; the body centre rests ~0.02 m above it.
                id="precision_touchdown",
                kind=MissionStageKind.LANDING,
                target_position_m=[1.15, 0.0, 0.06],
                tolerance_m=0.10,
                dwell_s=0.01,
                completion_deadline_s=9.00,
                pad_id="gauntlet-pad",
            ),
        ]
        constraints = MissionConstraints(
            min_altitude_m=0.01,
            max_altitude_m=1.20,
            max_speed_mps=3.5,
            max_tilt_deg=55.0,
            fail_on_unpermitted_contact=True,
            max_landing_impact_speed_mps=1.5,
        )
        init_pos = [0.0, 0.0, 0.05]
    elif world_id == "gate-corridor":
        # Gate at x = 0.65, y = 0.0, center z = 0.35, aperture 0.45 x 0.45 m.
        # Calibrated against baseline arrival times: 0.628 / 2.438 / 4.526 / 6.550 s.
        # Deadlines set for >= 20% margin.
        stages = [
            MissionStage(
                id="takeoff",
                kind=MissionStageKind.TAKEOFF,
                target_position_m=[0.0, 0.0, 0.25],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=0.85,
            ),
            MissionStage(
                id="approach_gate",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.35, 0.0, 0.35],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=3.10,
            ),
            MissionStage(
                id="transit_gate",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.75, 0.0, 0.35],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=5.60,
            ),
            MissionStage(
                id="exit_corridor",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[1.10, 0.0, 0.30],
                tolerance_m=0.08,
                dwell_s=0.02,
                completion_deadline_s=8.00,
            ),
        ]
        constraints = MissionConstraints(
            min_altitude_m=0.02,
            max_altitude_m=1.00,
            max_tilt_deg=55.0,
            fail_on_unpermitted_contact=True,
        )
        init_pos = [0.0, 0.0, 0.05]
    elif world_id == "wind-tunnel":
        # Lateral walls at y = +-0.45 m spanning x in [-0.30, 1.30] m.
        # Flight path along y = 0.0 stays centered between the walls.
        # Calibrated against baseline arrival times: 0.628 / 2.430 / 4.462 / 6.462 s.
        # Deadlines set for >= 20% margin.
        stages = [
            MissionStage(
                id="takeoff",
                kind=MissionStageKind.TAKEOFF,
                target_position_m=[0.0, 0.0, 0.25],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=0.85,
            ),
            MissionStage(
                id="corridor_entry",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.35, 0.0, 0.30],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=3.10,
            ),
            MissionStage(
                id="corridor_mid",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.70, 0.0, 0.30],
                tolerance_m=0.08,
                dwell_s=0.0,
                completion_deadline_s=5.50,
            ),
            MissionStage(
                id="corridor_exit",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[1.05, 0.0, 0.30],
                tolerance_m=0.08,
                dwell_s=0.02,
                completion_deadline_s=7.90,
            ),
        ]
        constraints = MissionConstraints(
            min_altitude_m=0.02,
            max_altitude_m=1.00,
            max_tilt_deg=55.0,
            fail_on_unpermitted_contact=True,
        )
        init_pos = [0.0, 0.0, 0.05]
    else:
        # Open field (and any other world without its own default).
        # Calibrated against the built-in baseline: measured arrivals are
        # 0.644 / 1.738 / 2.450 s, so each deadline leaves ~26-32% margin.
        stages = [
            MissionStage(
                id="takeoff",
                kind=MissionStageKind.TAKEOFF,
                target_position_m=[0.0, 0.0, 0.20],
                tolerance_m=0.06,
                dwell_s=0.02,
                completion_deadline_s=0.85,
            ),
            MissionStage(
                id="slalom_waypoint",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.10, -0.05, 0.22],
                tolerance_m=0.08,
                dwell_s=0.02,
                completion_deadline_s=2.20,
            ),
            MissionStage(
                id="terminal_approach",
                kind=MissionStageKind.WAYPOINT,
                target_position_m=[0.15, 0.0, 0.15],
                tolerance_m=0.08,
                dwell_s=0.02,
                completion_deadline_s=3.10,
            ),
        ]
        constraints = MissionConstraints(
            min_altitude_m=0.02,
            max_altitude_m=1.00,
            max_tilt_deg=55.0,
            fail_on_unpermitted_contact=True,
        )
        init_pos = [0.0, 0.0, 0.05]

    mission = MissionSpecV2(
        mission_id=f"mission-{world_id}",
        world_id=world_id,
        stages=stages,
        constraints=constraints,
    )
    return mission, init_pos
