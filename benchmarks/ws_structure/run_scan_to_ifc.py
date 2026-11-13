"""Infer one CRASLAB wall patch from XYZ, then evaluate frozen output on labels.

No class labels are loaded until after prediction, IR and IFC are written.
Development-set metrics are not an independent holdout scene evaluation.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from products.worldstate_bim.parametric_ir import digest
from products.worldstate_bim.scan_to_bim import export_scan_ifc, infer_visible_wall, make_scan_ir

ARCHIVE_SHA256 = "933732e81910116cec5e74c9205074b82d1f571f3d9816386b68a0a909112671"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists() and any(args.output_dir.iterdir()):
        raise FileExistsError("output directory must be empty")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    xyz_path = args.sample_dir / "xyz.npy"
    xyz = np.load(xyz_path, allow_pickle=False)
    candidate, prediction = infer_visible_wall(xyz)
    model = make_scan_ir(candidate, xyz_path, project_id="craslab-development-sample",
                         source_url="https://doi.org/10.5281/zenodo.7948116", archive_sha256=ARCHIVE_SHA256)
    (args.output_dir / "scan-ir.json").write_text(json.dumps(model, indent=2, allow_nan=False) + "\n")
    (args.output_dir / "geometry-candidate.json").write_text(json.dumps(candidate, indent=2, allow_nan=False) + "\n")
    np.save(args.output_dir / "predicted-mask.npy", prediction)
    export_scan_ifc(model, args.output_dir / "scan-wall.ifc")
    inference_seconds = time.monotonic() - start
    # Frozen candidate and IFC now exist. Semantic ground truth is only used for evaluation.
    labels_path = args.sample_dir / "labels.npy"
    labels = np.load(labels_path, allow_pickle=False)
    if labels.shape != prediction.shape:
        raise ValueError("point and ground-truth label counts differ")
    wall = labels == 3
    tp = int(np.sum(prediction & wall))
    fp = int(np.sum(prediction & ~wall))
    fn = int(np.sum(~prediction & wall))
    precision = tp / (tp+fp) if tp+fp else None
    recall = tp / (tp+fn) if tp+fn else None
    f1 = 2*precision*recall/(precision+recall) if precision and recall else None
    classes, counts = np.unique(labels[prediction], return_counts=True)
    import ifcopenshell
    import ifcopenshell.geom
    f = ifcopenshell.open(str(args.output_dir / "scan-wall.ifc"))
    walls = f.by_type("IfcWall")
    if len(walls) != 1:
        raise ValueError("expected one native IfcWall")
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), walls[0])
    vertex_count = len(shape.geometry.verts)//3
    report = {"dataset": "CRASLAB", "dataset_license": "CC-BY-4.0", "source": "https://doi.org/10.5281/zenodo.7948116",
              "archive_sha256": ARCHIVE_SHA256, "sample_xyz_sha256": digest(xyz_path), "labels_sha256": digest(labels_path),
              "mode": "automatic geometric inference; no semantic model and no human confirmation", "split": "development sample; no independent scene",
              "label_class": 3, "sample_points": len(xyz), "predicted_points": int(prediction.sum()),
              "semantic": {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1,
                           "predicted_points_by_reference_class": {str(int(k)): int(v) for k,v in zip(classes, counts)},
                           "scope": "point labels against entire sampled multi-room scene; candidate is one patch"},
              "ifc": {"schema": f.schema, "native_ifc_walls": len(walls), "wall_guid": walls[0].GlobalId,
                      "generated_mesh_vertices": vertex_count},
              "candidate_wall_geometry_m": {k: candidate[k] for k in ("start_m", "end_m", "length_m", "visible_height_m")},
              "wall_thickness_m": {"value": 0.12, "status": "ASSUMED"},
              "elapsed_seconds_including_ifc_export": inference_seconds,
              "independent_ifc_reference_geometric_error": "NOT_MEASURED: reference and scan frames require registration",
              "limitations": ["partial surface patch only", "wall classification is inferred, not confirmed",
                              "semantic labels from the same development scene; not a generalization test",
                              "wall thickness, full boundary and openings are unknown"]}
    (args.output_dir / "evaluation.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
