"""Run CPU SfM using same-scene, hash-pinned source-camera calibration.

Source poses are not used in the reconstruction or as independent truth. The
source sparse model is read only to associate each exact photo with its own
undistorted camera and raster dimensions. Source poses, points and scale must
not be treated as physically measured or independent validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pycolmap
from PIL import Image

from products.worldstate_bim.colmap_provider import reconstruct_uncalibrated_images


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_entries(manifest: Path, directory: Path) -> list[str]:
    data = json.loads(manifest.read_text())
    names = []
    for item in data['input_photos']:
        name = item['filename']
        if not isinstance(name, str) or Path(name).name != name or name in names:
            raise ValueError('invalid or duplicated input filename')
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError(f'missing or mismatched input: {name}')
        names.append(name)
    return names


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, required=True)
    parser.add_argument('--image-manifest', type=Path, required=True)
    parser.add_argument('--source-sparse', type=Path, required=True)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--max-image-size', type=int, default=1200,
                        help='Maximum image dimension for CPU SIFT; larger settings cost more resources')
    args = parser.parse_args()
    names = verified_entries(args.image_manifest, args.images)
    source_names = verified_entries(args.source_manifest, args.source_sparse)
    if set(source_names) != {'cameras.bin', 'images.bin', 'points3D.bin'}:
        raise ValueError('source sparse files are incomplete')
    source = pycolmap.Reconstruction(str(args.source_sparse))
    source_images = {image.name: image for image in source.images.values()}
    if any(name not in source_images for name in names):
        raise ValueError('an image does not belong to the supplied source reconstruction')
    camera_ids = {source_images[name].camera_id for name in names}
    if len(camera_ids) != 1:
        raise ValueError('input images do not all share the same source camera')
    camera_id = next(iter(camera_ids))
    camera = source.cameras[camera_id]
    if camera.model_name == 'SIMPLE_PINHOLE':
        f, cx, cy = map(float, camera.params)
        fx = fy = f
    elif camera.model_name == 'PINHOLE':
        fx, fy, cx, cy = map(float, camera.params)
    else:
        raise ValueError('only undistorted pinhole source images are supported')
    with Image.open(args.images / names[0]) as image:
        width, height = image.size
    sx, sy = width / camera.width, height / camera.height
    calibration = {'fx': fx*sx, 'fy': fy*sy, 'cx': cx*sx, 'cy': cy*sy,
                   'confirmed': True, 'source_sha256': digest(args.source_sparse / 'cameras.bin'),
                   'source': 'Matching source image/camera mapping and undistorted pinhole calibration, resized to this photo raster; not independent validation'}
    result = reconstruct_uncalibrated_images(args.images, names, args.output, threads=args.threads,
                                             calibration=calibration, max_image_size=args.max_image_size)
    result['input_selection'] = 'Exact hash-pinned development image manifest; no hidden evaluation data'
    result['source_image_camera_map_sha256'] = digest(args.source_sparse / 'images.bin')
    result['source_camera_original'] = {'id': camera_id, 'model': camera.model_name,
        'width': camera.width, 'height': camera.height, 'params': camera.params.tolist(),
        'resized_width': width, 'resized_height': height}
    result['limitations'].append('The same-scene source calibration is an input, not independent truth or physical scale')
    (args.output / 'geometry.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': result['status'], 'input_images': len(names),
        'registered_images': len(result['registered_cameras']), 'sparse_points': result['sparse_points'],
        'mean_reprojection_error_px': result.get('mean_reprojection_error_px'),
        'timing_seconds': result['timing_seconds']}, indent=2))


if __name__ == '__main__':
    main()
