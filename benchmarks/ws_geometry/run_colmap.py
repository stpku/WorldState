"""Reconstruct fixed, nested TUM RGB subsets with CPU COLMAP and assess poses."""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from products.worldstate_bim.colmap_provider import reconstruct_images


def evaluate(candidate: dict, groundtruth: Path, expected_names: list[str]) -> dict:
    """Align with two fixed anchor poses; evaluate all remaining camera poses."""
    cameras = {x["name"]: x for x in candidate["registered_cameras"]}
    metrics = {"requested_images": len(expected_names), "registered_images": len(cameras),
               "registered_fraction": len(cameras) / len(expected_names),
               "scale_status": "NOT_MEASURED", "heldout_pose_status": "NOT_MEASURED",
               "surface_completeness": "NOT_MEASURED: no independent dense surface visibility protocol"}
    first, last = expected_names[0], expected_names[-1]
    if first not in cameras or last not in cameras:
        metrics["strict_anchor_status"] = "FAILED: preselected first/last anchor not registered"
        if len(cameras) < 3:
            return metrics
        # Development-only fallback is deterministic and disclosed; never hide
        # missed frames or use this as a pre-registered final acceptance result.
        first, last = sorted(cameras)[0], sorted(cameras)[-1]
        metrics["anchor_selection"] = "first/last registered frames, diagnostic fallback"
    else:
        metrics["strict_anchor_status"] = "available"
        metrics["anchor_selection"] = "preselected first/last input frames"
    gt = np.loadtxt(groundtruth, comments="#")
    def pose(name):
        timestamp = float(Path(name).stem)
        row = gt[np.argmin(abs(gt[:, 0] - timestamp))]
        if abs(row[0] - timestamp) > 0.03:
            raise ValueError("pose association exceeds 30 ms")
        return row[1:4], Rotation.from_quat(row[4:8]).as_matrix()
    gt_first, r_gt_first = pose(first)
    gt_last, _ = pose(last)
    c0 = np.asarray(cameras[first]["center"])
    c1 = np.asarray(cameras[last]["center"])
    reconstructed_baseline = np.linalg.norm(c1-c0)
    reference_baseline = np.linalg.norm(gt_last-gt_first)
    if reconstructed_baseline < 1e-9 or reference_baseline < 1e-9:
        metrics["alignment_failure"] = "degenerate reference baseline"
        return metrics
    scale = reference_baseline / reconstructed_baseline
    r_col_camera0 = np.asarray(cameras[first]["rotation_camera_from_world"]).T
    align = r_gt_first @ r_col_camera0.T
    position_errors, rotation_errors, relative_baseline_errors = [], [], []
    for name, camera in cameras.items():
        if name in (first, last):
            continue
        p_gt, r_gt = pose(name)
        c = np.asarray(camera["center"])
        estimate = gt_first + scale * align @ (c-c0)
        r_est = align @ np.asarray(camera["rotation_camera_from_world"]).T
        position_errors.append(float(np.linalg.norm(estimate-p_gt)))
        rotation_errors.append(float(np.degrees(Rotation.from_matrix(r_est @ r_gt.T).magnitude())))
        baseline = float(np.linalg.norm(p_gt-gt_first))
        if baseline > 1e-6:
            relative_baseline_errors.append(abs(float(np.linalg.norm(estimate-gt_first))/baseline-1))
    metrics.update({"scale_status": "ORACLE_TWO_CAMERA_BASELINE_NOT_PRODUCT_SCALE",
                    "anchor_images": [first, last], "oracle_baseline_m": float(reference_baseline),
                    "oracle_scale_m_per_unit": float(scale), "heldout_pose_count": len(position_errors),
                    "heldout_pose_status": "MEASURED" if position_errors else "NOT_MEASURED",
                    "position_median_error_m": float(np.median(position_errors)) if position_errors else None,
                    "rotation_median_error_deg": float(np.median(rotation_errors)) if rotation_errors else None,
                    "heldout_baseline_relative_error_median": float(np.median(relative_baseline_errors)) if relative_baseline_errors else None})
    return metrics


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--groundtruth", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--counts", type=int, nargs="+", default=[4, 8, 16, 32])
    args = parser.parse_args()
    all_images = json.loads(args.manifest.read_text())
    if len(all_images) != 32:
        raise ValueError("manifest must define the fixed 32-image sequence")
    for item in all_images:
        name = item["name"]
        if Path(name).name != name:
            raise ValueError("manifest image names must be simple filenames")
        with (args.images / name).open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != item["sha256"]:
                raise ValueError(f"image input SHA-256 differs from manifest: {name}")
    for count in args.counts:
        if count not in (4, 8, 16, 32):
            raise ValueError("supported nested subset sizes are 4, 8, 16 and 32")
        names = [all_images[i]["name"] for i in range(0, 32, 32 // count)]
        candidate = reconstruct_images(args.images, names, args.output_dir / str(count))
        candidate["evaluation"] = evaluate(candidate, args.groundtruth, names)
        with args.groundtruth.open("rb") as stream:
            candidate["evaluation"]["trajectory_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
        path = args.output_dir / str(count) / "candidate.json"
        path.write_text(json.dumps(candidate, indent=2, allow_nan=False) + "\n")
        print(json.dumps({"images": count, "status": candidate["status"],
                          "points": candidate["sparse_points"], "evaluation": candidate["evaluation"],
                          "seconds": candidate["timing_seconds"]["total"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
