"""World specification schema for physical 3D simulation scenes."""

from __future__ import annotations

from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, model_validator


class EntityKind(str, Enum):
    BOX_OBSTACLE = "box_obstacle"
    CYLINDER_OBSTACLE = "cylinder_obstacle"
    GATE = "gate"
    LANDING_PAD = "landing_pad"
    WALL = "wall"
    DYNAMIC_OBSTACLE = "dynamic_obstacle"


class Pose3D(BaseModel):
    position_m: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    quaternion_wxyz: list[float] = Field(default_factory=lambda: [1.0, 0.0, 0.0, 0.0])

    @model_validator(mode="after")
    def validate_pose(self) -> Pose3D:
        if len(self.position_m) != 3:
            raise ValueError(f"position_m must have 3 coordinates, got {len(self.position_m)}")
        if len(self.quaternion_wxyz) != 4:
            raise ValueError(f"quaternion_wxyz must have 4 components [w, x, y, z], got {len(self.quaternion_wxyz)}")
        return self


class WorldEntity(BaseModel):
    id: str
    kind: EntityKind
    pose: Pose3D = Field(default_factory=Pose3D)
    dimensions_m: list[float] = Field(default_factory=lambda: [0.2, 0.2, 0.2])
    aperture_m: list[float] | None = None
    frame_width_m: float = 0.04
    contact_class: str = "obstacle"  # "obstacle", "allowed-touchdown", "boundary"
    visual_asset_id: str | None = None
    trajectory: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def validate_entity(self) -> WorldEntity:
        if self.kind == EntityKind.GATE and not self.aperture_m:
            self.aperture_m = [0.40, 0.40]
        if self.kind == EntityKind.LANDING_PAD:
            self.contact_class = "allowed-touchdown"
        return self


class WorldSpec(BaseModel):
    schema_version: str = "world-v1"
    world_id: str
    name: str = "Custom Flight Arena"
    units: str = "SI"
    coordinate_frame: str = "world-z-up-right-handed"
    floor_dimensions_m: list[float] = Field(default_factory=lambda: [4.0, 4.0])
    entities: list[WorldEntity] = Field(default_factory=list)

    def get_entity(self, entity_id: str) -> WorldEntity | None:
        for ent in self.entities:
            if ent.id == entity_id:
                return ent
        return None
