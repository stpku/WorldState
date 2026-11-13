"""Fit a manually marked real RGB-D wall-surface candidate, not an IFC wall."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from products.worldstate_bim.visible_surface import fit_visible_surface


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--depth", type=Path, required=True)
    parser.add_argument("--roi", type=int, nargs=4, metavar=("XMIN", "YMIN", "XMAX", "YMAX"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    image = cv2.imread(str(args.image))
    depth = cv2.imread(str(args.depth), cv2.IMREAD_UNCHANGED)
    if image is None or depth is None or image.shape[:2] != depth.shape:
        raise ValueError("registered RGB and depth frames must be readable and have the same shape")
    association = abs(float(args.image.stem) - float(args.depth.stem))
    if association > 0.02:
        raise ValueError("TUM frame association exceeds 20 ms")
    h, w = depth.shape
    x0, y0, x1, y1 = args.roi
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h):
        raise ValueError("ROI must be a non-empty rectangle inside the image")
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    k = np.array([[525., 0., 319.5], [0., 525., 239.5], [0., 0., 1.]])
    result = fit_visible_surface(depth, mask, k)
    report = {
        "schema": "worldstate-bim-visible-surface/0.1", "status": "UNVERIFIED_VISIBLE_SURFACE_CANDIDATE",
        "semantic_label": {"value": "possible_wall", "basis": "manual_image_region_label_not_an_observation"},
        "image": {"file": args.image.name, "sha256": sha256(args.image)},
        "depth": {"file": args.depth.name, "sha256": sha256(args.depth), "unit_factor": 5000},
        "association_seconds": association, "roi_xyxy": args.roi, "intrinsics": k.tolist(),
        "geometry": {"frame": "color-camera", "basis": "inferred_from_metric_depth_samples",
                     "normal_camera": result.normal_camera.tolist(), "plane_offset_m": result.offset_m,
                     "centroid_camera_m": result.centroid_camera_m.tolist(),
                     "visible_sample_span_m": result.visible_span_m.tolist(),
                     "valid_depth_samples": result.valid_depth_samples, "inlier_samples": result.inlier_samples,
                     "median_residual_m": result.median_residual_m},
        "unknown": ["complete wall boundary", "wall height", "wall thickness", "building coordinates", "ground-truth wall dimensions", "independent plane accuracy"],
        "limitations": ["manually selected region", "single RGB-D frame", "RANSAC residual is not independent accuracy", "no IFC wall or editable solid generated"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
