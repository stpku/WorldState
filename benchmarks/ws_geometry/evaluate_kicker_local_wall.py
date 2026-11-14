"""Evaluate a frozen ETH3D local-wall draft against development references.

The held-out view was inspected during development, and official camera poses
are scanner-registered. Neither result is an independent room acceptance.
Scanning is opened only after the input, code and artifact hashes are checked.
"""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import cKDTree

from benchmarks.ws_geometry.evaluate_eth3d_scan import read_sample
from benchmarks.ws_geometry.run_kicker_model_first import checked, sha, write
from products.worldstate_bim.model_first import _basis, _cameras, _project, evaluate_patch


def verify_freeze(path: Path, reconstruction: Path) -> dict:
    freeze = json.loads(path.read_text())
    if freeze.get('schema') != 'worldstate-local-wall-freeze/0.1':
        raise ValueError('unexpected freeze schema')
    for item in freeze['input'] + list(freeze['artifacts'].values()) + freeze['code']:
        if checked(Path(item['path']))['sha256'] != item['sha256']:
            raise ValueError('frozen input, code or model changed')
    bins = [{'file': p.name, 'sha256': sha(p)} for p in sorted(reconstruction.glob('*.bin'))]
    if bins != freeze['source_reconstruction']:
        raise ValueError('frozen reconstruction changed')
    return freeze


def patch_points(params: np.ndarray, across: int = 70, high: int = 30) -> np.ndarray:
    left, right, bottom = params[:3], params[3:6], params[6:9]
    _, up, _, _ = _basis(left, right, bottom)
    a, b = np.meshgrid(np.linspace(0., 1., across), np.linspace(0., params[9], high))
    return left + a.ravel()[:, None] * (right-left) + b.ravel()[:, None] * up


def corners(params: np.ndarray) -> list[np.ndarray]:
    left, right, bottom = params[:3], params[3:6], params[6:9]
    _, up, _, _ = _basis(left, right, bottom)
    return [left, right, right + params[9]*up, left + params[9]*up]


