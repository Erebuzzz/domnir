"""Vendor Three.js and addons into domnir/web/vendor."""

import shutil
from pathlib import Path

src_base = Path("D:/confluxa/node_modules/three")
dst_base = Path("d:/domnir/domnir/web/vendor")

addons_dir = dst_base / "addons"
(addons_dir / "loaders").mkdir(parents=True, exist_ok=True)
(addons_dir / "controls").mkdir(parents=True, exist_ok=True)
(addons_dir / "utils").mkdir(parents=True, exist_ok=True)

files = [
    (src_base / "build" / "three.module.js", dst_base / "three.module.js"),
    (src_base / "build" / "three.core.js", dst_base / "three.core.js"),
    (src_base / "examples" / "jsm" / "loaders" / "GLTFLoader.js", addons_dir / "loaders" / "GLTFLoader.js"),
    (src_base / "examples" / "jsm" / "controls" / "OrbitControls.js", addons_dir / "controls" / "OrbitControls.js"),
    (src_base / "examples" / "jsm" / "utils" / "BufferGeometryUtils.js", addons_dir / "utils" / "BufferGeometryUtils.js"),
    (src_base / "examples" / "jsm" / "utils" / "SkeletonUtils.js", addons_dir / "utils" / "SkeletonUtils.js"),
]

for src, dst in files:
    shutil.copy2(src, dst)
    print(f"Copied {src.name} -> {dst.relative_to(dst_base.parent)}")
