"""Pre-configured world scenes and entity registry."""

from __future__ import annotations

from .schema import EntityKind, Pose3D, WorldEntity, WorldSpec


def open_field_world() -> WorldSpec:
    return WorldSpec(
        world_id="open-field",
        name="Open Field Arena",
        floor_dimensions_m=[4.0, 4.0],
        entities=[],
    )


def gate_corridor_world() -> WorldSpec:
    gate = WorldEntity(
        id="gate-1",
        kind=EntityKind.GATE,
        pose=Pose3D(position_m=[0.65, 0.0, 0.35]),
        dimensions_m=[0.05, 0.55, 0.05],
        aperture_m=[0.45, 0.45],
        frame_width_m=0.04,
        contact_class="obstacle",
        visual_asset_id="gate_01.glb",
    )
    return WorldSpec(
        world_id="gate-corridor",
        name="Gate Corridor Arena",
        entities=[gate],
    )


def precision_landing_world() -> WorldSpec:
    pad = WorldEntity(
        id="pad-target",
        kind=EntityKind.LANDING_PAD,
        pose=Pose3D(position_m=[0.80, 0.0, 0.02]),
        dimensions_m=[0.30, 0.30, 0.04],
        contact_class="allowed-touchdown",
        visual_asset_id="landing_pad.glb",
    )
    return WorldSpec(
        world_id="precision-landing",
        name="Precision Landing Arena",
        entities=[pad],
    )


def wind_tunnel_world() -> WorldSpec:
    wall_left = WorldEntity(
        id="wall-left",
        kind=EntityKind.WALL,
        pose=Pose3D(position_m=[0.50, 0.45, 0.50]),
        dimensions_m=[1.60, 0.05, 1.00],
        contact_class="obstacle",
    )
    wall_right = WorldEntity(
        id="wall-right",
        kind=EntityKind.WALL,
        pose=Pose3D(position_m=[0.50, -0.45, 0.50]),
        dimensions_m=[1.60, 0.05, 1.00],
        contact_class="obstacle",
    )
    return WorldSpec(
        world_id="wind-tunnel",
        name="Wind Tunnel Corridor",
        entities=[wall_left, wall_right],
    )


def ragnarok_gauntlet_world() -> WorldSpec:
    # Slalom pillar
    pillar = WorldEntity(
        id="slalom-pillar",
        kind=EntityKind.CYLINDER_OBSTACLE,
        pose=Pose3D(position_m=[0.35, 0.15, 0.40]),
        dimensions_m=[0.12, 0.80],  # radius=0.06, height=0.80
        contact_class="obstacle",
    )
    # Transit gate
    gate = WorldEntity(
        id="gauntlet-gate",
        kind=EntityKind.GATE,
        pose=Pose3D(position_m=[0.70, -0.10, 0.40]),
        dimensions_m=[0.05, 0.55, 0.05],
        aperture_m=[0.45, 0.45],
        frame_width_m=0.04,
        contact_class="obstacle",
    )
    # Landing pad
    pad = WorldEntity(
        id="gauntlet-pad",
        kind=EntityKind.LANDING_PAD,
        pose=Pose3D(position_m=[1.15, 0.0, 0.02]),
        dimensions_m=[0.35, 0.35, 0.04],
        contact_class="allowed-touchdown",
    )
    return WorldSpec(
        world_id="ragnarok-gauntlet",
        name="The Ragnarök Gauntlet",
        entities=[pillar, gate, pad],
    )


_REGISTRY: dict[str, callable] = {
    "open-field": open_field_world,
    "gate-corridor": gate_corridor_world,
    "precision-landing": precision_landing_world,
    "wind-tunnel": wind_tunnel_world,
    "ragnarok-gauntlet": ragnarok_gauntlet_world,
}


def get_world(world_id: str) -> WorldSpec:
    factory = _REGISTRY.get(world_id, open_field_world)
    return factory()


def list_worlds() -> list[dict[str, str]]:
    return [
        {"id": k, "name": fn().name}
        for k, fn in _REGISTRY.items()
    ]
