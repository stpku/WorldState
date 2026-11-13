"""Inspect an authorized GLB with Blender; no reconstruction claims are made.

Run with Blender's Python: blender -b --factory-startup --python this.py --
  --input path/to/model.glb --output /outside/repo/report.json
The audit reports aggregate mesh structure without exporting the input asset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if args.output.exists():
        raise FileExistsError("output already exists")
    with args.input.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    start = time.perf_counter()
    bpy.ops.import_scene.gltf(filepath=str(args.input))
    elapsed = time.perf_counter()-start
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise ValueError("input contains no mesh objects")
    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = [min(v[i] for v in corners) for i in range(3)]
    high = [max(v[i] for v in corners) for i in range(3)]
    report = {"schema": "worldstate-mesh-audit/0.1", "source_sha256": digest,
              "blender_version": bpy.app.version_string, "mesh_objects": len(meshes),
              "vertices": sum(len(obj.data.vertices) for obj in meshes),
              "polygons": sum(len(obj.data.polygons) for obj in meshes),
              "bounds_min_model_units": low, "bounds_max_model_units": high,
              "ifc_identified_objects": sum(any("ifc" in str(key).lower() or "globalid" in str(key).lower()
                                                for key in obj.keys()) for obj in meshes),
              "import_seconds": elapsed,
              "status": "VISUAL_MESH_ONLY_NO_METRIC_OR_BIM_SEMANTICS_ESTABLISHED"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
