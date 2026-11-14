"""Experimental multiview wall-floor lines for an open, evidence-linked room.

This provider uses the registered COLMAP cameras and the same semantic floor
plane as the sparse-plane route. It detects image-space boundaries, associates
them across views, and estimates free 3-D lines from backprojection planes.
Neither the lines nor their inferred intersections establish surveyed geometry.
"""
from __future__ import annotations

import hashlib
import itertools
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pycolmap
from scipy.optimize import least_squares

from .multiview_fusion import (
    _camera_matrix, _read_semantic_masks, _sha, apply_multiview_scale,
    triangulate_observations,
)


def _floor_basis(fusion: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, float]:
    if not fusion.get('floor_planes') or fusion.get('floor_up') is None:
        raise ValueError('缺少可用的多视图地面候选')
    floor = fusion['floor_planes'][0]
    normal = np.asarray(floor['normal'], dtype=float)
    up = np.asarray(fusion['floor_up'], dtype=float)
    if normal.shape != (3,) or up.shape != (3,) or not np.isfinite(normal).all() or not np.isfinite(up).all():
        raise ValueError('地面坐标无效')
    length = float(np.linalg.norm(normal)); up_length = float(np.linalg.norm(up))
    if length < 1e-8 or up_length < 1e-8:
        raise ValueError('地面法向退化')
    normal /= length; up /= up_length
    if abs(float(normal @ up)) < .999:
        raise ValueError('地面法向与向上方向不一致')
    offset = float(floor['offset']) / length
    origin = -offset * normal
    basis = np.eye(3)[int(np.argmin(np.abs(up)))]
    ex = np.cross(up, basis); ex /= np.linalg.norm(ex)
    ey = np.cross(up, ex); ey /= np.linalg.norm(ey)
    return origin, ex, ey, normal, offset


def _project_to_floor(camera: dict, pixel: list[float], origin: np.ndarray, ex: np.ndarray,
                      ey: np.ndarray, normal: np.ndarray, offset: float) -> list[float]:
    K, R, t = _camera_matrix(camera)
    center = -R.T @ t
    ray = R.T @ np.linalg.solve(K, np.array([*pixel, 1.], dtype=float))
    ray /= np.linalg.norm(ray)
    denominator = float(normal @ ray)
    if abs(denominator) < math.sin(math.radians(3)):
        raise ValueError('视线与地面近乎平行')
    distance = -(float(normal @ center) + offset) / denominator
    if distance <= 0:
        raise ValueError('地面交点位于相机后方')
    point = center + distance * ray
    return [float((point-origin) @ ex), float((point-origin) @ ey)]


