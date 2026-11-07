import hashlib
import json
from pathlib import Path
import struct
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = PROJECT_ROOT / "domnir" / "assets"
WORLDS_DIR = ASSETS_DIR / "worlds"
MANIFEST_FILE = WORLDS_DIR / "manifests" / "manifest.json"
WEB_ASSETS_DIR = PROJECT_ROOT / "domnir" / "web" / "assets"


def test_manifest_structure_and_schema():
    assert MANIFEST_FILE.exists(), f"Missing manifest file at {MANIFEST_FILE}"
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    assert manifest.get("schema_version") == "asset-manifest-v1"
    assert "assets" in manifest
    assert len(manifest["assets"]) >= 8


def test_manifest_asset_hashes_and_integrity():
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    assets = manifest["assets"]

    expected_assets = [
        "gate_01.blend",
        "gate_01.glb",
        "landing_pad.blend",
        "landing_pad.glb",
        "obstacle_pillar.blend",
        "obstacle_pillar.glb",
        "arena_assets.blend",
        "crazyflie_2.blend",
        "crazyflie_2.glb",
    ]

    for name in expected_assets:
        assert name in assets, f"Asset {name} missing from manifest"
        entry = assets[name]

        # Locate file on disk
        if name.endswith(".blend"):
            if name == "crazyflie_2.blend":
                disk_path = ASSETS_DIR / name
            else:
                disk_path = WORLDS_DIR / "sources" / name
        elif name.endswith(".glb"):
            if name == "crazyflie_2.glb":
                disk_path = WEB_ASSETS_DIR / name
            else:
                disk_path = WORLDS_DIR / "glb" / name
        else:
            pytest.fail(f"Unexpected asset extension: {name}")

        assert disk_path.exists(), f"File {name} not found on disk at {disk_path}"
        data = disk_path.read_bytes()

        # Verify byte size
        assert len(data) == entry["byte_size"], f"Size mismatch for {name}: {len(data)} != {entry['byte_size']}"

        # Verify SHA-256 hash
        computed_hash = hashlib.sha256(data).hexdigest()
        assert computed_hash == entry["sha256"], f"Hash mismatch for {name}: {computed_hash} != {entry['sha256']}"


def test_gltf_binary_headers():
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    glb_assets = [k for k in manifest["assets"].keys() if k.endswith(".glb")]

    for glb_name in glb_assets:
        if glb_name == "crazyflie_2.glb":
            path = WEB_ASSETS_DIR / glb_name
        else:
            path = WORLDS_DIR / "glb" / glb_name

        data = path.read_bytes()
        assert len(data) >= 12, f"GLB file {glb_name} too short"

        magic, version, length = struct.unpack("<4sII", data[:12])
        assert magic == b"glTF", f"GLB {glb_name} missing glTF magic header: {magic}"
        assert version == 2, f"GLB {glb_name} unsupported version: {version}"
        assert length == len(data), f"GLB {glb_name} header length {length} != file size {len(data)}"


def test_blend_source_headers():
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    blend_assets = [k for k in manifest["assets"].keys() if k.endswith(".blend")]

    for blend_name in blend_assets:
        if blend_name == "crazyflie_2.blend":
            path = ASSETS_DIR / blend_name
        else:
            path = WORLDS_DIR / "sources" / blend_name

        data = path.read_bytes()
        assert len(data) >= 12, f"Blend file {blend_name} too short"
        magic = data[:4]
        # Modern Blender files start with either uncompressed b"BLEN" or Zstd compressed 0x28 0xB5 0x2F 0xFD
        assert magic in (b"BLEN", b"\x28\xb5\x2f\xfd"), f"Blend file {blend_name} missing Blender/Zstd magic: {magic}"


def test_web_mirror_parity():
    for name in ["gate_01.glb", "landing_pad.glb", "obstacle_pillar.glb"]:
        world_copy = WORLDS_DIR / "glb" / name
        web_copy = WEB_ASSETS_DIR / name

        assert world_copy.exists(), f"Worlds asset {name} missing"
        assert web_copy.exists(), f"Web asset {name} missing"
        assert world_copy.read_bytes() == web_copy.read_bytes(), f"Web asset {name} differs from worlds copy"
