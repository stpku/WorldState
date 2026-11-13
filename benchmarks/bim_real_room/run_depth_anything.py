"""CPU-only Depth Anything V2 Small relative-depth research benchmark.

The ONNX model is an external, pinned community conversion. The network gives
relative inverse depth, not metric measurements, camera poses, or BIM objects.
When depth is supplied, a checkerboard of *the same image's* sensor pixels is
used as an oracle to fit scale/shift; the held-out pixels are only a local
diagnostic, not an independent scene-level or user-workflow benchmark.
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
import onnxruntime as ort


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--depth", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prediction", type=Path, help="Optional relative-depth numpy output")
    parser.add_argument("--tracks", type=Path, help="Two-view tracks for matching held-out depth pixels")
    parser.add_argument("--two-view-report", type=Path, help="Two-view report supplying oracle baseline")
    args = parser.parse_args()
    if bool(args.tracks) != bool(args.two_view_report) or (args.tracks and not args.depth):
        parser.error("--tracks and --two-view-report must be supplied together with --depth")
    image = cv2.imread(str(args.image), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("image cannot be read")
    h, w = image.shape[:2]
    # DPT processor: resize the shorter side to 518, preserve aspect ratio,
    # round both dimensions to multiples of the ViT patch size (14).
    scale = 518 / min(h, w)
    target_w = max(14, round(w * scale / 14) * 14)
    target_h = max(14, round(h * scale / 14) * 14)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    rgb = cv2.resize(rgb, (target_w, target_h), interpolation=cv2.INTER_CUBIC).astype(np.float32) / 255.0
    rgb = (rgb - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array([0.229, 0.224, 0.225], dtype=np.float32)
    tensor = np.transpose(rgb, (2, 0, 1))[None]
    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    started = time.perf_counter()
    session = ort.InferenceSession(str(args.model), sess_options=options, providers=["CPUExecutionProvider"])
    init_seconds = time.perf_counter() - started
    started = time.perf_counter()
    raw = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
    inference_seconds = time.perf_counter() - started
    prediction = cv2.resize(raw, (w, h), interpolation=cv2.INTER_CUBIC)
    if not np.isfinite(prediction).all():
        raise ValueError("model returned non-finite predictions")
    report = {
        "schema": "worldstate-bim-relative-depth-experiment/0.1",
        "status": "RESEARCH_ONLY_NOT_A_BIM_MODEL",
        "route": "Depth Anything V2 Small ONNX, monocular relative inverse depth",
        "input": {"file": args.image.name, "sha256": sha256(args.image)},
        "model_sha256": sha256(args.model),
        "model_revision": "4472b7362082ad9968fee890ca0f1e5aca36b93d",
        "input_dimensions": [w, h], "inference_dimensions": [target_w, target_h],
        "relative_prediction_range": [float(np.min(prediction)), float(np.max(prediction))],
        "initialization_seconds": init_seconds, "inference_seconds": inference_seconds,
        "environment": {"python": platform.python_version(), "onnxruntime": ort.__version__,
                        "opencv": cv2.__version__, "provider": session.get_providers()[0]},
        "limitations": ["relative depth only", "no camera pose", "no multi-view consistency", "no building semantics", "no IFC output", "pretraining overlap with this scene unknown"],
    }
    if args.depth:
        depth = cv2.imread(str(args.depth), cv2.IMREAD_UNCHANGED)
        if depth is None or depth.dtype != np.uint16 or depth.shape != (h, w):
            raise ValueError("depth must be a registered 16-bit TUM depth PNG")
        delta = abs(float(args.depth.stem) - float(args.image.stem))
        if delta > 0.02:
            raise ValueError(f"depth/RGB association exceeds 20 ms: {delta:.6f}s")
        depth_m = depth.astype(np.float64) / 5000.0
        rows, cols = np.indices((h, w))
        observed = depth_m > 0
        calibrate = observed & (((rows // 16 + cols // 16) % 2) == 0)
        evaluate = observed & ~calibrate
        if calibrate.sum() < 100 or evaluate.sum() < 100:
            raise ValueError("too few observed depth pixels for local evaluation")
        design = np.column_stack((prediction[calibrate], np.ones(calibrate.sum())))
        a, b = np.linalg.lstsq(design, 1.0 / depth_m[calibrate], rcond=None)[0]
        estimated_inverse = a * prediction + b
        valid = evaluate & np.isfinite(estimated_inverse) & (estimated_inverse > 0)
        estimate_m = 1.0 / estimated_inverse[valid]
        actual_m = depth_m[valid]
        errors = np.abs(estimate_m - actual_m)
        report["depth_evaluation"] = {
            "depth_file": args.depth.name, "sha256": sha256(args.depth), "association_seconds": delta,
            "calibration": "same-frame alternating 16x16 tiles fitted to inverse metric depth",
            "calibration_pixels": int(calibrate.sum()), "held_out_valid_sensor_pixels": int(evaluate.sum()),
            "held_out_valid_prediction_pixels": int(valid.sum()),
            "held_out_positive_prediction_fraction": float(valid.sum() / evaluate.sum()),
            "median_abs_error_m": float(np.median(errors)) if len(errors) else None,
            "mean_abs_error_m": float(np.mean(errors)) if len(errors) else None,
            "mean_absolute_relative_error": float(np.mean(errors / actual_m)) if len(errors) else None,
            "fitted_inverse_depth_scale": float(a), "fitted_inverse_depth_shift": float(b),
        }
        if args.tracks:
            tracks = json.loads(args.tracks.read_text())
            two_view = json.loads(args.two_view_report.read_text())
            if (tracks.get("schema") != "worldstate-bim-two-view-tracks/0.1" or
                    tracks.get("input_sha256") != report["input"]["sha256"] or
                    two_view["inputs"][0]["sha256"] != report["input"]["sha256"]):
                raise ValueError("two-view tracks/report do not match this image")
            baseline = float(two_view["oracle_baseline_m"])
            if not np.isfinite(baseline) or baseline <= 0:
                raise ValueError("two-view oracle baseline must be finite and positive")
            points = np.asarray(tracks["points"], dtype=float)
            if points.ndim != 2 or points.shape[1] != 3 or not np.isfinite(points).all():
                raise ValueError("invalid two-view tracks")
            x = np.clip(np.rint(points[:, 0]).astype(int), 0, w - 1)
            y = np.clip(np.rint(points[:, 1]).astype(int), 0, h - 1)
            common = valid[y, x] & (points[:, 2] > 0)
            reference = depth_m[y[common], x[common]]
            model_error = np.abs(1 / estimated_inverse[y[common], x[common]] - reference)
            stereo_error = np.abs(points[common, 2] * baseline - reference)
            report["same_pixels_diagnostic"] = {
                "held_out_common_points": int(common.sum()),
                "model_median_abs_error_m": float(np.median(model_error)) if len(model_error) else None,
                "two_view_median_abs_error_m": float(np.median(stereo_error)) if len(stereo_error) else None,
                "caveat": "same pixels; different oracle inputs: same-frame dense depth for model versus trajectory baseline for two-view; not an independent contest",
            }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    if args.prediction:
        np.save(args.prediction, prediction)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