def extract_lines(fusion: dict, sparse: Path, images: Path, masks: Path) -> dict:
    """Detect real image lines; verify reconstruction, photographs and masks."""
    source = [{'file': p.name, 'sha256': _sha(p)} for p in sorted(sparse.glob('*.bin'))]
    if source != fusion.get('source_reconstruction') or _sha(masks/'manifest.json') != fusion.get('semantic_manifest_sha256'):
        raise ValueError('语义掩膜与当前三维重建不匹配')
    reconstruction = pycolmap.Reconstruction(str(sparse))
    records, arrays = _read_semantic_masks(reconstruction, images, masks)
    cameras = {c['image_id']: c for c in fusion['cameras']}
    if set(records) != set(cameras):
        raise ValueError('已注册相机与融合结果不一致')
    origin, ex, ey, normal, offset = _floor_basis(fusion)
    lines = []; rejected = defaultdict(int)
    for image_id in sorted(records):
        image = reconstruction.image(image_id); camera = cameras[image_id]
        transform = image.cam_from_world()
        if (camera['sha256'] != records[image_id]['sha256'] or camera['photo'] != image.name or
                camera['camera_model'] != image.camera.model_name or
                not np.allclose(camera['intrinsics'], image.camera.params, rtol=0, atol=1e-8) or
                not np.allclose(camera['rotation_camera_from_world'], transform.rotation.matrix(), rtol=0, atol=1e-8) or
                not np.allclose(camera['translation_camera_from_world'], transform.translation, rtol=0, atol=1e-8)):
            raise ValueError('融合相机与重建文件不一致')
        width, height = int(camera['width_px']), int(camera['height_px'])
        labels = cv2.resize(arrays[image_id][0], (width, height), interpolation=cv2.INTER_NEAREST)
        wall = (labels == 0).astype(np.uint8); floor = (labels == 3).astype(np.uint8)
        boundary = cv2.bitwise_and(cv2.Canny(floor * 255, 50, 150), cv2.dilate(wall, np.ones((7, 7), np.uint8)))
        found = cv2.HoughLinesP(boundary, 1, np.pi / 180, threshold=max(18, width//45),
                                minLineLength=max(35, width//12), maxLineGap=max(8, width//50))
        segments = sorted([tuple(map(int, x[0])) for x in found] if found is not None else [])
        for x1, y1, x2, y2 in segments:
            pixels = [[x1, y1], [x2, y2]]
            try:
                projected = [_project_to_floor(camera, p, origin, ex, ey, normal, offset) for p in pixels]
            except ValueError:
                rejected['floor_ray_degenerate_or_behind'] += 1
                continue
            direction = np.asarray(projected[1]) - projected[0]
            if np.linalg.norm(direction) < 1e-8:
                rejected['zero_length_floor_projection'] += 1
                continue
            key = f"{camera['sha256']}:{pixels}"
            lines.append({'id': 'image-line-'+hashlib.sha256(key.encode()).hexdigest()[:16],
                'image_id': image_id, 'photo': image.name, 'photo_sha256': camera['sha256'],
                'mask_sha256': records[image_id]['mask_sha256'], 'points_px': pixels,
                'floor_projected_relative': projected,
                'endpoint_status': ['IMAGE_EDGE' if x <= 2 or y <= 2 or x >= width-3 or y >= height-3
                                    else 'FRAGMENT_END_NOT_CONFIRMED_CORNER' for x, y in pixels],
                'kind': 'wall_floor_semantic_boundary', 'status': 'AI_PROPOSAL_UNVERIFIED',
                'pixel_tolerance': math.ceil(math.hypot(width/128, height/128)) + 1})
            if len(lines)>512:
                raise ValueError('语义边界候选过多，无法可靠关联；请检查照片或补充人工标注')
    return {'schema': 'worldstate-image-structure-lines/0.1', 'source_reconstruction': source,
            'semantic_manifest_sha256': fusion['semantic_manifest_sha256'], 'lines': lines,
            'rejected': dict(rejected), 'method': 'UPerNet wall/floor boundary and image Hough segments',
            'warning': 'The 128x128 semantic mask sets an image-space tolerance, not an accuracy guarantee.'}


def _image_line(theta: float, distance: float, camera: dict, basis: tuple) -> np.ndarray | None:
    origin, ex, ey, _, _ = basis
    n = np.array([math.cos(theta), math.sin(theta)]); direction = np.array([-n[1], n[0]])
    point = origin + ex*(n[0]*distance) + ey*(n[1]*distance)
    another = point + ex*direction[0] + ey*direction[1]
    K, R, t = _camera_matrix(camera)
    a = K @ (R @ point + t); b = K @ (R @ another + t)
    line = np.cross(a, b); magnitude = np.linalg.norm(line[:2])
    return line/magnitude if magnitude > 1e-10 else None


def _line_error(theta: float, distance: float, line: dict, cameras: dict, basis: tuple) -> float:
    predicted = _image_line(theta, distance, cameras[line['image_id']], basis)
    if predicted is None:
        return float('inf')
    return max(abs(float(predicted @ np.array([*xy, 1.]))) for xy in line['points_px'])


def _support(theta: float, distance: float, lines: list[dict], cameras: dict, basis: tuple) -> dict:
    result = {}
    for line in lines:
        err = _line_error(theta, distance, line, cameras, basis)
        if err <= line['pixel_tolerance']:
            prior = result.get(line['image_id'])
            if prior is None or err < prior[0]:
                result[line['image_id']] = (err, line)
    return result


def _free_line(support: dict, cameras: dict) -> dict:
    """Fit a 3-D line as the common nullspace of image backprojection planes."""
    planes = [];centers = []
    for _, line in support.values():
        K, R, t = _camera_matrix(cameras[line['image_id']]); P = K @ np.column_stack((R, t))
        centers.append(-R.T@t)
        a, b = (np.array([*p, 1.]) for p in line['points_px'])
        plane = P.T @ np.cross(a, b); magnitude = np.linalg.norm(plane[:3])
        if magnitude < 1e-10:
            raise ValueError('图像线反投影平面退化')
        planes.append(plane/magnitude)
    if len(centers)<2 or max(np.linalg.norm(a-b) for a,b in itertools.combinations(centers,2))<1e-9:
        raise ValueError('相机基线为零，线三角化退化')
    max_angle = max(math.degrees(math.acos(float(np.clip(abs(a[:3] @ b[:3]), -1, 1))))
                    for a, b in itertools.combinations(planes, 2))
    if max_angle < 5:
        raise ValueError('跨视图线的反投影平面夹角不足')
    _, singular, vh = np.linalg.svd(np.asarray(planes), full_matrices=True)
    if singular[1] < 1e-8:
        raise ValueError('多视图线求解退化')
    a, b = vh[-2:]; direction = a[:3]*b[3] - b[:3]*a[3]
    magnitude = np.linalg.norm(direction)
    if magnitude < 1e-10:
        raise ValueError('多视图线方向退化')
    direction /= magnitude
    q = a if abs(a[3]) > abs(b[3]) else b
    if abs(q[3]) < 1e-10:
        raise ValueError('多视图线位于无穷远')
    point = q[:3]/q[3]; point -= direction*float(point @ direction)
    return {'point': point.tolist(), 'direction': direction.tolist(),
            'backprojection_plane_max_angle_deg': max_angle,
            'singular_values': singular.tolist(), 'spatial_uncertainty': 'NOT_QUANTIFIED'}


def _free_line_error(line3d: dict, observation: dict, cameras: dict) -> float:
    K, R, t = _camera_matrix(cameras[observation['image_id']])
    point = np.asarray(line3d['point']); direction = np.asarray(line3d['direction'])
    a = K @ (R@point+t); b = K @ (R@(point+direction)+t)
    projected = np.cross(a,b); magnitude = np.linalg.norm(projected[:2])
    if magnitude < 1e-10:
        return float('inf')
    projected /= magnitude
    return max(abs(float(projected @ np.array([*p,1.]))) for p in observation['points_px'])


def _visible_intervals(theta: float, lines: list[dict]) -> list[dict]:
    direction = np.array([-math.sin(theta), math.cos(theta)]); intervals = []
    for line in lines:
        a, b = (np.asarray(p) for p in line['floor_projected_relative'])
        low, high = sorted((float(a @ direction), float(b @ direction)))
        intervals.append((low, high, line['image_id']))
    points = sorted({x for low, high, _ in intervals for x in (low, high)})
    output = []
    for left, right in zip(points[:-1], points[1:]):
        midpoint = (left+right)/2
        views = {v for low, high, v in intervals if low <= midpoint <= high}
        if len(views) < 2:
            continue
        if output and math.isclose(output[-1]['range_relative'][1], left, abs_tol=1e-9):
            output[-1]['range_relative'][1] = right
        else:
            output.append({'range_relative': [left, right], 'minimum_distinct_views': 2})
    return output


def _parallel_separation_over_shared_support(a: dict, b: dict) -> float | None:
    """Minimum line separation only where both visibility intervals overlap."""
    na=np.array([math.cos(a['theta_rad']),math.sin(a['theta_rad'])]); va=np.array([-na[1],na[0]])
    nb=np.array([math.cos(b['theta_rad']),math.sin(b['theta_rad'])]); vb=np.array([-nb[1],nb[0]])
    intervals=[]
    for interval in b['visible_support_intervals']:
        points=[nb*b['offset_relative']+vb*t for t in interval['range_relative']]
        intervals.append(sorted(float(point@va) for point in points))
    distances=[]
    for span in a['visible_support_intervals']:
        for other in intervals:
            low=max(span['range_relative'][0],other[0]);high=min(span['range_relative'][1],other[1])
            if low>=high:continue
            ends=[float(nb@(na*a['offset_relative']+va*t)-b['offset_relative']) for t in (low,high)]
            distances.append(0. if ends[0]*ends[1]<=0 else min(abs(x) for x in ends))
    return min(distances) if distances else None


def triangulate_annotated_corners(fusion: dict, annotations: list[dict], uploads: list[dict]) -> dict:
    """Triangulate same-ID corner clicks; do not silently connect walls.

    Observations are attributed to the recorded operator and must use distinct
    registered photos. A click is evidence of a claimed correspondence, not
    proof of the physical corner or of the unobserved wall boundary.
    """
    _,_,_,normal,offset=_floor_basis(fusion)
    cameras={c['sha256']:c for c in fusion['cameras']}
    photos={x['id']:x for x in uploads};by_corner=defaultdict(list);rejected=[];accepted=[]
    for ann in annotations:
        if ann.get('kind')!='corner':continue
        ident=ann.get('object_id')
        if not isinstance(ident,str) or not ident.strip() or len(ident)>120:
            rejected.append({'annotation_id':ann.get('id'),'reason':'missing corner association ID'});continue
        by_corner[ident].append(ann)
    for ident,items in sorted(by_corner.items()):
        observations=[];reason=None
        for ann in items:
            photo=photos.get(ann.get('photo_id'));camera=cameras.get(photo.get('sha256')) if photo else None
            if not camera or len(ann.get('points',[]))!=1:
                reason='corner observation must refer to one point in a registered photo';break
            observations.append({'image_id':camera['image_id'],'photo_sha256':camera['sha256'],
                'pixel_xy':ann['points'][0],'annotation_id':ann.get('id'),
                'operator_kind':ann.get('operator_kind','unknown'),'origin':ann.get('origin','manual_annotation')})
        if reason:
            rejected.append({'corner_id':ident,'reason':reason});continue
        try:
            result=triangulate_observations(fusion['cameras'],observations)
        except ValueError as exc:
            rejected.append({'corner_id':ident,'reason':str(exc),'observations':observations});continue
        floor_residual=abs(float(normal@np.asarray(result['xyz'])+offset))
        if all(x['operator_kind']=='user' for x in observations):
            status=('USER_DECLARED_CORRESPONDENCE_NOT_INDEPENDENTLY_VERIFIED' if all(
                x['origin']=='manual_annotation' for x in observations) else 'USER_ACCEPTED_AI_OR_MIXED_CORRESPONDENCE_UNVERIFIED')
        elif any(x['operator_kind']=='automation' for x in observations):status='SCRIPTED_OR_MIXED_CORRESPONDENCE_NOT_HUMAN'
        else:status='CORRESPONDENCE_OPERATOR_UNKNOWN'
        result.update({'corner_id':ident,'source_observations':observations,
            'floor_plane_residual_relative':floor_residual,
            'floor_consistency':'CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY' if floor_residual<=3*float(fusion['floor_planes'][0]['fit_rms_arbitrary']) else 'CONFLICT_WITH_SPARSE_FLOOR',
            'status':status,
            'topology':'NOT_APPLIED_REQUIRES_EXPLICIT_ASSOCIATION'})
        accepted.append(result)
    return {'accepted':accepted,'rejected':rejected,
            'warning':'Same-ID clicks are triangulated and checked but are not automatically snapped to walls.'}


def solve_lines(fusion: dict, detections: dict) -> dict:
    """Associate wall-floor lines in common geometry; retain unresolved cases."""
    started = time.monotonic()
    if (detections.get('schema') != 'worldstate-image-structure-lines/0.1' or
        detections.get('source_reconstruction') != fusion.get('source_reconstruction') or
        detections.get('semantic_manifest_sha256') != fusion.get('semantic_manifest_sha256')):
        raise ValueError('二维线与三维融合输入不一致')
    basis = _floor_basis(fusion); origin, ex, ey, normal, offset = basis
    cameras = {c['image_id']: c for c in fusion['cameras']}
    lines = detections['lines']
    if any(l['image_id'] not in cameras or l['photo_sha256'] != cameras[l['image_id']]['sha256'] for l in lines):
        raise ValueError('线段引用了未注册照片')
    remaining = list(lines); groups = []; rejected = []
    for _ in range(8):
        candidates = []
        for line in remaining:
            a, b = (np.asarray(p) for p in line['floor_projected_relative']); v = b-a
            if np.linalg.norm(v) < 1e-8:
                continue
            n = np.array([-v[1], v[0]]) / np.linalg.norm(v)
            if n[0] < 0 or (n[0] == 0 and n[1] < 0): n = -n
            theta, distance = math.atan2(n[1], n[0]), float(n @ a)
            support = _support(theta, distance, remaining, cameras, basis)
            if len(support) >= 3:
                candidates.append((len(support), -sum(x[0] for x in support.values()), theta, distance, support))
        if not candidates:
            break
        _, _, theta, distance, support = max(candidates, key=lambda x: (x[0], x[1]))
        def objective(x, observations):
            values = []
            for _, line in observations.values():
                predicted = _image_line(x[0], x[1], cameras[line['image_id']], basis)
                if predicted is None:
                    return np.full(2*len(observations), 1e3)
                values.extend(float(predicted @ np.array([*p, 1.])) for p in line['points_px'])
            return values
        solution = least_squares(objective, [theta, distance], args=(support,), loss='soft_l1', f_scale=6, max_nfev=100)
        theta, distance = map(float, solution.x)
        support = _support(theta, distance, remaining, cameras, basis)
        if len(support) < 3:
            rejected.append({'reason': 'refinement_lost_multiview_support'}); break
        inliers = [line for line in remaining if _line_error(theta, distance, line, cameras, basis) <= line['pixel_tolerance']]
        remaining = [line for line in remaining if line not in inliers]
        try:
            free = _free_line(support, cameras)
        except ValueError as exc:
            rejected.append({'reason': str(exc), 'image_ids': sorted(support)}); continue
        direct_errors = {view:_free_line_error(free,item[1],cameras) for view,item in support.items()}
        holdout_errors = []; floor_holdout_errors = []
        for view,item in support.items():
            training={v:x for v,x in support.items() if v!=view}
            try:
                fitted = _free_line(training,cameras)
                error = _free_line_error(fitted,item[1],cameras)
                if math.isfinite(error):holdout_errors.append({'image_id':view,'error_px':error})
            except ValueError:
                pass
            fitted_floor=least_squares(objective,[theta,distance],args=(training,),loss='soft_l1',f_scale=6,max_nfev=100)
            error=_line_error(float(fitted_floor.x[0]),float(fitted_floor.x[1]),item[1],cameras,basis)
            if math.isfinite(error):
                floor_holdout_errors.append({'image_id':view,'error_px':error,'pixel_tolerance':item[1]['pixel_tolerance']})
        if not all(math.isfinite(x) for x in direct_errors.values()):
            rejected.append({'reason':'free_line_projection_degenerate','image_ids':sorted(support)});continue
        d3 = np.asarray(free['direction']); p3 = np.asarray(free['point'])
        floor_delta = float(normal @ p3 + offset)
        floor_tilt = math.degrees(math.asin(float(np.clip(abs(normal @ d3), 0, 1))))
        floor_rms = float(fusion['floor_planes'][0]['fit_rms_arbitrary'])
        identifier = hashlib.sha256('|'.join(sorted(l['id'] for l in inliers)).encode()).hexdigest()[:16]
        errors = [float(x[0]) for x in support.values()]
        intervals = _visible_intervals(theta, inliers)
        n2 = np.array([math.cos(theta), math.sin(theta)]); along = np.array([-n2[1], n2[0]])
        support_floor_residuals = []
        for interval in intervals:
            for endpoint in interval['range_relative']:
                uv = n2*distance + along*endpoint
                floor_point = origin + ex*uv[0] + ey*uv[1]
                nearest = p3 + d3*float((floor_point-p3) @ d3)
                support_floor_residuals.append(float(normal @ nearest + offset))
        consistent = (bool(support_floor_residuals) and max(map(abs, support_floor_residuals)) <= 3*floor_rms
                      and floor_tilt <= 5)
        groups.append({'id': 'structure-line-'+identifier, 'theta_rad': theta, 'offset_relative': distance,
            'free_line': free, 'floor_distance_at_closest_origin_relative': floor_delta,
            'floor_signed_distances_at_support_ends_relative': support_floor_residuals,
            'floor_inclination_deg': floor_tilt, 'floor_consistency': 'CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY' if consistent else 'CONFLICT_WITH_SPARSE_FLOOR',
            'floor_consistency_threshold_relative': 3*floor_rms, 'floor_inclination_threshold_deg': 5,
            'support_view_count': len(support), 'support_image_ids': sorted(support),
            'reprojection_max_per_view_px': [{'image_id': view, 'error_px': float(item[0])}
                                              for view, item in sorted(support.items())],
            'reprojection_median_px': float(np.median(errors)),
            'free_line_reprojection_max_per_view_px': [{'image_id':v,'error_px':e} for v,e in sorted(direct_errors.items())],
            'free_line_leave_one_view_out_px': holdout_errors,
            'floor_joint_leave_one_view_out_px': floor_holdout_errors,
            'floor_joint_holdout_status': 'CONSISTENT_UNVERIFIED' if len(floor_holdout_errors)==len(support) and len(holdout_errors)==len(support) and all(
                x['error_px']<=x['pixel_tolerance'] for x in floor_holdout_errors) else 'CONFLICT_OR_INSUFFICIENT',
            'leave_one_view_out_note': 'Fit excludes each view in turn, but initial association and camera poses used all views; not an independent accuracy evaluation.',
            'selected_observations': [x[1] for _, x in sorted(support.items())],
            'inlier_observations': inliers, 'visible_support_intervals': intervals,
            'status': 'CANDIDATE_UNVERIFIED',
            'unknown': ['physical wall instance', 'complete wall boundary', 'actual wall height', 'wall thickness',
                        'occlusion', 'geometry uncertainty', 'independent metric accuracy']})
    corners = []
    for left, right in itertools.combinations(groups, 2):
        angle = abs(math.sin(left['theta_rad']-right['theta_rad']))
        if angle < math.sin(math.radians(20)):
            continue
        observations = []
        for image_id, camera in cameras.items():
            a = [x for x in left['inlier_observations'] if x['image_id'] == image_id]
            b = [x for x in right['inlier_observations'] if x['image_id'] == image_id]
            possible = []
            for x, y in itertools.product(a, b):
                p, q = (np.array([*v, 1.]) for v in x['points_px'])
                r, s = (np.array([*v, 1.]) for v in y['points_px'])
                cross = np.cross(np.cross(p, q), np.cross(r, s))
                if abs(cross[2]) < 1e-10: continue
                pixel = cross[:2]/cross[2]
                dx = min(np.linalg.norm(pixel-np.asarray(v)) for v in x['points_px'])
                dy = min(np.linalg.norm(pixel-np.asarray(v)) for v in y['points_px'])
                if (dx <= 25 and dy <= 25 and 10 < pixel[0] < camera['width_px']-10 and
                        10 < pixel[1] < camera['height_px']-10):
                    possible.append((float(dx+dy), pixel, x, y))
            if possible:
                _, pixel, x, y = min(possible, key=lambda z:z[0])
                observations.append({'image_id': image_id, 'photo_sha256': camera['sha256'],
                    'pixel_xy': pixel.tolist(), 'source_line_ids': [x['id'], y['id']],
                    'status': 'INFERRED_IMAGE_LINE_INTERSECTION_NOT_MANUAL_CONFIRMATION'})
        if len(observations) < 2:
            continue
        tolerance = 2*max(math.ceil(math.hypot(cameras[o['image_id']]['width_px']/128,
                                                   cameras[o['image_id']]['height_px']/128))+1 for o in observations)
        try:
            result = triangulate_observations(fusion['cameras'], observations, max_reprojection_px=tolerance)
            floor_residual = abs(float(normal @ np.asarray(result['xyz'])+offset))
            result.update({'line_ids': [left['id'], right['id']], 'source_observations': observations,
                           'floor_plane_residual_relative': floor_residual,
                           'floor_consistency': 'CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY' if floor_residual <= 3*float(fusion['floor_planes'][0]['fit_rms_arbitrary']) else 'CONFLICT_WITH_SPARSE_FLOOR',
                           'status': 'TRIANGULATED_VISUAL_CORNER_CANDIDATE_NOT_INDEPENDENTLY_VERIFIED'})
            corners.append(result)
        except ValueError as exc:
            rejected.append({'reason': 'corner_triangulation: '+str(exc), 'line_ids': [left['id'], right['id']]})
    ambiguous = []
    for a, b in itertools.combinations(groups, 2):
        angle = math.degrees(math.acos(float(np.clip(abs(math.cos(a['theta_rad']-b['theta_rad'])), -1, 1))))
        if angle < 20:
            sign = 1 if math.cos(a['theta_rad']-b['theta_rad']) >= 0 else -1
            separation = abs(a['offset_relative']-sign*b['offset_relative'])
            shared_separation = _parallel_separation_over_shared_support(a,b)
            ambiguous.append({'line_ids': [a['id'], b['id']], 'angle_deg': angle,
                'offset_separation_relative': separation,
                'minimum_separation_over_shared_support_relative': shared_separation,
                'status': 'SEPARATED_PARALLEL_HYPOTHESES_NOT_CONFIRMED_WALLS' if shared_separation is not None and shared_separation > 6*float(fusion['floor_planes'][0]['fit_rms_arbitrary'])
                          else 'POSSIBLE_DUPLICATE_OR_NEARBY_DISTINCT_WALLS_REQUIRES_REVIEW'})
    return {'schema': 'worldstate-multiview-structure/0.1', 'status': 'UNVERIFIED_PARTIAL_CANDIDATES',
            'source_reconstruction': fusion['source_reconstruction'], 'semantic_manifest_sha256': fusion['semantic_manifest_sha256'],
            'floor_basis': {'origin': origin.tolist(), 'ex': ex.tolist(), 'ey': ey.tolist(),
                            'normal': normal.tolist(), 'offset': offset},
            'groups': groups, 'corner_candidates': corners, 'parallel_pairs_requiring_review': ambiguous,
            'remaining_line_ids': [x['id'] for x in remaining], 'rejected': rejected,
            'runtime_seconds': round(time.monotonic()-started, 3),
            'limitations': ['associations use a sparse semantic floor as a shared prior; this is a hybrid route',
                '2D boundaries and physical wall instances are not independently verified',
                'visible support intervals are not confirmed full wall boundaries',
                'reprojection and floor-fit residuals are not independent geometric accuracy',
                'no independent scale or construction dimensions are supplied']}


def build_structure_room(fusion: dict, structure: dict, anchor: dict, solution: dict,
                         selected_line_ids: list[str], *, project_id: str, height_m: float,
                         height_basis: str, height_description: str, thickness_m: float,
                         confirmed_candidates: bool, allow_assumed_scale: bool = False,
                         operator_kind: str = 'user', height_uncertainty_m: float | None = None) -> dict:
    """Turn selected real multiview lines into open Room IR using declared height.

    Only the longest interval with support from at least two views is exported
    per selected line. Image boundaries are not promoted to physical corners.
    """
    from .room_ir import SCHEMA, geometry_issues, quantity, validate_room
    if (structure.get('schema') != 'worldstate-multiview-structure/0.1' or
        structure.get('source_reconstruction') != fusion.get('source_reconstruction') or
        structure.get('semantic_manifest_sha256') != fusion.get('semantic_manifest_sha256')):
        raise ValueError('结构候选与当前多视图证据不一致')
    if confirmed_candidates is not True:
        raise ValueError('请确认已检查线段、遮挡和候选墙面')
    if operator_kind not in {'user', 'automation'}:
        raise ValueError('操作来源无效')
    if not isinstance(project_id,str) or not project_id.strip() or len(project_id)>120:
        raise ValueError('项目标识无效')
    if anchor.get('basis') != 'independent_user_declared' and allow_assumed_scale is not True:
        raise ValueError('非独立尺度必须明确允许，模型仍是草稿')
    for value, label in ((height_m, '墙高'), (thickness_m, '墙厚')):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=20:
            raise ValueError(label+'需要明确的正数输入')
    if thickness_m > 2:
        raise ValueError('假设墙厚超出有效范围')
    if height_basis not in {'assumed', 'user_measurement'} or not isinstance(height_description,str) or not height_description.strip():
        raise ValueError('请明确墙高来源和说明')
    if height_uncertainty_m is not None and (isinstance(height_uncertainty_m,bool) or
            not isinstance(height_uncertainty_m,(int,float)) or not math.isfinite(height_uncertainty_m) or height_uncertainty_m<=0):
        raise ValueError('墙高不确定性必须是正数')
    if height_basis == 'user_measurement' and height_uncertainty_m is None:
        raise ValueError('用户测量墙高需要记录测量不确定性')
    if not isinstance(selected_line_ids,list) or not selected_line_ids or len(selected_line_ids)!=len(set(selected_line_ids)):
        raise ValueError('请选择不重复的结构线候选')
    groups = {g['id']:g for g in structure['groups']}
    if any(i not in groups or groups[i]['floor_consistency']!='CONSISTENT_WITH_SPARSE_FLOOR_NOT_ACCURACY'
           or groups[i]['floor_joint_holdout_status']!='CONSISTENT_UNVERIFIED'
           or not groups[i]['visible_support_intervals'] for i in selected_line_ids):
        raise ValueError('所选线与地面或留出视图冲突，或缺少多视图可见范围')
    if any(set(pair['line_ids']) <= set(selected_line_ids) and pair['status'].startswith('POSSIBLE_DUPLICATE')
           for pair in structure['parallel_pairs_requiring_review']):
        raise ValueError('所选线可能重复或属于相近墙体，请先区分')
    scaled = apply_multiview_scale(fusion,anchor,solution)
    factor = float(solution['metres_per_sfm_unit'])
    frame = structure['floor_basis'];origin = np.asarray(frame['origin'])*factor
    ex=np.asarray(frame['ex'],float);ey=np.asarray(frame['ey'],float);up=np.asarray(fusion['floor_up'],float)

    def endpoints(group):
        interval = max(group['visible_support_intervals'],key=lambda x:x['range_relative'][1]-x['range_relative'][0])
        theta=group['theta_rad'];n=np.array([math.cos(theta),math.sin(theta)]);along=np.array([-n[1],n[0]])
        points=[]
        for value in interval['range_relative']:
            xy=n*group['offset_relative']+along*value
            points.append((np.asarray(frame['origin'])+ex*xy[0]+ey*xy[1])*factor)
        return points

    first=endpoints(groups[selected_line_ids[0]]);xaxis=first[1]-first[0]
    xaxis-=up*float(xaxis@up);length=float(np.linalg.norm(xaxis))
    if length<1e-7:raise ValueError('结构线长度退化')
    xaxis/=length;yaxis=np.cross(up,xaxis);yaxis/=np.linalg.norm(yaxis)
    def local(point):
        delta=point-origin
        return [float(delta@xaxis),float(delta@yaxis)]

    evidence=[{'id':'selection-structure','kind':'candidate_selection','operator':operator_kind,
               'status':'user_selection_unverified' if operator_kind=='user' else 'scripted_selection_not_human'},
              {'id':'cameras-structure','kind':'multiview_camera_reconstruction','registered_cameras':scaled['cameras'],
               'source_reconstruction':fusion['source_reconstruction'],'status':'inferred_unverified'},
              {'id':'floor-structure','kind':'multiview_semantic_floor','plane':scaled['floor_planes'][0],
               'status':'inferred_unverified'},
              {'id':'scale-structure','kind':'multiview_scale_anchor','anchor':anchor,'solution':scaled['scale_solution'],
               'status':'user_declared_unverified' if anchor['basis']=='independent_user_declared' else anchor['basis']},
              {'id':'height-structure','kind':'height_input','basis':height_basis,'value_m':height_m,
               'description':height_description,'measurement_uncertainty_m':height_uncertainty_m,
               'status':'assumed' if height_basis=='assumed' else 'user_declared_unverified'},
              {'id':'thickness-structure','kind':'user_assumption','value_m':thickness_m,
               'description':'Unobserved thickness is an explicit assumption'}]
    if structure.get('annotated_corners') is not None:
        evidence.append({'id':'annotated-corners-structure','kind':'multiview_corner_annotations',
                         'annotation_sha256':structure.get('corner_annotation_sha256'),
                         'results':structure['annotated_corners'],'status':'correspondence_unverified',
                         'note':'Annotations are evidence only; no wall connection or hidden topology is invented.'})
    for camera in scaled['cameras']:
        evidence.append({'id':'photo-'+camera['sha256'][:16],'kind':'image','sha256':camera['sha256'],
                         'width_px':camera['width_px'],'height_px':camera['height_px'],
                         'captured_at':'UNKNOWN','authorization':'user_supplied_unverified'})
    nodes=[];walls=[]
    for ident in selected_line_ids:
        group=groups[ident];ref='evidence-'+ident
        evidence.append({'id':ref,'kind':'multiview_wall_floor_line','line_id':ident,
            'status':'inferred_unverified','source_reconstruction':fusion['source_reconstruction'],
            'semantic_manifest_sha256':fusion['semantic_manifest_sha256'],
            'observations':group['inlier_observations'],'free_line_relative':group['free_line'],
            'support_intervals_relative':group['visible_support_intervals'],
            'floor_consistency':group['floor_consistency'],'floor_joint_holdout':group['floor_joint_leave_one_view_out_px'],
            'free_line_holdout':group['free_line_leave_one_view_out_px'],
            'corner_candidates':[c for c in structure['corner_candidates'] if ident in c['line_ids']]})
        start,end=endpoints(group);a,b=local(start),local(end)
        wall_id='wall-'+ident[len('structure-line-'):];refs=[ref,'floor-structure','scale-structure','cameras-structure']
        nodes.extend([{'id':wall_id+'-a','x':a[0],'y':a[1],'status':'inferred','evidence_refs':refs},
                      {'id':wall_id+'-b','x':b[0],'y':b[1],'status':'inferred','evidence_refs':refs}])
        walls.append({'id':wall_id,'ifc_type':'IfcWall','start':wall_id+'-a','end':wall_id+'-b','storey':'storey-1',
          'classification':{'status':'inferred','evidence_refs':[ref]},
          'parameters':{'height':quantity(height_m,'assumed' if height_basis=='assumed' else 'observed',
                                           ['height-structure'],height_description),
                        'thickness':quantity(thickness_m,'assumed',['thickness-structure'],'Unobserved thickness'),
                        'base_elevation':quantity(0,'inferred',['floor-structure'],'Unverified shared floor plane')},
          'unknown':['physical wall identity','full wall boundary','corner connectivity','occlusion',
                     'actual wall thickness','3D uncertainty','independent metric accuracy']})
    model={'schema':SCHEMA,'project_id':project_id,'mode':'assisted','revision':1,
      'coordinate_system':{'name':'floor-aligned local frame from scaled COLMAP','unit':'m','georeferencing':'UNKNOWN',
          'origin_in_scaled_colmap':origin.tolist(),'x_axis_in_colmap':xaxis.tolist(),
          'y_axis_in_colmap':yaxis.tolist(),'z_axis_in_colmap':up.tolist()},
      'evidence':evidence,'nodes':nodes,'storeys':[{'id':'storey-1','elevation':quantity(0,'assumed',['floor-structure'],'Local datum, not surveyed')}],
      'elements':walls,'constraints':[],
      'scale':{'status':'applied','independence':anchor['basis'],'anchor_ref':'scale-structure',
               'metres_per_relative_unit':factor,'binding_sha256':solution['binding_sha256']},
      'validation':{'status':'UNVERIFIED_DRAFT','scope':'PARTIAL_OPEN',
          'warning':'Line candidates and disconnected visible support only; dimensions, identities and corners require independent validation'}}
    validate_room(model);issues=geometry_issues(model)
    if issues:raise ValueError('几何冲突：'+', '.join(f"{x['id']}:{x['code']}" for x in issues))
    return model
