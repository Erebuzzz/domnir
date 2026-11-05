"""Validate controller response frames before they reach the simulator."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

ACTION_KEYS = ("thrust", "moment_x", "moment_y", "moment_z")
MAX_FRAME_BYTES = 4096


class InvalidFrame(ValueError):
    """A controller frame does not match the expected contract."""


@dataclass(frozen=True)
class ActionBounds:
    lower: tuple[float, ...]
    upper: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.lower) != 4 or len(self.upper) != 4:
            raise ValueError("Action bounds must have four components")
        if any(not math.isfinite(x) for x in (*self.lower, *self.upper)):
            raise ValueError("Action bounds must be finite")
        if any(low > high for low, high in zip(self.lower, self.upper, strict=True)):
            raise ValueError("Action lower bound exceeds upper bound")


def _object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidFrame("Duplicate JSON key")
        result[key] = value
    return result


def parse_action(
    payload: bytes, *, trial_id: str, step_index: int, bounds: ActionBounds
) -> tuple[float, float, float, float]:
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise InvalidFrame("Invalid frame size")
    try:
        frame = json.loads(payload, object_pairs_hook=_object_without_duplicates)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise InvalidFrame("Invalid JSON frame") from error
    required = {"schema_version", "trial_id", "step_index", *ACTION_KEYS}
    if not isinstance(frame, dict) or set(frame) != required:
        raise InvalidFrame("Unexpected frame fields")
    if frame["schema_version"] != "1.0" or frame["trial_id"] != trial_id:
        raise InvalidFrame("Frame version or trial mismatch")
    if type(frame["step_index"]) is not int or frame["step_index"] != step_index:
        raise InvalidFrame("Frame step mismatch")
    values = []
    for name, lower, upper in zip(ACTION_KEYS, bounds.lower, bounds.upper, strict=True):
        value = frame[name]
        if type(value) not in (int, float):
            raise InvalidFrame(f"{name} must be numeric")
        try:
            number = float(value)
        except OverflowError as error:
            raise InvalidFrame(f"{name} is not finite") from error
        if not math.isfinite(number) or not lower <= number <= upper:
            raise InvalidFrame(f"{name} outside the permitted range")
        values.append(number)
    return (values[0], values[1], values[2], values[3])