def overlays(data: dict, initial: np.ndarray, optimized: np.ndarray, images: Path, output: Path) -> list[str]:
    output.mkdir()
    cameras = _cameras(data)
    outputs = []
    for ident, camera in cameras.items():
        name = camera['photo']
        if Path(name).name != name or checked(images / name)['sha256'] != camera['sha256']:
            raise ValueError('photo or hash changed')
        raw = cv2.imread(str(images / name))
        if raw is None or raw.shape[:2] != (camera['height_px'], camera['width_px']):
            raise ValueError('photo shape differs from camera')
        size = (1553, 1034)
        scale = np.asarray([size[0] / camera['width_px'], size[1] / camera['height_px']])
        image = cv2.resize(raw, size)
        for params, color in ((initial, (255, 0, 255)), (optimized, (255, 255, 0))):
            poly = np.asarray([np.rint(_project(p, camera) * scale).astype(int) for p in corners(params)], dtype=np.int32)
            cv2.polylines(image, [poly], True, color, 3)
        for observations in data.get('corners', {}).values():
            for obs in observations:
                if obs['image_id'] == ident:
                    pt = tuple(np.rint(np.asarray(obs['pixel_xy']) * scale).astype(int))
                    cv2.circle(image, pt, 6, (0, 0, 255), 2)
        for line in data.get('ceiling_lines', []):
            if line['image_id'] == ident:
                pts = [tuple(np.rint(np.asarray(p) * scale).astype(int)) for p in line['points_px']]
                cv2.line(image, *pts, (0, 255, 255), 2)
        cv2.putText(image, 'MAGENTA prior; CYAN optimized; YELLOW image line; RED detected corner',
                    (15, 30), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 255), 2)
        cv2.putText(image, 'DEVELOPMENT: assumed scale and thickness; NOT a complete wall',
                    (15, 60), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 255), 2)
        filename = Path(name).stem + '-model-comparison.jpg'
        if not cv2.imwrite(str(output / filename), image, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            raise OSError('failed to write overlay')
        outputs.append(filename)
    return outputs


def percentiles(values: np.ndarray) -> dict:
    if not len(values):
        return {'count': 0}
    return {'count': int(len(values)), 'median': float(np.median(values)),
            'p90': float(np.percentile(values, 90)), 'mean': float(np.mean(values))}


def scan_diagnostic(solution: dict, scan_dir: Path, stride: int) -> dict:
    """Create a model-ROI conditioned, automatically proposed scan-plane check."""
    if not 1 <= stride <= 10000:
        raise ValueError('invalid scan stride')
    alignment = scan_dir / 'scan_alignment.mlp'
    root = ET.parse(alignment).getroot()
    frame = solution['frame']
    origin = np.asarray(frame['origin_source'])
    basis = np.column_stack([frame['x_axis_source'], frame['y_axis_source'], frame['z_axis_source']])
    params0 = np.asarray(solution['initial_parameters'])
    params1 = np.asarray(solution['optimized_parameters'])
    surfaces = [patch_points(params0), patch_points(params1)]
    width, height = solution['width_source_units'], solution['height_source_units']
    reports, rois = [], []
    for node in root.findall('./MeshGroup/MLMesh'):
        name = node.attrib['filename']
        if Path(name).name != name:
            raise ValueError('unexpected scan path')
        matrix = np.fromstring(node.findtext('MLMatrix44'), sep=' ').reshape((4, 4))
        if not np.isfinite(matrix).all() or not np.allclose(matrix[3], [0, 0, 0, 1]):
            raise ValueError('invalid scan alignment')
        points, total = read_sample(scan_dir / name, stride)
        points = points @ matrix[:3, :3].T + matrix[:3, 3]
        tree = cKDTree(points)
        nearest = [percentiles(tree.query(surface, workers=1)[0]) for surface in surfaces]
        local = (points-origin) @ basis
        select = (local[:, 0] >= 0) & (local[:, 0] <= width) & (local[:, 2] >= 0) & (local[:, 2] <= height) & (np.abs(local[:, 1]) <= .35)
        rois.append(local[select])
        reports.append({'file': name, 'sha256': sha(scan_dir / name), 'total_vertices': total,
                        'sampled_vertices': len(points), 'points_in_model_defined_roi': int(select.sum()),
                        'surface_to_scan_before': nearest[0], 'surface_to_scan_after': nearest[1]})
    if len(reports) != 2:
        raise ValueError('expected two scanner files')
    candidate = {'status': 'NOT_ENOUGH_SAMPLED_POINTS'}
    if len(rois[0]) >= 30:
        bins = np.linspace(-.35, .35, 71)
        counts, edges = np.histogram(rois[0][:, 1], bins=bins)
        peak = int(np.argmax(counts)); center = float((edges[peak]+edges[peak+1])/2)
        selected = rois[0][np.abs(rois[0][:, 1]-center) <= .02]
        if len(selected) >= 30:
            design = np.column_stack([selected[:, 0], selected[:, 2], np.ones(len(selected))])
            coef, _, rank, _ = np.linalg.lstsq(design, selected[:, 1], rcond=None)
            if rank == 3:
                second = rois[1][np.abs(rois[1][:, 1]-center) <= .03]
                residual = np.abs(second[:, 1]-(coef[0]*second[:, 0]+coef[1]*second[:, 2]+coef[2]))
                candidate = {'status': 'AUTOMATIC_UNREVIEWED_CANDIDATE',
                    'method': 'largest signed-depth histogram peak in model-defined ROI of scan 1; ordinary local plane fit',
                    'coordinate_system': 'optimized patch frame, source units', 'peak_y': center,
                    'plane_y_equals_ax_plus_bz_plus_c': coef.tolist(), 'fit_points': len(selected),
                    'scan_2_near_selected_peak_absolute_residual': percentiles(residual),
                    'warning': 'ROI and peak are model-conditioned; the surface may be furniture or another object. No human validation.'}
    return {'scan_alignment_sha256': sha(alignment), 'stride': stride, 'scans': reports,
            'scan_plane_candidate': candidate, 'unit': 'source reconstruction units, not independently calibrated metres',
            'limits': ['Official camera poses are scanner-registered; model and scan are not independent in pose.',
                       'Nearest sampled scan surfaces include clutter; model ROI biases surface and plane selection.',
                       'No independently audited wall instances, full boundaries, floor or dimensions.',
                       'Distances cannot establish wall precision, recall, dimensions or WS-RealRoom acceptance.']}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--freeze', type=Path, required=True)
    p.add_argument('--reconstruction', type=Path, required=True)
    p.add_argument('--holdout', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--scan-dir', type=Path, help='Known-pose scanner-frame diagnostic only')
    p.add_argument('--stride', type=int, default=50)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('choose a new evaluation directory')
    freeze = verify_freeze(a.freeze, a.reconstruction)
    training = json.loads(Path(freeze['input'][0]['path']).read_text())
    solution = json.loads(Path(freeze['artifacts']['solution.json']['path']).read_text())
    # Holdout and laser scans are opened only after verification of the freeze.
    holdout = json.loads(a.holdout.read_text())
    if holdout['source_reconstruction'] != freeze['source_reconstruction'] or holdout['camera_mode'] != freeze['mode']:
        raise ValueError('held-out observations use a different camera source')
    initial = np.asarray(solution['initial_parameters'])
    optimized = np.asarray(solution['optimized_parameters'])
    before, after = evaluate_patch(initial, holdout), evaluate_patch(optimized, holdout)
    a.output.mkdir(parents=True)
    training_overlays = overlays(training, initial, optimized, a.images, a.output / 'training-overlays')
    holdout_overlays = overlays(holdout, initial, optimized, a.images, a.output / 'holdout-overlays')
    if freeze['mode'] == 'ETH3D_KNOWN_POSE_SCANNER_REGISTERED_NOT_PHOTO_ONLY':
        if a.scan_dir is None:raise ValueError('known-pose diagnostic requires scan directory')
        scan = scan_diagnostic(solution, a.scan_dir, a.stride)
    else:
        if a.scan_dir is not None:raise ValueError('photo-only source is not aligned to the scanner; refusing a misleading scan comparison')
        scan = {'status':'NOT_EVALUATED_PHOTO_ONLY_FRAME_HAS_NO_INDEPENDENT_SCAN_ALIGNMENT',
                'scans':[], 'scan_plane_candidate':None}
    report = {'schema': 'worldstate-local-wall-development-evaluation/0.1',
        'freeze_sha256': sha(a.freeze), 'holdout_sha256': sha(a.holdout),
        'holdout_scope': 'excluded from parameter optimization, but inspected during scene development; not blind',
        'training_before': solution['before'], 'training_after': solution['after'],
        'holdout_before': before, 'holdout_after': after,
        'training_overlays': training_overlays, 'holdout_overlays': holdout_overlays,
        'scan': scan, 'wall_instance_precision_recall': 'NOT_MEASURED',
        'independent_wall_dimensions': 'NOT_MEASURED', 'human_cost': 'NOT_MEASURED',
        'release_status': 'NOT_RELEASE_READY'}
    write(a.output / 'evaluation.json', report)
    print(json.dumps({'training_rms_before_px': solution['before']['rms_px'],
        'training_rms_after_px': solution['after']['rms_px'], 'holdout_rms_before_px': before['rms_px'],
        'holdout_rms_after_px': after['rms_px'], 'holdout_max_after_px': after['maximum_px'],
        'scan': scan['scans'], 'scan_plane_candidate': scan['scan_plane_candidate'],
        'independent_dimensions': report['independent_wall_dimensions']}, indent=2))


if __name__ == '__main__':
    main()
