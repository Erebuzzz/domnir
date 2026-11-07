"""Validated MJCF compiler translating WorldSpec into native MuJoCo simulation scenes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from .schema import EntityKind, WorldSpec


class WorldCompilerError(ValueError):
    """Raised when world specification cannot be compiled into valid physics geometry."""


class MJCFWorldCompiler:
    @staticmethod
    def compile(base_cf2_xml: str | Path, world: WorldSpec) -> str:
        """Inject world physical collision geometry into Crazyflie MJCF model XML."""
        if isinstance(base_cf2_xml, Path):
            with open(base_cf2_xml, "r", encoding="utf-8") as f:
                raw_xml = f.read()
        else:
            raw_xml = str(base_cf2_xml)

        try:
            root = ET.fromstring(raw_xml)
        except ET.ParseError as err:
            raise WorldCompilerError(f"Failed to parse base model XML: {err}") from err

        worldbody = root.find("worldbody")
        if worldbody is None:
            raise WorldCompilerError("Base model XML is missing <worldbody> tag")

        # Resolve meshdir to absolute path if needed
        compiler_elem = root.find("compiler")
        if compiler_elem is not None and "meshdir" in compiler_elem.attrib:
            if isinstance(base_cf2_xml, Path):
                meshdir_val = compiler_elem.attrib["meshdir"]
                if not Path(meshdir_val).is_absolute():
                    abs_meshdir = (base_cf2_xml.parent / meshdir_val).resolve()
                    compiler_elem.attrib["meshdir"] = str(abs_meshdir).replace("\\", "/")

        # Compile each entity into native MuJoCo elements
        for ent in world.entities:
            p = ent.pose.position_m
            dims = ent.dimensions_m

            if ent.kind == EntityKind.BOX_OBSTACLE or ent.kind == EntityKind.WALL:
                half_x = max(0.01, dims[0] / 2.0)
                half_y = max(0.01, (dims[1] if len(dims) > 1 else dims[0]) / 2.0)
                half_z = max(0.01, (dims[2] if len(dims) > 2 else dims[0]) / 2.0)
                rgba = "0.7 0.25 0.25 1" if ent.kind == EntityKind.BOX_OBSTACLE else "0.4 0.4 0.5 1"

                geom = ET.SubElement(worldbody, "geom")
                geom.set("name", f"obstacle_{ent.id}")
                geom.set("type", "box")
                geom.set("size", f"{half_x:.4f} {half_y:.4f} {half_z:.4f}")
                geom.set("pos", f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")
                geom.set("rgba", rgba)
                geom.set("contype", "1")
                geom.set("conaffinity", "1")

            elif ent.kind == EntityKind.CYLINDER_OBSTACLE:
                radius = max(0.01, dims[0] / 2.0)
                half_len = max(0.01, (dims[1] if len(dims) > 1 else 1.0) / 2.0)

                geom = ET.SubElement(worldbody, "geom")
                geom.set("name", f"obstacle_{ent.id}")
                geom.set("type", "cylinder")
                geom.set("size", f"{radius:.4f} {half_len:.4f}")
                geom.set("pos", f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")
                geom.set("rgba", "0.8 0.4 0.2 1")
                geom.set("contype", "1")
                geom.set("conaffinity", "1")

            elif ent.kind == EntityKind.LANDING_PAD:
                half_x = max(0.02, dims[0] / 2.0)
                half_y = max(0.02, (dims[1] if len(dims) > 1 else dims[0]) / 2.0)
                half_z = max(0.005, (dims[2] if len(dims) > 2 else 0.04) / 2.0)

                geom = ET.SubElement(worldbody, "geom")
                geom.set("name", f"landingpad_{ent.id}")
                geom.set("type", "box")
                geom.set("size", f"{half_x:.4f} {half_y:.4f} {half_z:.4f}")
                geom.set("pos", f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")
                geom.set("rgba", "0.1 0.75 0.45 1")
                geom.set("friction", "1.5 0.1 0.1")
                geom.set("contype", "1")
                geom.set("conaffinity", "1")

            elif ent.kind == EntityKind.GATE:
                # Gate with a true physical aperture: 4 bounding bars leaving center open
                aperture = ent.aperture_m or [0.40, 0.40]
                ap_w = max(0.10, aperture[0])
                ap_h = max(0.10, aperture[1])
                fw = max(0.02, ent.frame_width_m)
                th = max(0.02, dims[2] if len(dims) > 2 else fw)

                # Gate body container
                gate_body = ET.SubElement(worldbody, "body")
                gate_body.set("name", f"gate_{ent.id}")
                gate_body.set("pos", f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}")

                # Left post
                g_left = ET.SubElement(gate_body, "geom")
                g_left.set("name", f"gate_{ent.id}_post_left")
                g_left.set("type", "box")
                g_left.set("size", f"{th/2:.4f} {fw/2:.4f} {(ap_h + 2*fw)/2:.4f}")
                g_left.set("pos", f"0.0000 {-(ap_w + fw)/2:.4f} 0.0000")
                g_left.set("rgba", "0.2 0.6 0.9 1")

                # Right post
                g_right = ET.SubElement(gate_body, "geom")
                g_right.set("name", f"gate_{ent.id}_post_right")
                g_right.set("type", "box")
                g_right.set("size", f"{th/2:.4f} {fw/2:.4f} {(ap_h + 2*fw)/2:.4f}")
                g_right.set("pos", f"0.0000 {(ap_w + fw)/2:.4f} 0.0000")
                g_right.set("rgba", "0.2 0.6 0.9 1")

                # Top bar
                g_top = ET.SubElement(gate_body, "geom")
                g_top.set("name", f"gate_{ent.id}_bar_top")
                g_top.set("type", "box")
                g_top.set("size", f"{th/2:.4f} {ap_w/2:.4f} {fw/2:.4f}")
                g_top.set("pos", f"0.0000 0.0000 {(ap_h + fw)/2:.4f}")
                g_top.set("rgba", "0.2 0.6 0.9 1")

                # Bottom bar
                g_bottom = ET.SubElement(gate_body, "geom")
                g_bottom.set("name", f"gate_{ent.id}_bar_bottom")
                g_bottom.set("type", "box")
                g_bottom.set("size", f"{th/2:.4f} {ap_w/2:.4f} {fw/2:.4f}")
                g_bottom.set("pos", f"0.0000 0.0000 {-(ap_h + fw)/2:.4f}")
                g_bottom.set("rgba", "0.2 0.6 0.9 1")

        return ET.tostring(root, encoding="unicode")
