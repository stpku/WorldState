"""Fit a visible RGB-D surface patch without inventing a complete wall.

An operator supplies a region of interest. Depth samples are measurements;
the plane and the operator's possible-wall label are inferences. Neither
unseen boundaries nor wall thickness, height, or an IFC solid are inferred.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SurfaceCandidate:
    """RANSAC plane in the color camera frame, with visible support only."""

    normal_camera: np.ndarray
    offset_m: float
    centroid_camera_m: np.ndarray
    visible_span_m: np.ndarray
    valid_depth_samples: int
    inlier_samples: int
    median_residual_m: float


def fit_visible_surface(depth: np.ndarray, mask: np.ndarray, intrinsics: np.ndarray,
                        *, depth_factor: float = 5000.0, stride: int = 2,
                        threshold_m: float = 0.025, iterations: int = 250) -> SurfaceCandidate:
    """Fit a plane to a manually selected, depth-registered image region.

    The caller supplies the correct calibration, units and registered frame.
    Return a bounded visible patch, not a wall solid. Fail when evidence is
    insufficient or incoherent; the RANSAC threshold is not an accuracy claim.
    """
    if depth.ndim != 2 or mask.shape != depth.shape or depth.dtype != np.uint16:
        raise ValueError("a registered uint16 depth image and matching mask are required")
    k = np.asarray(intrinsics, dtype=float)
    if (k.shape != (3, 3) or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0 or
            not np.allclose(k[2], [0, 0, 1]) or abs(k[0, 1]) > 1e-12 or abs(k[1, 0]) > 1e-12):
        raise ValueError("valid pinhole camera intrinsics are required")
    if (not np.isfinite(depth_factor) or depth_factor <= 0 or stride < 1 or
            not np.isfinite(threshold_m) or threshold_m <= 0 or iterations < 1):
        raise ValueError("invalid depth factor or fitting configuration")
    rows, cols = np.indices(depth.shape)
    selected = np.asarray(mask, dtype=bool) & (depth > 0) & (rows % stride == 0) & (cols % stride == 0)
    ys, xs = np.nonzero(selected)
    z = depth[ys, xs].astype(float) / depth_factor
    points = np.column_stack(((xs - k[0, 2]) * z / k[0, 0], (ys - k[1, 2]) * z / k[1, 1], z))
    if len(points) < 100:
        raise ValueError("fewer than 100 valid depth samples in the selected region")
    rng = np.random.default_rng(0)
    best: np.ndarray | None = None
    best_count = 0
    for _ in range(iterations):
        a, b, c = points[rng.choice(len(points), size=3, replace=False)]
        normal = np.cross(b - a, c - a)
        length = np.linalg.norm(normal)
        if length < 1e-9:
            continue
        normal /= length
        inliers = np.abs((points - a) @ normal) <= threshold_m
        count = int(inliers.sum())
        if count > best_count:
            best, best_count = inliers, count
    if best is None or best_count < 100 or best_count / len(points) < 0.6:
        raise ValueError("selected depth region does not support a coherent plane")
    samples = points[best]
    centroid = samples.mean(axis=0)
    _, _, basis = np.linalg.svd(samples - centroid, full_matrices=False)
    normal = basis[-1]
    if np.dot(normal, centroid) > 0:
        normal = -normal
    offset = -float(np.dot(normal, centroid))
    residuals = np.abs((samples - centroid) @ normal)
    uv = (samples - centroid) @ basis[:2].T
    span = np.percentile(uv, 98, axis=0) - np.percentile(uv, 2, axis=0)
    return SurfaceCandidate(normal, offset, centroid, span, len(points), best_count, float(np.median(residuals)))
