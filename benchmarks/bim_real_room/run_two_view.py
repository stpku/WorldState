"""Run the photo-only two-view baseline and evaluate against TUM poses/depth.

The pose is estimated solely from RGB pixels.  Ground-truth baseline length is
used *after* reconstruction as an oracle scale for depth comparison; the depth
and trajectory are not training data and do not prove IFC or wall accuracy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from products.worldstate_bim.two_view import reconstruct


def sha256(path: Path) -> str:
    """Return the SHA-256 of an input file."""
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def nearest_pose(path: Path, timestamp: float) -> tuple[np.ndarray, np.ndarray, float]:
    """Return camera-to-world rotation, position and association time error."""
    data = np.loadtxt(path, comments="#")
    row = data[np.argmin(np.abs(data[:, 0] - timestamp))]
    delta = abs(float(row[0] - timestamp))
    if delta > 0.03:
        raise ValueError(f"no ground-truth pose within 30 ms: {delta:.6f}s")
    return Rotation.from_quat(row[4:8]).as_matrix(), row[1:4], delta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image1", type=Path, required=True)
    parser.add_argument("--image2", type=Path, required=True)
    parser.add_argument("--groundtruth", type=Path, required=True)
    parser.add_argument("--depth1", type=Path, help="TUM registered depth PNG nearest to image 1")
    parser.add_argument("--output", type=Path, required=True, help="JSON metrics path")
    parser.add_argument("--cloud", type=Path, help="Optional ASCII PLY in arbitrary units")
    parser.add_argument("--tracks", type=Path, help="Optional pixel/point correspondences for same-pixel comparison")
    args = parser.parse_args()

    started = time.perf_counter()
    image1, image2 = cv2.imread(str(args.image1)), cv2.imread(str(args.image2))
    # TUM recommends the ROS default parameters for registered color/depth.
    k = np.array([[525.0, 0.0, 319.5], [0.0, 525.0, 239.5], [0.0, 0.0, 1.0]])
    result = reconstruct(image1, image2, k)
    seconds = time.perf_counter() - started
    r1, p1, dt1 = nearest_pose(args.groundtruth, float(args.image1.stem))
    r2, p2, dt2 = nearest_pose(args.groundtruth, float(args.image2.stem))
    rotation_gt = r2.T @ r1
    translation_gt = r2.T @ (p1 - p2)
    baseline = float(np.linalg.norm(translation_gt))
    if baseline < 1e-6:
        raise ValueError("ground-truth baseline is too small for directional evaluation")
    angle = lambda x: float(np.degrees(np.arccos(np.clip(x, -1.0, 1.0))))
    rotation_error = angle((np.trace(result.rotation @ rotation_gt.T) - 1.0) / 2.0)
    direction_error = angle(np.dot(result.translation, translation_gt / baseline))
    report = {
        "schema": "worldstate-bim-two-view-experiment/0.1",
        "status": "RESEARCH_ONLY_NOT_A_BIM_MODEL",
        "route": "SIFT + essential matrix + triangulation (RGB-only)",
        "inputs": [{"file": p.name, "sha256": sha256(p)} for p in (args.image1, args.image2)],
        "groundtruth_sha256": sha256(args.groundtruth),
        "pose_association_seconds": [dt1, dt2],
        "intrinsics": k.tolist(),
        "matches_after_ratio_test": result.matches,
        "triangulated_points": result.inliers,
        "median_reprojection_px": result.median_reprojection_px,
        "median_parallax_deg": result.median_parallax_deg,
        "rotation_error_deg": rotation_error,
        "translation_direction_error_deg": direction_error,
        "oracle_baseline_m": baseline,
        "translation_error_m_with_oracle_baseline": float(np.linalg.norm(result.translation * baseline - translation_gt)),
        "scale_status": "unknown_without_independent_anchor; ground truth baseline is an evaluation oracle",
        "elapsed_reconstruction_seconds": seconds,
        "environment": {"python": platform.python_version(), "opencv": cv2.__version__, "numpy": np.__version__},
        "limitations": ["two views only", "no semantic wall labels", "no IFC output", "no independent wall measurements", "no held-out-view evaluation"],
    }
    if args.depth1:
        depth = cv2.imread(str(args.depth1), cv2.IMREAD_UNCHANGED)
        if depth is None or depth.shape != image1.shape[:2] or depth.dtype != np.uint16:
            raise ValueError("depth must be a registered 16-bit TUM depth PNG")
        depth_dt = abs(float(args.depth1.stem) - float(args.image1.stem))
        if depth_dt > 0.02:
            raise ValueError(f"depth/RGB association exceeds 20 ms: {depth_dt:.6f}s")
        pixels = np.rint(result.pixels1).astype(int)
        x = np.clip(pixels[:, 0], 0, depth.shape[1] - 1)
        y = np.clip(pixels[:, 1], 0, depth.shape[0] - 1)
        observed = depth[y, x].astype(float) / 5000.0
        valid = observed > 0
        errors = np.abs(result.points[valid, 2] * baseline - observed[valid])
        report["depth_evaluation"] = {"depth_file": args.depth1.name, "sha256": sha256(args.depth1),
                                      "association_seconds": depth_dt, "valid_points": int(valid.sum()),
                                      "median_abs_error_m": float(np.median(errors)) if len(errors) else None,
                                      "mean_abs_error_m": float(np.mean(errors)) if len(errors) else None,
                                      "scale": "ground-truth trajectory baseline oracle, not independently estimated"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if args.tracks:
        tracks = {"schema": "worldstate-bim-two-view-tracks/0.1", "input_sha256": report["inputs"][0]["sha256"],
                  "points": [[float(pixel[0]), float(pixel[1]), float(point[2])]
                             for pixel, point in zip(result.pixels1, result.points)]}
        args.tracks.parent.mkdir(parents=True, exist_ok=True)
        args.tracks.write_text(json.dumps(tracks, indent=2, allow_nan=False) + "\n")
    if args.cloud:
        args.cloud.parent.mkdir(parents=True, exist_ok=True)
        with args.cloud.open("w", encoding="ascii") as out:
            out.write(f"ply\nformat ascii 1.0\ncomment arbitrary scale and first camera frame\nelement vertex {len(result.points)}\nproperty float x\nproperty float y\nproperty float z\nend_header\n")
            np.savetxt(out, result.points, fmt="%.8f")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
