"""Evaluate IFC wall surface proximity on separately loaded labelled XYZ.

The IFC and all model decisions must be frozen before this evaluation. Points
within threshold of any triangulated IFC wall surface are predicted as wall.
This is a development-scene point-proximity proxy, not BIM instance accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate
import numpy as np
import open3d as o3d


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ifc", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--threshold-m", type=float, default=.04)
    args = parser.parse_args()
    if args.output.exists() or not np.isfinite(args.threshold_m) or args.threshold_m <= 0:
        raise ValueError("output must not exist and threshold must be positive")
    ifc_sha = digest(args.ifc)
    f = ifcopenshell.open(str(args.ifc))
    walls = f.by_type("IfcWall")
    if not walls:
        raise ValueError("IFC contains no walls")
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    scene = o3d.t.geometry.RaycastingScene(nthreads=4)
    failed = []
    for wall in walls:
        try:
            shape = ifcopenshell.geom.create_shape(settings, wall)
            vertices = np.asarray(shape.geometry.verts, dtype=np.float32).reshape(-1, 3)
            triangles = np.asarray(shape.geometry.faces, dtype=np.uint32).reshape(-1, 3)
            scene.add_triangles(o3d.core.Tensor(vertices), o3d.core.Tensor(triangles))
        except Exception as exc:
            failed.append({"guid": wall.GlobalId, "error": type(exc).__name__})
    if failed:
        raise ValueError(f"cannot evaluate incomplete IFC geometry: {failed}")
    xyz = np.load(args.points, allow_pickle=False)
    if xyz.ndim != 2 or xyz.shape[1] != 3 or not np.isfinite(xyz).all():
        raise ValueError("points must be finite XYZ")
    start = time.monotonic()
    distances = scene.compute_distance(o3d.core.Tensor(xyz.astype(np.float32)), nthreads=4).numpy()
    prediction = distances <= args.threshold_m
    # The model and point-proximity predictions are fixed before opening GT.
    labels = np.load(args.labels, allow_pickle=False)
    if labels.shape != prediction.shape:
        raise ValueError("semantic reference point count differs")
    truth = labels == 3
    tp, fp, fn = int(np.sum(prediction & truth)), int(np.sum(prediction & ~truth)), int(np.sum(~prediction & truth))
    precision, recall = (tp/(tp+fp) if tp+fp else 0.), (tp/(tp+fn) if tp+fn else 0.)
    classes, counts = np.unique(labels[prediction], return_counts=True)
    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, logger)
    problems: dict[str, int] = {}
    for issue in logger.statements:
        key = str(issue.get("attribute", issue.get("message", "unknown")))
        problems[key] = problems.get(key, 0) + 1
    counts_ifc = {name: len(f.by_type(name)) for name in (
        "IfcWall", "IfcSlab", "IfcOpeningElement", "IfcWindow", "IfcDoor", "IfcSpace", "IfcRelVoidsElement", "IfcRelFillsElement")}
    report = {"dataset": "CRASLAB development sample, CC-BY-4.0", "ifc_sha256": ifc_sha,
              "points_sha256": digest(args.points), "labels_sha256": digest(args.labels),
              "evaluation": "point distance to nearest world-space IfcWall triangle; reference class 3 = wall",
              "threshold_m": args.threshold_m, "predicted_points": int(prediction.sum()),
              "tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall,
              "f1": 2*precision*recall/(precision+recall) if precision+recall else 0.,
              "predicted_points_by_reference_class": {str(int(k)): int(v) for k,v in zip(classes, counts)},
              "ifc_schema": f.schema, "entity_counts": counts_ifc, "wall_geometry_success": len(walls)-len(failed),
              "wall_geometry_failure": len(failed), "schema_validation_issues": problems,
              "evaluation_seconds": time.monotonic()-start,
              "limitations": ["same development scene; not an independent scene test",
                  "point proximity is not object instance matching or independent dimensional error",
                  "output uses modelled material, thickness and site metadata assumptions"]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps(report, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
