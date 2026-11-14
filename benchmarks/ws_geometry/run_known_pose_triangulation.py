"""Triangulate selected photos using correlated, precomputed same-scene poses.

This development fallback uses extra pose inputs from the public source
reconstruction. It is NOT camera registration from only the selected photos,
independent metric scale, or independent reconstruction accuracy.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import pycolmap

from benchmarks.ws_geometry.run_same_scene_sfm import digest, verified_entries


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sfm-output', type=Path, required=True)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--image-manifest', type=Path, required=True)
    p.add_argument('--source-sparse', type=Path, required=True)
    p.add_argument('--source-manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('choose a new output directory')
    names = verified_entries(args.image_manifest, args.images)
    if set(verified_entries(args.source_manifest, args.source_sparse)) != {'cameras.bin', 'images.bin', 'points3D.bin'}:
        raise ValueError('source reconstruction is incomplete')
    geometry = json.loads((args.sfm_output / 'geometry.json').read_text())
    if {x['file']: x['sha256'] for x in geometry['inputs']} != {name: digest(args.images / name) for name in names}:
        raise ValueError('COLMAP database and image manifest have different inputs')
    if geometry.get('source_image_camera_map_sha256') != digest(args.source_sparse / 'images.bin'):
        raise ValueError('source image/camera mapping changed')
    if geometry['supplied_calibration']['source_sha256'] != digest(args.source_sparse / 'cameras.bin'):
        raise ValueError('source camera calibration changed')
    source = pycolmap.Reconstruction(str(args.source_sparse))
    source_images = {image.name: image for image in source.images.values()}
    if any(name not in source_images or not source_images[name].has_pose for name in names):
        raise ValueError('missing matching source pose')
    if {source_images[name].camera_id for name in names} != {geometry['source_camera_original']['id']}:
        raise ValueError('source pose camera does not match supplied calibration')
    with pycolmap.Database.open(args.sfm_output / 'database.db') as database:
        images, cameras = database.read_all_images(), database.read_all_cameras()
    if len(cameras) != 1 or {image.name for image in images} != set(names):
        raise ValueError('COLMAP database does not match manifest')
    calibration = geometry['supplied_calibration']
    expected = [calibration[k] for k in ('fx', 'fy', 'cx', 'cy')]
    source_camera = source.cameras[geometry['source_camera_original']['id']]
    if source_camera.model_name == 'SIMPLE_PINHOLE':
        focal, cx, cy = map(float, source_camera.params)
        fx = fy = focal
    elif source_camera.model_name == 'PINHOLE':
        fx, fy, cx, cy = map(float, source_camera.params)
    else:
        raise ValueError('source camera is not an undistorted pinhole')
    sx, sy = cameras[0].width/source_camera.width, cameras[0].height/source_camera.height
    source_scaled = [fx*sx, fy*sy, cx*sx, cy*sy]
    if (cameras[0].model_name != 'PINHOLE' or len(cameras[0].params) != 4
            or any(not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
                   for a, b in zip(expected, source_scaled))
            or any(not math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
                   for a, b in zip(cameras[0].params, expected))):
        raise ValueError('database camera does not match verified source calibration')
    initial = pycolmap.Reconstruction()
    initial.add_camera_with_trivial_rig(cameras[0])
    for image in images:
        initial.add_image_with_trivial_frame(pycolmap.Image(name=image.name, image_id=image.image_id,
                    camera_id=image.camera_id), source_images[image.name].cam_from_world())
    args.output.mkdir(parents=True)
    started = time.monotonic()
    result = pycolmap.triangulate_points(initial, args.sfm_output / 'database.db', args.images,
                                        args.output, clear_points=True, refine_intrinsics=False)
    elapsed = time.monotonic() - started
    if result.num_reg_images() != len(names):
        raise ValueError('triangulation did not retain every supplied camera pose')
    max_center_delta = max(float(sum((float(x)-float(y))**2 for x,y in
                 zip(image.projection_center(), source_images[image.name].projection_center()))**0.5)
                 for image in result.images.values())
    max_rotation_delta = max(float(sum((float(a)-float(b))**2 for row_a, row_b in
                 zip(image.cam_from_world().rotation.matrix(), source_images[image.name].cam_from_world().rotation.matrix())
                 for a, b in zip(row_a, row_b))**0.5) for image in result.images.values())
    summary = {'schema': 'worldstate-correlated-pose-triangulation/0.1',
        'status': 'DEVELOPMENT_DIAGNOSTIC_NOT_AUTOMATIC_REGISTRATION',
        'extra_input': 'Precomputed poses from the same scene source reconstruction; source poses are correlated and not independent truth',
        'source_registered_images': source.num_reg_images(),
        'source_images_sha256': digest(args.source_sparse / 'images.bin'),
        'source_camera_sha256': digest(args.source_sparse / 'cameras.bin'),
        'input_images': len(names), 'registered_poses_supplied': result.num_reg_images(),
        'triangulated_points': result.num_points3D(),
        'mean_reprojection_error_px': result.compute_mean_reprojection_error() if result.num_points3D() else None,
        'max_camera_center_change_source_units': max_center_delta,
        'max_camera_rotation_matrix_change_frobenius': max_rotation_delta,
        'triangulation_seconds': elapsed, 'scale': 'SOURCE_FRAME_UNVERIFIED_NOT_INDEPENDENT_MEASUREMENT',
        'limits': ['Source points were not used; poses, matching and intrinsics are not independent.',
                   'Neither reprojection error nor precomputed source pose establishes physical wall precision.',
                   'This run is development only; no independent room accuracy or human time measured.']}
    (args.output / 'known-pose-summary.json').write_text(json.dumps(summary, indent=2, allow_nan=False)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
