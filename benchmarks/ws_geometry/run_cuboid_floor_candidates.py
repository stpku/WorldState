"""Project real registered floor masks onto unconfirmed PixCuboid faces."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
import pycolmap
from products.worldstate_bim.floor_candidates import cuboid_floor_candidates


def sha(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate', type=Path, required=True); p.add_argument('--reconstruction', type=Path, required=True)
    p.add_argument('--mask-dir', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists(): raise FileExistsError('choose a new output')
    candidate = json.loads(a.candidate.read_text()); manifest = json.loads((a.mask_dir / 'manifest.json').read_text())
    if candidate['schema'] != 'worldstate-pixcuboid-candidate/0.1': raise ValueError('unknown candidate schema')
    for f in candidate['source_reconstruction']:
        if Path(f['file']).name != f['file'] or sha(a.reconstruction / f['file']) != f['sha256']:
            raise ValueError('candidate camera reconstruction changed')
    photos = {x['file']: x['sha256'] for x in candidate['photos']}
    records = {x['name']: x for x in manifest['images'] if x['name'] in photos}
    if set(records) != set(photos): raise ValueError('missing registered semantic image')
    reconstruction = pycolmap.Reconstruction(a.reconstruction); images = {i.name: i for i in reconstruction.images.values()}
    views = []
    for name, digest in photos.items():
        record = records[name]; mask_path = a.mask_dir / record['mask_file']
        if record['sha256'] != digest or Path(record['mask_file']).name != record['mask_file'] or sha(mask_path) != record['mask_sha256']:
            raise ValueError('semantic image or mask changed')
        image = images[name]; pose = image.cam_from_world(); camera = reconstruction.cameras[image.camera_id]
        if camera.model_name != 'PINHOLE': raise ValueError('only PINHOLE cameras are currently supported')
        fx, fy, cx, cy = camera.params
        with np.load(mask_path, allow_pickle=False) as mask:
            views.append({'name': name, 'image_sha256': digest, 'registered': image.has_pose,
                'intrinsics': [[fx, 0, cx], [0, fy, cy], [0, 0, 1]], 'camera_from_world': pose.rotation.matrix(),
                'camera_center': image.projection_center(), 'width': record['width_px'], 'height': record['height_px'],
                'labels': mask['labels'].copy(), 'confidence': mask['confidence'].copy()})
    out = cuboid_floor_candidates(candidate['output']['R_world_to_cuboid'], candidate['output']['plane_offsets'], views)
    out['candidate_sha256'] = sha(a.candidate); out['semantic_manifest_sha256'] = sha(a.mask_dir / 'manifest.json')
    out['coordinate_frame'] = 'provided camera frame; units and scale inherited from source'
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x') as stream: json.dump(out, stream, indent=2, allow_nan=False); stream.write('\n')
    print(json.dumps({'state': out['state'], 'faces': [{'face': f['face'], 'views': len(f['support_views']),
          'pixels': f['sampled_floor_pixels']} for f in out['candidates']]}, indent=2))


if __name__ == '__main__': main()
