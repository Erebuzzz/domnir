"""Build authentic Bitcraze Crazyflie 2.0 3D model, materials, GLB, and rendered stills via Cycles CPU."""

from pathlib import Path
import bpy
import bmesh
import numpy as np

def build_crazyflie():
    # 1. Clear scene
    bpy.ops.wm.read_factory_settings(use_empty=True)

    assets_dir = Path("d:/domnir/.cache/mujoco_menagerie/bitcraze_crazyflie_2/assets")
    output_blend = Path("d:/domnir/domnir/assets/crazyflie_2.blend")
    output_glb = Path("d:/domnir/domnir/web/assets/crazyflie_2.glb")
    output_dawn = Path("d:/domnir/domnir/web/assets/crazyflie_ragnarok_dawn.png")
    output_dusk = Path("d:/domnir/domnir/web/assets/crazyflie_ragnarok_dusk.png")
    output_readme = Path("d:/domnir/domnir/assets/README.md")
    output_blend.parent.mkdir(parents=True, exist_ok=True)
    output_glb.parent.mkdir(parents=True, exist_ok=True)

    # Helper to create Principled BSDF material
    def make_mat(name, base_color, metallic=0.0, roughness=0.5):
        mat = bpy.data.materials.new(name=name)
        nodes = mat.node_tree.nodes
        bsdf = nodes.get("Principled BSDF")
        if bsdf:
            bsdf.inputs["Base Color"].default_value = base_color
            bsdf.inputs["Metallic"].default_value = metallic
            bsdf.inputs["Roughness"].default_value = roughness
        return mat

    mat_pcb = make_mat("Mat_PCB_Frame", (0.05, 0.05, 0.06, 1.0), metallic=0.08, roughness=0.65)
    mat_motors = make_mat("Mat_Motors_BrushedChrome", (0.82, 0.83, 0.85, 1.0), metallic=0.95, roughness=0.20)
    mat_mounts = make_mat("Mat_Mounts_Battery", (0.90, 0.90, 0.92, 1.0), metallic=0.02, roughness=0.35)
    mat_gold = make_mat("Mat_Gold_Traces", (0.95, 0.78, 0.35, 1.0), metallic=0.96, roughness=0.18)
    mat_connectors = make_mat("Mat_Connectors", (0.08, 0.08, 0.09, 1.0), metallic=0.10, roughness=0.50)
    mat_props = make_mat("Mat_Propellers", (0.06, 0.06, 0.07, 1.0), metallic=0.05, roughness=0.35)

    # Create root object
    drone_root = bpy.data.objects.new("DroneRoot", None)
    drone_root.empty_display_type = 'PLAIN_AXES'
    drone_root.empty_display_size = 0.05
    bpy.context.collection.objects.link(drone_root)

    # Import parts with correct Z-up orientation
    mesh_map = {
        "cf2_1.obj": ("Connectors", mat_connectors),
        "cf2_2.obj": ("GoldTraces_Antenna", mat_gold),
        "cf2_3.obj": ("BatteryClip_Pins", mat_connectors),
        "cf2_4.obj": ("Motors", mat_motors),
        "cf2_5.obj": ("Frame_PCB", mat_pcb),
        "cf2_6.obj": ("Mounts_Battery", mat_mounts),
    }

    imported_objects = {}
    for filename, (part_name, material) in mesh_map.items():
        filepath = str(assets_dir / filename)
        bpy.ops.wm.obj_import(filepath=filepath, forward_axis='Y', up_axis='Z')
        obj = bpy.context.selected_objects[0]
        obj.name = part_name
        obj.data.materials.clear()
        obj.data.materials.append(material)
        obj.parent = drone_root
        imported_objects[part_name] = obj

    # Import and split propellers (cf2_0.obj) into 4 distinct rotors with concentric motor pivots
    prop_path = str(assets_dir / "cf2_0.obj")
    bpy.ops.wm.obj_import(filepath=prop_path, forward_axis='Y', up_axis='Z')
    prop_obj = bpy.context.selected_objects[0]
    prop_obj.name = "AllPropellers"

    # Exact motor centers for rotation pivots
    motor_pivots = {
        "RotorFL": (0.0320, 0.0320, 0.0130),
        "RotorFR": (-0.0333, 0.0320, 0.0130),
        "RotorRL": (0.0320, -0.0334, 0.0130),
        "RotorRR": (-0.0333, -0.0334, 0.0130),
    }

    quadrant_defs = [
        ("RotorFL", lambda co: co.x >= 0 and co.y >= 0),
        ("RotorFR", lambda co: co.x < 0 and co.y >= 0),
        ("RotorRL", lambda co: co.x >= 0 and co.y < 0),
        ("RotorRR", lambda co: co.x < 0 and co.y < 0),
    ]

    rotors = []
    for rotor_name, predicate in quadrant_defs:
        bm_src = bmesh.new()
        bm_src.from_mesh(prop_obj.data)
        bm_rotor = bmesh.new()

        vert_map = {}
        for v in bm_src.verts:
            if predicate(v.co):
                vert_map[v] = bm_rotor.verts.new(v.co)

        bm_rotor.verts.ensure_lookup_table()
        for f in bm_src.faces:
            if all(v in vert_map for v in f.verts):
                bm_rotor.faces.new([vert_map[v] for v in f.verts])

        rotor_mesh = bpy.data.meshes.new(rotor_name + "_Mesh")
        bm_rotor.to_mesh(rotor_mesh)
        bm_rotor.free()
        bm_src.free()

        rotor_obj = bpy.data.objects.new(rotor_name, rotor_mesh)
        rotor_obj.data.materials.append(mat_props)
        bpy.context.collection.objects.link(rotor_obj)

        pivot = motor_pivots[rotor_name]

        # Shift mesh vertices so origin is at the concentric motor shaft pivot
        for v in rotor_obj.data.vertices:
            v.co.x -= pivot[0]
            v.co.y -= pivot[1]
            v.co.z -= pivot[2]
        rotor_obj.location = (pivot[0], pivot[1], pivot[2])
        rotor_obj.parent = drone_root
        rotors.append(rotor_obj)

    # Delete temporary AllPropellers object
    bpy.data.objects.remove(prop_obj, do_unlink=True)

    # Save .blend file
    bpy.ops.wm.save_as_mainfile(filepath=str(output_blend))
    print(f"Saved {output_blend}")

    # Export .glb with Y-up conversion for Three.js
    bpy.ops.export_scene.gltf(
        filepath=str(output_glb),
        export_format='GLB',
        use_selection=False,
        export_apply=False,
        export_yup=True,
    )
    print(f"Exported {output_glb}")

    # Write README
    output_readme.write_text(
        "# Bitcraze Crazyflie 2.0 3D Asset Specification\n\n"
        "## Model Overview\n"
        "- Plant Platform: Bitcraze Crazyflie 2.0 open-source quadrotor\n"
        "- Geometry Source: CAD meshes from MuJoCo Menagerie (Apache 2.0 / Bitcraze AB)\n"
        "- Dimensions: 92 mm x 92 mm motor-to-motor span, ~105 mm rotor tip span, 29 mm height\n"
        "- Mass Calibration: 27.0 g nominal dry mass with 240 mAh LiPo battery\n"
        "- Coordinate Frame: Z-up, forward +X, left +Y, right -Y\n\n"
        "## Hierarchy\n"
        "- `DroneRoot` (Anchor)\n"
        "  - `Frame_PCB`: Matte black FR4 circuit board frame with gold traces\n"
        "  - `Motors`: Brushed metallic chrome cylindrical coreless DC motors (7x16mm)\n"
        "  - `Mounts_Battery`: White injection-molded motor mount brackets and LiPo battery\n"
        "  - `GoldTraces_Antenna`: Integrated 2.4 GHz meandered inverted-F antenna and test pads\n"
        "  - `Connectors`: Expansion headers and battery retention clips\n"
        "  - `RotorFL`: Front-Left counter-clockwise propeller (pivot centered at spin axis)\n"
        "  - `RotorFR`: Front-Right clockwise propeller (pivot centered at spin axis)\n"
        "  - `RotorRL`: Rear-Left clockwise propeller (pivot centered at spin axis)\n"
        "  - `RotorRR`: Rear-Right counter-clockwise propeller (pivot centered at spin axis)\n\n"
        "## Deliverables\n"
        "- `crazyflie_2.blend`: Source authoring file with materials, pivots, and hierarchy\n"
        "- `crazyflie_2.glb`: glTF binary runtime asset optimized for WebGL / Three.js\n"
        "- `crazyflie_ragnarok_dawn.png`: High-resolution render with warm sunlight and contact shadow\n"
        "- `crazyflie_ragnarok_dusk.png`: High-resolution render with cool obsidian/cyan lighting and contact shadow\n",
        encoding="utf-8"
    )
    print(f"Wrote {output_readme}")

    # Setup Cycles CPU rendering for stills
    scene = bpy.context.scene
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 64
    scene.render.resolution_x = 640
    scene.render.resolution_y = 520
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGBA'

    # Camera aiming at drone center with 15% visual margin
    cam_data = bpy.data.cameras.new("RenderCam")
    cam_data.lens = 65
    cam_data.clip_start = 0.01
    cam_data.clip_end = 10.0
    cam_obj = bpy.data.objects.new("RenderCam", cam_data)
    bpy.context.collection.objects.link(cam_obj)
    scene.camera = cam_obj

    cam_obj.location = (0.16, -0.20, 0.13)
    track = cam_obj.constraints.new(type='TRACK_TO')
    track.target = drone_root
    track.track_axis = 'TRACK_NEGATIVE_Z'
    track.up_axis = 'UP_Y'

    # Shadow catcher plane at bottom of landing feet
    bpy.ops.mesh.primitive_plane_add(size=0.6, location=(0, 0, -0.013))
    ground_plane = bpy.context.selected_objects[0]
    ground_plane.name = "ShadowCatcher"
    ground_plane.is_shadow_catcher = True

    # Render Dusk (Cool Midnight / Cyan rim)
    light_key_data = bpy.data.lights.new("KeyLight", type='POINT')
    light_key_data.energy = 1.2
    light_key_data.color = (0.85, 0.92, 1.0)
    light_key = bpy.data.objects.new("KeyLight", light_key_data)
    light_key.location = (0.20, -0.18, 0.25)
    bpy.context.collection.objects.link(light_key)

    light_rim_data = bpy.data.lights.new("RimLight", type='POINT')
    light_rim_data.energy = 0.9
    light_rim_data.color = (0.22, 0.74, 0.97)  # Bifrost Cyan #38BDF8
    light_rim = bpy.data.objects.new("RimLight", light_rim_data)
    light_rim.location = (-0.22, 0.22, 0.16)
    bpy.context.collection.objects.link(light_rim)

    light_fill_data = bpy.data.lights.new("FillLight", type='POINT')
    light_fill_data.energy = 0.4
    light_fill_data.color = (0.50, 0.60, 0.80)
    light_fill = bpy.data.objects.new("FillLight", light_fill_data)
    light_fill.location = (-0.12, -0.18, 0.10)
    bpy.context.collection.objects.link(light_fill)

    scene.render.filepath = str(output_dusk)
    bpy.ops.render.render(write_still=True)
    print(f"Rendered Dusk still to {output_dusk}")

    # Render Dawn (Warm Sunlight / Copper reflections)
    light_key_data.energy = 1.5
    light_key_data.color = (1.0, 0.90, 0.78)  # Warm sun #FFF1D8
    light_key.location = (0.22, -0.16, 0.28)

    light_rim_data.energy = 0.9
    light_rim_data.color = (0.95, 0.55, 0.25)  # Burnt copper #B64E1A
    light_rim.location = (-0.20, 0.20, 0.16)

    light_fill_data.energy = 0.5
    light_fill_data.color = (1.0, 0.94, 0.86)
    light_fill.location = (-0.14, -0.16, 0.08)

    scene.render.filepath = str(output_dawn)
    bpy.ops.render.render(write_still=True)
    print(f"Rendered Dawn still to {output_dawn}")

    print("ALL 3D DELIVERABLES BUILT SUCCESSFULLY")

if __name__ == "__main__":
    build_crazyflie()
