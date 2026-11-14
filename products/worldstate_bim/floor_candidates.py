"""Unconfirmed floor hypotheses from a cuboid and registered semantic views.

This alternative provider makes no selection and never closes a room. An image
label and intersection with a proposed cuboid are correlated evidence, not a
measured 3-D floor point. Callers must validate or explicitly confirm a plane.
"""
from __future__ import annotations
from typing import Any
import numpy as np


def cuboid_floor_candidates(rotation: Any, offsets: Any, views: list[dict], *, max_samples: int = 512) -> dict:
    """Return all six prior planes and per-view floor-mask ray support.

    Each view has a unique registered ``name``, image SHA-256, pinhole camera
    matrix, camera-from-world rotation, camera center, and equal-sized 2-D
    ``labels``/``confidence`` arrays. ADE20K class 3 is floor. This function
    does not calibrate scale or claim labels are correct.
    """
    r = np.asarray(rotation, dtype=float); d = np.asarray(offsets, dtype=float)
    if r.shape != (3, 3) or d.shape != (6,) or not np.isfinite(r).all() or not np.isfinite(d).all():
        raise ValueError('invalid cuboid')
    if not np.allclose(r @ r.T, np.eye(3), atol=1e-4) or np.linalg.det(r) < 0.999 or not np.all(d[3:] > d[:3]):
        raise ValueError('invalid rotation or cuboid bounds')
    if not 1 <= max_samples <= 16384:
        raise ValueError('invalid sample limit')
    result = []
    for face in range(6):
        axis = face % 3
        result.append({'face': face, 'normal': r[axis].tolist(), 'offset': float(-d[face]),
                       'state': 'INFERRED_PRIOR_UNCONFIRMED', 'support_views': [], 'sampled_floor_pixels': 0})
    seen = set()
    for view in views:
        name = view['name']; image_hash = view['image_sha256']
        if not name or name in seen or len(image_hash) != 64 or not view.get('registered', False):
            raise ValueError('each view must be unique, registered, and tied to a source image hash')
        seen.add(name)
        k = np.asarray(view['intrinsics'], dtype=float); rc = np.asarray(view['camera_from_world'], dtype=float)
        center = np.asarray(view['camera_center'], dtype=float); labels = np.asarray(view['labels'])
        confidence = np.asarray(view['confidence'], dtype=float)
        width, height = int(view['width']), int(view['height'])
        if (k.shape != (3, 3) or rc.shape != (3, 3) or center.shape != (3,) or labels.ndim != 2 or
            labels.shape != confidence.shape or min(width, height) <= 0 or not np.isfinite(k).all() or
            not np.isfinite(rc).all() or not np.isfinite(center).all() or not np.isfinite(confidence).all() or
            abs(np.linalg.det(k)) < 1e-12 or not np.allclose(rc @ rc.T, np.eye(3), atol=1e-5)):
            raise ValueError('invalid camera or mask')
        # Same UPerNet score cutoff as the existing semantic fusion. The score
        # is uncalibrated and nearby mask pixels are not independent evidence.
        y, x = np.nonzero((labels == 3) & (confidence >= .30))
        if len(x) > max_samples:
            index = np.linspace(0, len(x) - 1, max_samples, dtype=int); x, y = x[index], y[index]
        if not len(x):
            continue
        h, w = labels.shape
        pixels = np.column_stack(((x + .5) * width / w, (y + .5) * height / h, np.ones(len(x))))
        rays_world = pixels @ np.linalg.inv(k).T @ rc
        c = r @ center; rays = rays_world @ r.T
        distances = np.full((len(x), 6), np.inf)
        for face in range(6):
            axis = face % 3; denom = rays[:, axis]
            t = np.divide(d[face] - c[axis], denom, out=np.full(len(x), np.inf), where=np.abs(denom) > 1e-12)
            with np.errstate(invalid='ignore'):
                hit = c + t[:, None] * rays
            other = [i for i in range(3) if i != axis]
            valid = (t > 0) & np.isfinite(t)
            for i in other:
                valid &= (hit[:, i] >= d[i] - 1e-7) & (hit[:, i] <= d[i+3] + 1e-7)
            distances[valid, face] = t[valid]
        nearest = distances.argmin(axis=1); has_hit = np.isfinite(distances).any(axis=1)
        for face in range(6):
            idx = np.flatnonzero(has_hit & (nearest == face))
            if not len(idx):
                continue
            result[face]['sampled_floor_pixels'] += len(idx)
            result[face]['support_views'].append({'name': name, 'image_sha256': image_hash,
                'sampled_floor_pixels': len(idx), 'example_original_pixels': pixels[idx[:8], :2].tolist()})
    return {'schema': 'worldstate-floor-candidates/0.1', 'provider': 'cuboid-semantic-ray',
        'state': 'UNCONFIRMED_NO_AUTOMATIC_FLOOR_SELECTION', 'candidates': result,
        'limitations': ['Six faces come from a closed cuboid prior, including potentially unobserved surfaces.',
            'Floor pixels are uncalibrated predictions, can contain occluders, and are not independent 3-D points.',
            'Ray intersections assume the predicted box and do not establish geometry, metric scale, or accuracy.',
            'Select only after independent validation or explicit user confirmation; conflicting support remains unknown.']}
