"""Flag conflicting multiview floor semantics by inspecting local image crops.

This optional development check uses the same model at a second image scale.
It does not relabel pixels, prove geometry, confirm objects, or produce IFC.
"""
from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
import json
import math
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .multiview_fusion import _deduplicate_floor_tracks, _plane_fit
from .semantic_vision import UperNetOnnxProvider

# ADE20K classes named in the upstream model's id2label configuration.
_CLASS_NAMES = {0: 'wall', 3: 'floor', 19: 'chair', 75: 'swivel chair', 110: 'stool'}


def _crop_prediction(image: np.ndarray, xy: list[float], provider: Any) -> dict:
    """Run an exact-pixel-centred, bounded local crop through the pinned model."""
    height, width = image.shape[:2]
    x, y = map(float, xy)
    if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x < width and 0 <= y < height):
        raise ValueError('floor observation is outside its image')
    # An exploratory crop of 35% of the short image side provides context while
    # making small occluders larger than in the full-image 128x128 output.
    side = max(32, round(min(width, height)*0.35))
    side = min(side, width, height)
    x0 = max(0, min(width-side, round(x)-side//2))
    y0 = max(0, min(height-side, round(y)-side//2))
    crop = image[y0:y0+side, x0:x0+side]
    rgb = cv2.cvtColor(cv2.resize(crop, (512, 512)), cv2.COLOR_BGR2RGB).astype(np.float32)/255
    rgb = (rgb-np.array([.485, .456, .406], np.float32))/np.array([.229, .224, .225], np.float32)
    logits = provider.session.run(None, {'pixel_values': rgb.transpose(2, 0, 1)[None]})[0][0]
    if logits.shape != (150, 128, 128) or not np.isfinite(logits).all():
        raise ValueError('invalid local semantic model output')
    mx = min(127, int((x-x0)*128/side)); my = min(127, int((y-y0)*128/side))
    values = logits[:, my, mx]; exp = np.exp(values-values.max()); scores = exp/exp.sum()
    class_id = int(np.argmax(scores))
    return {'crop_bbox_px': [x0, y0, x0+side, y0+side], 'mask_xy': [mx, my],
            'class_id': class_id, 'class_name': _CLASS_NAMES.get(class_id, f'ADE20K class {class_id}'),
            'model_score_uncalibrated': float(scores[class_id]), 'floor_score_uncalibrated': float(scores[3])}


def review_floor_tracks(fusion: dict, images: Path, provider: Any, *, max_tracks: int = 20,
                        progress: bool = False) -> dict:
    """Compare floor-track observations with local-crop model predictions.

    All conflicting points remain in the original fusion. A counterfactual
    floor fit merely quarantines them to show whether further evidence is
    needed. Without a fitted floor, supported floor-class tracks are reviewed.
    Review coverage may be capped and scores are not calibrated.
    """
    if fusion.get('schema') != 'worldstate-multiview-semantic-fusion/0.1':
        raise ValueError('unsupported fusion result')
    if isinstance(max_tracks, bool) or not isinstance(max_tracks, int) or not 1 <= max_tracks <= 100:
        raise ValueError('max_tracks must be between 1 and 100')
    if fusion.get('model_sha256') != UperNetOnnxProvider.MODEL_SHA256:
        raise ValueError('fusion model hash does not match the local review model')
    cameras = {c['image_id']: c for c in fusion['cameras']}
    if len(cameras) != len(fusion['cameras']):
        raise ValueError('duplicate camera ID')
    tracks = {t['id']: t for t in fusion['tracks']}
    if len(tracks) != len(fusion['tracks']):
        raise ValueError('duplicate track ID')
    if fusion['floor_planes']:
        floor_ids = sorted({track_id for p in fusion['floor_planes'] for track_id in p['support_point_ids']})
        review_scope = 'FITTED_FLOOR_SUPPORT_TRACKS'
    else:
        # If robust fitting failed, still help the user inspect the floor
        # evidence that prevented generation instead of returning an empty review.
        floor_ids = sorted(t['id'] for t in fusion['tracks']
                           if t.get('status') == 'SUPPORTED' and t.get('semantic_class') == 3)
        review_scope = 'SUPPORTED_FLOOR_TRACKS_WITHOUT_A_FITTED_PLANE'
    for track_id in floor_ids:
        t = tracks.get(track_id)
        if not t or t.get('status') != 'SUPPORTED' or t.get('semantic_class') != 3:
            raise ValueError('floor support does not match a supported floor track')
    distinct_support, support_duplicates = _deduplicate_floor_tracks([tracks[i] for i in floor_ids])
    distinct_support_ids = [t['id'] for t in distinct_support]
    selected = distinct_support_ids[:max_tracks]
    reviewed = []; started = time.monotonic(); cached_images: OrderedDict[str, np.ndarray] = OrderedDict()
    for track_id in selected:
        track = tracks[track_id]; observations = []; used_ids: set[int] = set()
        for observation in track['observations']:
            image_id = observation['image_id']
            if not observation['usable'] or observation['semantic_class'] != 3 or image_id in used_ids:
                continue
            camera = cameras.get(image_id); name = observation['photo']; path = images/name
            if (camera is None or camera['photo'] != name or camera['sha256'] != observation['photo_sha256']
                    or Path(name).name != name or path.is_symlink() or not path.is_file()):
                raise ValueError('floor observation is not bound to a registered source image')
            if name not in cached_images:
                raw = path.read_bytes()
                if hashlib.sha256(raw).hexdigest() != observation['photo_sha256']:
                    raise ValueError('source image hash mismatch')
                decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
                if decoded is None or decoded.shape[:2] != (camera['height_px'], camera['width_px']):
                    raise ValueError('source image dimensions do not match the camera')
                cached_images[name] = decoded
                if len(cached_images) > 4:
                    cached_images.popitem(last=False)
            else:
                cached_images.move_to_end(name)
            prediction = _crop_prediction(cached_images[name], observation['pixel_xy'], provider)
            observations.append({'image_id': image_id, 'photo': name, 'photo_sha256': observation['photo_sha256'],
                'pixel_xy': observation['pixel_xy'], 'full_image_class_id': 3,
                'full_image_score_uncalibrated': observation['model_score_uncalibrated'], 'local_crop': prediction})
            used_ids.add(image_id)
            if len(observations) == 2:
                break
        if len(observations) < 2:
            status = 'INSUFFICIENT_DISTINCT_VIEWS'
        elif all(o['local_crop']['class_id'] != 3 for o in observations):
            status = 'MULTIVIEW_CROP_DISAGREEMENT_REVIEW_REQUIRED'
        elif any(o['local_crop']['class_id'] != 3 for o in observations):
            status = 'PARTIAL_CROP_DISAGREEMENT_REVIEW_REQUIRED'
        else:
            status = 'NO_CROP_DISAGREEMENT_NOT_VERIFIED'
        reviewed.append({'track_id': track_id, 'status': status, 'observations': observations})
        if progress:
            print(f'reviewed floor track {track_id} ({len(reviewed)}/{len(selected)}): {status}', flush=True)
    disputed = [r['track_id'] for r in reviewed if r['status'] in
                {'MULTIVIEW_CROP_DISAGREEMENT_REVIEW_REQUIRED', 'PARTIAL_CROP_DISAGREEMENT_REVIEW_REQUIRED'}]
    candidate_tracks = [t for t in tracks.values() if t['status'] == 'SUPPORTED' and t['semantic_class'] == 3]
    original_distinct_tracks, original_duplicate_groups = _deduplicate_floor_tracks(candidate_tracks)
    quarantined = set(disputed)
    for group in original_duplicate_groups:
        ids = {group['retained_track_id'], *group['redundant_track_ids']}
        if ids & quarantined:quarantined.update(ids)
    distinct_tracks, duplicate_groups = _deduplicate_floor_tracks([t for t in candidate_tracks if t['id'] not in quarantined])
    counterfactual, threshold = _plane_fit(distinct_tracks, 8, 31)
    return {'schema': 'worldstate-floor-semantic-review/0.1',
        'status': 'DEVELOPMENT_REVIEW_NOT_GROUND_TRUTH', 'source_model_sha256': fusion['model_sha256'],
        'semantic_manifest_sha256': fusion['semantic_manifest_sha256'],
        'source_reconstruction': fusion['source_reconstruction'],
        'method': 'Compare full-image floor prediction with the same model on a 35%-of-short-side local crop, up to two distinct source views.',
        'review_scope': review_scope, 'review_scope_track_count': len(floor_ids),
        'distinct_review_scope_track_count': len(distinct_support_ids), 'support_duplicate_groups': support_duplicates,
        'reviewed_track_count': len(reviewed),
        'unreviewed_support_track_ids': distinct_support_ids[len(selected):], 'disputed_track_ids': disputed,
        'quarantined_track_ids_including_duplicates': sorted(quarantined),
        'track_reviews': reviewed, 'counterfactual_excluding_disputed_tracks': {
            'status': 'HYPOTHETICAL_NOT_A_CONFIRMED_CORRECTION', 'minimum_support_points': 8,
            'fit_threshold_source_units': threshold, 'floor_planes': counterfactual,
            'distinct_tracks_after_quarantine': len(distinct_tracks), 'duplicate_groups': duplicate_groups,
            'unreviewed_floor_track_ids': [t['id'] for t in original_distinct_tracks
                                           if t['id'] not in selected and t['id'] not in quarantined]},
        'runtime_seconds': round(time.monotonic()-started, 3),
        'limitations': ['Local and full-image predictions use the same model and are correlated.',
            'A disagreement requests review; agreement and model scores do not establish truth.',
            'This diagnostic does not modify the input fusion, automatically correct the model, or export IFC.',
            'Floor fitting and camera poses remain unverified; no independent room accuracy is measured.']}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fusion', type=Path, required=True); p.add_argument('--images', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--max-tracks', type=int, default=20)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('choose a new output path')
    fusion = json.loads(a.fusion.read_text())
    provider = UperNetOnnxProvider(a.model)
    result = review_floor_tracks(fusion, a.images, provider, max_tracks=a.max_tracks, progress=True)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    print(json.dumps({'reviewed_tracks': result['reviewed_track_count'],
                      'disputed_tracks': result['disputed_track_ids'],
                      'counterfactual_floor_planes': len(result['counterfactual_excluding_disputed_tracks']['floor_planes']),
                      'runtime_seconds': result['runtime_seconds']}, indent=2))


if __name__ == '__main__':
    main()
