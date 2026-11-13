"""Calibrated two-view, photo-only sparse geometry for research drafts.

Coordinates are in the first camera frame and have *arbitrary scale*.  This
module does not infer building semantics or make claims about wall dimensions.
The optional dependencies are confined to the BIM product, not WorldState Core.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class TwoViewResult:
    """Camera motion and matched, triangulated points in arbitrary units."""

    rotation: np.ndarray
    translation: np.ndarray
    points: np.ndarray
    pixels1: np.ndarray
    pixels2: np.ndarray
    matches: int
    inliers: int
    median_reprojection_px: float
    median_parallax_deg: float


def reconstruct(image1: np.ndarray, image2: np.ndarray, intrinsics: np.ndarray) -> TwoViewResult:
    """Estimate sparse geometry from two overlapping calibrated RGB photos.

    Raises ``ValueError`` when matching, pose recovery, or triangulation does
    not provide enough valid evidence. Result scale and semantic labels remain
    unknown. Images must have the same size and use the supplied calibration.
    """
    if image1 is None or image2 is None or image1.shape[:2] != image2.shape[:2]:
        raise ValueError("both readable images must have the same dimensions")
    k = np.asarray(intrinsics, dtype=np.float64)
    if (k.shape != (3, 3) or not np.isfinite(k).all() or k[0, 0] <= 0 or k[1, 1] <= 0 or
            not np.allclose(k[2], [0, 0, 1])):
        raise ValueError("a finite 3x3 calibrated intrinsic matrix is required")
    cv2.setRNGSeed(0)
    cv2.setNumThreads(1)
    gray1 = cv2.cvtColor(image1, cv2.COLOR_BGR2GRAY) if image1.ndim == 3 else image1
    gray2 = cv2.cvtColor(image2, cv2.COLOR_BGR2GRAY) if image2.ndim == 3 else image2
    sift = cv2.SIFT_create(nfeatures=4000)
    key1, desc1 = sift.detectAndCompute(gray1, None)
    key2, desc2 = sift.detectAndCompute(gray2, None)
    if desc1 is None or desc2 is None or len(desc1) < 8 or len(desc2) < 8:
        raise ValueError("not enough visual features")
    candidates = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc1, desc2, k=2)
    matches = [a for pair in candidates if len(pair) == 2 for a, b in [pair] if a.distance < 0.75 * b.distance]
    if len(matches) < 8:
        raise ValueError("not enough reliable feature matches")
    p1 = np.array([key1[m.queryIdx].pt for m in matches], dtype=np.float64)
    p2 = np.array([key2[m.trainIdx].pt for m in matches], dtype=np.float64)
    essential, mask = cv2.findEssentialMat(p1, p2, k, method=cv2.RANSAC, prob=0.999, threshold=1.0)
    if essential is None or essential.shape != (3, 3) or mask is None:
        raise ValueError("essential matrix estimation failed or is ambiguous")
    _, rotation, translation, pose_mask = cv2.recoverPose(essential, p1, p2, k, mask=mask)
    keep = pose_mask.ravel() != 0
    p1, p2 = p1[keep], p2[keep]
    if len(p1) < 8:
        raise ValueError("not enough positive-depth pose inliers")
    proj1 = k @ np.hstack((np.eye(3), np.zeros((3, 1))))
    proj2 = k @ np.hstack((rotation, translation))
    homogeneous = cv2.triangulatePoints(proj1, proj2, p1.T, p2.T).T
    valid = np.abs(homogeneous[:, 3]) > 1e-10
    points = np.full((len(homogeneous), 3), np.nan)
    points[valid] = homogeneous[valid, :3] / homogeneous[valid, 3, None]
    points2 = points @ rotation.T + translation.ravel()
    valid &= np.isfinite(points).all(axis=1) & (points[:, 2] > 0) & (points2[:, 2] > 0)
    points, p1, p2, points2 = points[valid], p1[valid], p2[valid], points2[valid]
    if len(points) < 8:
        raise ValueError("not enough valid triangulated points")
    xy1 = (points @ k.T)[:, :2] / points[:, 2, None]
    xy2 = (points2 @ k.T)[:, :2] / points2[:, 2, None]
    residuals = np.concatenate((np.linalg.norm(xy1 - p1, axis=1), np.linalg.norm(xy2 - p2, axis=1)))
    camera2 = -rotation.T @ translation.ravel()
    ray1 = points / np.linalg.norm(points, axis=1)[:, None]
    ray2 = points - camera2
    ray2 /= np.linalg.norm(ray2, axis=1)[:, None]
    parallax = np.degrees(np.arccos(np.clip(np.sum(ray1 * ray2, axis=1), -1.0, 1.0)))
    return TwoViewResult(rotation, translation.ravel(), points, p1, p2, len(matches), len(points),
                         float(np.median(residuals)), float(np.median(parallax)))
