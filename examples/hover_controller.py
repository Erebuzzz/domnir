"""Guest-only altitude controller for integration testing."""


def observe(observation):
    altitude = observation["position_m"][2]
    velocity = observation["velocity_mps"][2]
    thrust = max(0.0, min(0.35, 0.26487 + 0.15 * (0.1 - altitude) - 0.08 * velocity))
    return {
        "schema_version": "1.0",
        "trial_id": observation["trial_id"],
        "step_index": observation["step_index"],
        "thrust": thrust,
        "moment_x": 0.0,
        "moment_y": 0.0,
        "moment_z": 0.0,
    }
