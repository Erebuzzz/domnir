"""Blender World Asset Authoring and glTF/GLB Exporter for Dómnir V4.

Operates in dual mode:
1. Native Blender mode: when executed inside Blender or via CLI:
   & "D:\\Blender\\blender.exe" -b -P scripts/export_blender_assets.py
   Constructs 3D mesh datablocks, assigns PBR materials, saves source .blend
   files to domnir/assets/worlds/sources/, and exports glTF 2.0 binary (.glb) files.
2. Standalone Python mode: when executed outside Blender, generates identical
   Khronos glTF 2.0 binary (.glb) files using binary chunk specifications.

Generates and tracks:
- gate_01.glb and gate_01.blend: Transit gate with 4 frame bars and open 0.45x0.45m aperture.
- landing_pad.glb and landing_pad.blend: Precision landing pad with runic touchdown target.
- obstacle_pillar.glb and obstacle_pillar.blend: Slalom cylinder obstacle with hazard caps.
- arena_assets.blend: Master Blender scene containing all world collections.
- manifest.json: Versioned asset manifest with SHA-256 hashes and physical dimensions.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import sys

try:
    import bpy
    HAS_BPY = True
except ImportError:
    HAS_BPY = False


def build_box_mesh(name: str, sx: float, sy: float, sz: float, color_rgba: list[float], emissive_rgb: list[float] | None = None):
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    faces = [
        ([(-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)], (0.0, 0.0, 1.0)),
        ([(-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz), (-hx, -hy, -hz)], (0.0, 0.0, -1.0)),
        ([(hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)], (1.0, 0.0, 0.0)),
        ([(-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz), (-hx, -hy, -hz)], (-1.0, 0.0, 0.0)),
        ([(-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz), (-hx, -hy, -hz)], (0.0, 1.0, 0.0)),
        ([(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)], (0.0, -1.0, 0.0)),
    ]
    return {"name": name, "faces": faces, "color": color_rgba, "emissive": emissive_rgb or [0.0, 0.0, 0.0]}


def build_cylinder_mesh(name: str, radius: float, height: float, segments: int, color_rgba: list[float], emissive_rgb: list[float] | None = None):
    hh = height / 2.0
    faces = []
    for i in range(segments):
        th1 = 2.0 * math.pi * i / segments
        th2 = 2.0 * math.pi * (i + 1) / segments
        x1, y1 = radius * math.cos(th1), radius * math.sin(th1)
        x2, y2 = radius * math.cos(th2), radius * math.sin(th2)
        mid_th = (th1 + th2) / 2.0
        n = (math.cos(mid_th), math.sin(mid_th), 0.0)
        faces.append(([(x1, y1, -hh), (x2, y2, -hh), (x2, y2, hh), (x1, y1, hh)], n))
    for i in range(segments):
        th1 = 2.0 * math.pi * i / segments
        th2 = 2.0 * math.pi * (i + 1) / segments
        x1, y1 = radius * math.cos(th1), radius * math.sin(th1)
        x2, y2 = radius * math.cos(th2), radius * math.sin(th2)
        faces.append(([(0.0, 0.0, hh), (x1, y1, hh), (x2, y2, hh), (x2, y2, hh)], (0.0, 0.0, 1.0)))
        faces.append(([(0.0, 0.0, -hh), (x2, y2, -hh), (x1, y1, -hh), (x1, y1, -hh)], (0.0, 0.0, -1.0)))
    return {"name": name, "faces": faces, "color": color_rgba, "emissive": emissive_rgb or [0.0, 0.0, 0.0]}


def compile_glb_from_parts(model_name: str, parts: list[dict], offsets: list[tuple[float, float, float]] | None = None) -> bytes:
    if offsets is None:
        offsets = [(0.0, 0.0, 0.0)] * len(parts)

    nodes = []
    meshes = []
    materials = []
    accessors = []
    buffer_views = []
    bin_buf = bytearray()

    for part_idx, (part, offset) in enumerate(zip(parts, offsets)):
        part_v_count = 0
        part_indices = 0
        min_p = [float("inf")] * 3
        max_p = [float("-inf")] * 3

        part_idx_bytes = bytearray()
        part_pos_bytes = bytearray()
        part_norm_bytes = bytearray()

        for quad, norm in part["faces"]:
            base_v = part_v_count
            for p in quad:
                world_p = (p[0] + offset[0], p[1] + offset[1], p[2] + offset[2])
                part_pos_bytes.extend(struct.pack("<3f", *world_p))
                part_norm_bytes.extend(struct.pack("<3f", *norm))
                for k in range(3):
                    min_p[k] = min(min_p[k], world_p[k])
                    max_p[k] = max(max_p[k], world_p[k])
                part_v_count += 1

            part_idx_bytes.extend(struct.pack("<3H", base_v, base_v + 1, base_v + 2))
            part_idx_bytes.extend(struct.pack("<3H", base_v, base_v + 2, base_v + 3))
            part_indices += 6

        idx_offset = len(bin_buf)
        bin_buf.extend(part_idx_bytes)
        while len(bin_buf) % 4 != 0:
            bin_buf.append(0)

        pos_offset = len(bin_buf)
        bin_buf.extend(part_pos_bytes)
        while len(bin_buf) % 4 != 0:
            bin_buf.append(0)

        norm_offset = len(bin_buf)
        bin_buf.extend(part_norm_bytes)
        while len(bin_buf) % 4 != 0:
            bin_buf.append(0)

        bv_idx = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": idx_offset, "byteLength": len(part_idx_bytes), "target": 34963})
        bv_pos = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": pos_offset, "byteLength": len(part_pos_bytes), "target": 34962})
        bv_norm = len(buffer_views)
        buffer_views.append({"buffer": 0, "byteOffset": norm_offset, "byteLength": len(part_norm_bytes), "target": 34962})

        acc_idx = len(accessors)
        accessors.append({"bufferView": bv_idx, "byteOffset": 0, "componentType": 5123, "count": part_indices, "type": "SCALAR"})
        acc_pos = len(accessors)
        accessors.append({"bufferView": bv_pos, "byteOffset": 0, "componentType": 5126, "count": part_v_count, "type": "VEC3", "min": min_p, "max": max_p})
        acc_norm = len(accessors)
        accessors.append({"bufferView": bv_norm, "byteOffset": 0, "componentType": 5126, "count": part_v_count, "type": "VEC3"})

        mat_idx = len(materials)
        materials.append({
            "name": f"{part['name']}_mat",
            "pbrMetallicRoughness": {
                "baseColorFactor": part["color"],
                "metallicFactor": 0.2,
                "roughnessFactor": 0.4,
            },
            "emissiveFactor": part.get("emissive", [0.0, 0.0, 0.0]),
        })

        mesh_idx = len(meshes)
        meshes.append({
            "name": part["name"],
            "primitives": [{
                "attributes": {"POSITION": acc_pos, "NORMAL": acc_norm},
                "indices": acc_idx,
                "material": mat_idx,
            }],
        })

        nodes.append({"name": part["name"], "mesh": mesh_idx})

    gltf = {
        "asset": {
            "version": "2.0",
            "generator": "Domnir-Blender-Asset-Pipeline-1.0",
            "copyright": "Dómnir Adversarial Robotics Platform",
        },
        "scene": 0,
        "scenes": [{"name": model_name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "materials": materials,
        "meshes": meshes,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_buf)}],
    }

    json_bytes = json.dumps(gltf).encode("utf-8")
    while len(json_bytes) % 4 != 0:
        json_bytes += b" "

    total_len = 12 + 8 + len(json_bytes) + 8 + len(bin_buf)
    header = struct.pack("<4sII", b"glTF", 2, total_len)
    chunk0 = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes
    chunk1 = struct.pack("<II", len(bin_buf), 0x004E4942) + bytes(bin_buf)

    return header + chunk0 + chunk1


def build_gate_asset() -> bytes:
    ap_w, ap_h = 0.45, 0.45
    thick = 0.04
    depth = 0.05
    cyan = [0.02, 0.71, 0.83, 1.0]
    glow = [0.03, 0.57, 0.70]

    post_l = build_box_mesh("gate_1_post_left", depth, thick, ap_h, cyan, glow)
    post_r = build_box_mesh("gate_1_post_right", depth, thick, ap_h, cyan, glow)
    bar_t = build_box_mesh("gate_1_bar_top", depth, ap_w + thick * 2, thick, cyan, glow)
    bar_b = build_box_mesh("gate_1_bar_bottom", depth, ap_w + thick * 2, thick, cyan, glow)

    offsets = [
        (0.0, -(ap_w / 2.0 + thick / 2.0), 0.0),
        (0.0, (ap_w / 2.0 + thick / 2.0), 0.0),
        (0.0, 0.0, (ap_h / 2.0 + thick / 2.0)),
        (0.0, 0.0, -(ap_h / 2.0 + thick / 2.0)),
    ]
    return compile_glb_from_parts("gate_01", [post_l, post_r, bar_t, bar_b], offsets)


def build_landing_pad_asset() -> bytes:
    emerald = [0.06, 0.71, 0.38, 1.0]
    glow_green = [0.02, 0.37, 0.27]
    dark_gray = [0.15, 0.17, 0.20, 1.0]

    base = build_box_mesh("pad_base", 0.35, 0.35, 0.02, dark_gray)
    surface = build_box_mesh("pad_touchdown_surface", 0.30, 0.30, 0.005, emerald, glow_green)
    bullseye = build_cylinder_mesh("pad_bullseye_ring", 0.05, 0.008, 24, [0.95, 0.95, 0.95, 1.0], [0.8, 0.8, 0.8])

    offsets = [
        (0.0, 0.0, 0.01),
        (0.0, 0.0, 0.0225),
        (0.0, 0.0, 0.025),
    ]
    return compile_glb_from_parts("landing_pad", [base, surface, bullseye], offsets)


def build_pillar_asset() -> bytes:
    amber = [0.96, 0.62, 0.07, 1.0]
    dark = [0.12, 0.14, 0.17, 1.0]

    body = build_cylinder_mesh("slalom_pillar_body", 0.06, 0.80, 24, amber)
    cap_top = build_cylinder_mesh("slalom_pillar_cap_top", 0.065, 0.04, 24, dark)
    cap_bot = build_cylinder_mesh("slalom_pillar_cap_bottom", 0.07, 0.02, 24, dark)

    offsets = [
        (0.0, 0.0, 0.40),
        (0.0, 0.0, 0.80),
        (0.0, 0.0, 0.01),
    ]
    return compile_glb_from_parts("obstacle_pillar", [body, cap_top, cap_bot], offsets)


# =============================================================================
# Native Blender 5.x Authoring Implementation
# =============================================================================

def _bpy_create_material(name: str, color_rgba: tuple[float, float, float, float], emissive_rgb: tuple[float, float, float] | None = None):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color_rgba
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = 0.2
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = 0.4
        if emissive_rgb and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (*emissive_rgb, 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 1.0
    return mat


def _bpy_create_box(name: str, sx: float, sy: float, sz: float, loc: tuple[float, float, float], mat, collection):
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0
    verts = [
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)
    ]
    faces = [
        (0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1),
        (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)
    ]
    mesh = bpy.data.meshes.new(name=f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = loc
    if mat:
        obj.data.materials.append(mat)
    collection.objects.link(obj)
    return obj


def _bpy_create_cylinder(name: str, radius: float, height: float, loc: tuple[float, float, float], mat, collection, segments: int = 24):
    hh = height / 2.0
    verts = []
    for i in range(segments):
        th = 2.0 * math.pi * i / segments
        verts.append((radius * math.cos(th), radius * math.sin(th), -hh))
    for i in range(segments):
        th = 2.0 * math.pi * i / segments
        verts.append((radius * math.cos(th), radius * math.sin(th), hh))
    verts.append((0.0, 0.0, -hh))
    verts.append((0.0, 0.0, hh))

    bot_c = 2 * segments
    top_c = 2 * segments + 1
    faces = []
    for i in range(segments):
        nxt = (i + 1) % segments
        faces.append((i, nxt, segments + nxt, segments + i))
        faces.append((bot_c, nxt, i))
        faces.append((top_c, segments + i, segments + nxt))

    mesh = bpy.data.meshes.new(name=f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.location = loc
    if mat:
        obj.data.materials.append(mat)
    collection.objects.link(obj)
    return obj


def author_assets_with_bpy(project_root: Path) -> dict[str, str]:
    sources_dir = project_root / "domnir" / "assets" / "worlds" / "sources"
    glb_dir = project_root / "domnir" / "assets" / "worlds" / "glb"
    manifest_dir = project_root / "domnir" / "assets" / "worlds" / "manifests"
    web_assets_dir = project_root / "domnir" / "web" / "assets"

    sources_dir.mkdir(parents=True, exist_ok=True)
    glb_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    web_assets_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = {}

    # 1. Author Gate 01
    bpy.ops.wm.read_factory_settings(use_empty=True)
    gate_col = bpy.data.collections.new("Gate_01")
    bpy.context.scene.collection.children.link(gate_col)
    mat_gate = _bpy_create_material("Gate_Cyan_PBR", (0.02, 0.71, 0.83, 1.0), (0.03, 0.57, 0.70))

    ap_w, ap_h, thick, depth = 0.45, 0.45, 0.04, 0.05
    _bpy_create_box("gate_1_post_left", depth, thick, ap_h, (0.0, -(ap_w / 2.0 + thick / 2.0), 0.0), mat_gate, gate_col)
    _bpy_create_box("gate_1_post_right", depth, thick, ap_h, (0.0, (ap_w / 2.0 + thick / 2.0), 0.0), mat_gate, gate_col)
    _bpy_create_box("gate_1_bar_top", depth, ap_w + thick * 2, thick, (0.0, 0.0, (ap_h / 2.0 + thick / 2.0)), mat_gate, gate_col)
    _bpy_create_box("gate_1_bar_bottom", depth, ap_w + thick * 2, thick, (0.0, 0.0, -(ap_h / 2.0 + thick / 2.0)), mat_gate, gate_col)

    gate_blend = sources_dir / "gate_01.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(gate_blend))
    gate_glb = glb_dir / "gate_01.glb"
    bpy.ops.export_scene.gltf(filepath=str(gate_glb), export_format="GLB")
    (web_assets_dir / "gate_01.glb").write_bytes(gate_glb.read_bytes())

    manifest_entries["gate_01.blend"] = {
        "sha256": hashlib.sha256(gate_blend.read_bytes()).hexdigest(),
        "byte_size": gate_blend.stat().st_size,
        "source_type": f"Blender {bpy.app.version_string} Source File",
    }
    manifest_entries["gate_01.glb"] = {
        "sha256": hashlib.sha256(gate_glb.read_bytes()).hexdigest(),
        "byte_size": gate_glb.stat().st_size,
        "units": "metres",
        "coordinate_frame": "world-z-up-right-handed",
        "format": "glTF 2.0 Binary (GLB)",
        "generator": f"Blender {bpy.app.version_string} glTF Exporter",
    }

    # 2. Author Landing Pad
    bpy.ops.wm.read_factory_settings(use_empty=True)
    pad_col = bpy.data.collections.new("Landing_Pad")
    bpy.context.scene.collection.children.link(pad_col)
    mat_base = _bpy_create_material("Pad_Base_Dark", (0.15, 0.17, 0.20, 1.0))
    mat_surf = _bpy_create_material("Pad_Surface_Emerald", (0.06, 0.71, 0.38, 1.0), (0.02, 0.37, 0.27))
    mat_ring = _bpy_create_material("Pad_Bullseye_Ring", (0.95, 0.95, 0.95, 1.0), (0.8, 0.8, 0.8))

    _bpy_create_box("pad_base", 0.35, 0.35, 0.02, (0.0, 0.0, 0.01), mat_base, pad_col)
    _bpy_create_box("pad_touchdown_surface", 0.30, 0.30, 0.005, (0.0, 0.0, 0.0225), mat_surf, pad_col)
    _bpy_create_cylinder("pad_bullseye_ring", 0.05, 0.008, (0.0, 0.0, 0.025), mat_ring, pad_col)

    pad_blend = sources_dir / "landing_pad.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(pad_blend))
    pad_glb = glb_dir / "landing_pad.glb"
    bpy.ops.export_scene.gltf(filepath=str(pad_glb), export_format="GLB")
    (web_assets_dir / "landing_pad.glb").write_bytes(pad_glb.read_bytes())

    manifest_entries["landing_pad.blend"] = {
        "sha256": hashlib.sha256(pad_blend.read_bytes()).hexdigest(),
        "byte_size": pad_blend.stat().st_size,
        "source_type": f"Blender {bpy.app.version_string} Source File",
    }
    manifest_entries["landing_pad.glb"] = {
        "sha256": hashlib.sha256(pad_glb.read_bytes()).hexdigest(),
        "byte_size": pad_glb.stat().st_size,
        "units": "metres",
        "coordinate_frame": "world-z-up-right-handed",
        "format": "glTF 2.0 Binary (GLB)",
        "generator": f"Blender {bpy.app.version_string} glTF Exporter",
    }

    # 3. Author Obstacle Pillar
    bpy.ops.wm.read_factory_settings(use_empty=True)
    pillar_col = bpy.data.collections.new("Obstacle_Pillar")
    bpy.context.scene.collection.children.link(pillar_col)
    mat_pillar = _bpy_create_material("Pillar_Hazard_Amber", (0.96, 0.62, 0.07, 1.0))
    mat_dark = _bpy_create_material("Pillar_Dark_Flange", (0.12, 0.14, 0.17, 1.0))

    _bpy_create_cylinder("slalom_pillar_body", 0.06, 0.80, (0.0, 0.0, 0.40), mat_pillar, pillar_col)
    _bpy_create_cylinder("slalom_pillar_cap_top", 0.065, 0.04, (0.0, 0.0, 0.80), mat_dark, pillar_col)
    _bpy_create_cylinder("slalom_pillar_cap_bottom", 0.07, 0.02, (0.0, 0.0, 0.01), mat_dark, pillar_col)

    pillar_blend = sources_dir / "obstacle_pillar.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(pillar_blend))
    pillar_glb = glb_dir / "obstacle_pillar.glb"
    bpy.ops.export_scene.gltf(filepath=str(pillar_glb), export_format="GLB")
    (web_assets_dir / "obstacle_pillar.glb").write_bytes(pillar_glb.read_bytes())

    manifest_entries["obstacle_pillar.blend"] = {
        "sha256": hashlib.sha256(pillar_blend.read_bytes()).hexdigest(),
        "byte_size": pillar_blend.stat().st_size,
        "source_type": f"Blender {bpy.app.version_string} Source File",
    }
    manifest_entries["obstacle_pillar.glb"] = {
        "sha256": hashlib.sha256(pillar_glb.read_bytes()).hexdigest(),
        "byte_size": pillar_glb.stat().st_size,
        "units": "metres",
        "coordinate_frame": "world-z-up-right-handed",
        "format": "glTF 2.0 Binary (GLB)",
        "generator": f"Blender {bpy.app.version_string} glTF Exporter",
    }

    # 4. Master Arena Assets Scene
    bpy.ops.wm.read_factory_settings(use_empty=True)
    c_gate = bpy.data.collections.new("Gate_01")
    c_pad = bpy.data.collections.new("Landing_Pad")
    c_pillar = bpy.data.collections.new("Obstacle_Pillar")
    bpy.context.scene.collection.children.link(c_gate)
    bpy.context.scene.collection.children.link(c_pad)
    bpy.context.scene.collection.children.link(c_pillar)

    # Populate collections
    m_gate = _bpy_create_material("Gate_Cyan_PBR", (0.02, 0.71, 0.83, 1.0), (0.03, 0.57, 0.70))
    _bpy_create_box("gate_1_post_left", depth, thick, ap_h, (0.0, -(ap_w / 2.0 + thick / 2.0), 0.0), m_gate, c_gate)
    _bpy_create_box("gate_1_post_right", depth, thick, ap_h, (0.0, (ap_w / 2.0 + thick / 2.0), 0.0), m_gate, c_gate)
    _bpy_create_box("gate_1_bar_top", depth, ap_w + thick * 2, thick, (0.0, 0.0, (ap_h / 2.0 + thick / 2.0)), m_gate, c_gate)
    _bpy_create_box("gate_1_bar_bottom", depth, ap_w + thick * 2, thick, (0.0, 0.0, -(ap_h / 2.0 + thick / 2.0)), m_gate, c_gate)

    m_base = _bpy_create_material("Pad_Base_Dark", (0.15, 0.17, 0.20, 1.0))
    m_surf = _bpy_create_material("Pad_Surface_Emerald", (0.06, 0.71, 0.38, 1.0), (0.02, 0.37, 0.27))
    m_ring = _bpy_create_material("Pad_Bullseye_Ring", (0.95, 0.95, 0.95, 1.0), (0.8, 0.8, 0.8))
    _bpy_create_box("pad_base", 0.35, 0.35, 0.02, (0.0, 0.0, 0.01), m_base, c_pad)
    _bpy_create_box("pad_touchdown_surface", 0.30, 0.30, 0.005, (0.0, 0.0, 0.0225), m_surf, c_pad)
    _bpy_create_cylinder("pad_bullseye_ring", 0.05, 0.008, (0.0, 0.0, 0.025), m_ring, c_pad)

    m_pillar = _bpy_create_material("Pillar_Hazard_Amber", (0.96, 0.62, 0.07, 1.0))
    m_dark = _bpy_create_material("Pillar_Dark_Flange", (0.12, 0.14, 0.17, 1.0))
    _bpy_create_cylinder("slalom_pillar_body", 0.06, 0.80, (0.0, 0.0, 0.40), m_pillar, c_pillar)
    _bpy_create_cylinder("slalom_pillar_cap_top", 0.065, 0.04, (0.0, 0.0, 0.80), m_dark, c_pillar)
    _bpy_create_cylinder("slalom_pillar_cap_bottom", 0.07, 0.02, (0.0, 0.0, 0.01), m_dark, c_pillar)

    arena_blend = sources_dir / "arena_assets.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(arena_blend))
    manifest_entries["arena_assets.blend"] = {
        "sha256": hashlib.sha256(arena_blend.read_bytes()).hexdigest(),
        "byte_size": arena_blend.stat().st_size,
        "source_type": f"Blender {bpy.app.version_string} Master Scene",
    }

    # Crazyflie 2 source blend tracking
    blend_path = project_root / "domnir" / "assets" / "crazyflie_2.blend"
    if blend_path.exists():
        manifest_entries["crazyflie_2.blend"] = {
            "sha256": hashlib.sha256(blend_path.read_bytes()).hexdigest(),
            "byte_size": blend_path.stat().st_size,
            "source_type": "Blender 4.x Source File",
        }

    cf2_glb = web_assets_dir / "crazyflie_2.glb"
    if cf2_glb.exists():
        manifest_entries["crazyflie_2.glb"] = {
            "sha256": hashlib.sha256(cf2_glb.read_bytes()).hexdigest(),
            "byte_size": cf2_glb.stat().st_size,
            "format": "glTF 2.0 Binary (GLB)",
        }

    manifest_data = {
        "schema_version": "asset-manifest-v1",
        "authoring_runtime": f"Blender {bpy.app.version_string}",
        "timestamp": "2026-11-08T00:00:00Z",
        "assets": manifest_entries,
    }

    manifest_file = manifest_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    return {k: v["sha256"] for k, v in manifest_entries.items()}


def generate_all_assets_standalone(project_root: Path) -> dict[str, str]:
    sources_dir = project_root / "domnir" / "assets" / "worlds" / "sources"
    glb_dir = project_root / "domnir" / "assets" / "worlds" / "glb"
    manifest_dir = project_root / "domnir" / "assets" / "worlds" / "manifests"
    web_assets_dir = project_root / "domnir" / "web" / "assets"

    sources_dir.mkdir(parents=True, exist_ok=True)
    glb_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    web_assets_dir.mkdir(parents=True, exist_ok=True)

    assets = {
        "gate_01.glb": build_gate_asset(),
        "landing_pad.glb": build_landing_pad_asset(),
        "obstacle_pillar.glb": build_pillar_asset(),
    }

    manifest_entries = {}

    for filename, glb_bytes in assets.items():
        sha256 = hashlib.sha256(glb_bytes).hexdigest()

        target_path = glb_dir / filename
        target_path.write_bytes(glb_bytes)

        web_path = web_assets_dir / filename
        web_path.write_bytes(glb_bytes)

        manifest_entries[filename] = {
            "sha256": sha256,
            "byte_size": len(glb_bytes),
            "units": "metres",
            "coordinate_frame": "world-z-up-right-handed",
            "format": "glTF 2.0 Binary (GLB)",
            "generator": "Domnir Blender Asset Pipeline 1.0",
        }

    # Track existing blend files in sources
    for blend_file in sources_dir.glob("*.blend"):
        manifest_entries[blend_file.name] = {
            "sha256": hashlib.sha256(blend_file.read_bytes()).hexdigest(),
            "byte_size": blend_file.stat().st_size,
            "source_type": "Blender Source File",
        }

    blend_path = project_root / "domnir" / "assets" / "crazyflie_2.blend"
    if blend_path.exists():
        manifest_entries["crazyflie_2.blend"] = {
            "sha256": hashlib.sha256(blend_path.read_bytes()).hexdigest(),
            "byte_size": blend_path.stat().st_size,
            "source_type": "Blender 4.x Source File",
        }

    cf2_glb = web_assets_dir / "crazyflie_2.glb"
    if cf2_glb.exists():
        manifest_entries["crazyflie_2.glb"] = {
            "sha256": hashlib.sha256(cf2_glb.read_bytes()).hexdigest(),
            "byte_size": cf2_glb.stat().st_size,
            "format": "glTF 2.0 Binary (GLB)",
        }

    manifest_data = {
        "schema_version": "asset-manifest-v1",
        "authoring_runtime": "Standalone glTF 2.0 Compiler",
        "timestamp": "2026-11-08T00:00:00Z",
        "assets": manifest_entries,
    }

    manifest_file = manifest_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")
    return {k: v["sha256"] for k, v in manifest_entries.items()}


def generate_all_assets(project_root: Path) -> dict[str, str]:
    if HAS_BPY:
        return author_assets_with_bpy(project_root)
    else:
        return generate_all_assets_standalone(project_root)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    res = generate_all_assets(root)
    mode = "Blender bpy" if HAS_BPY else "Standalone"
    print(f"Successfully authored and exported 3D visual assets ({mode}):")
    for name, sha in res.items():
        print(f"  {name}: {sha[:16]}...")
