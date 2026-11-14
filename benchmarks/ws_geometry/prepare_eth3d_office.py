"""Prepare ETH3D office development photos without exposing reference poses/scans.

The output is outside the repository. The two held-out photographs are placed
in a separate directory and are not referenced by the modeling input manifest.
The source camera file supplies intrinsics only; no images.txt, points3D.txt,
scan, or reference pose is read by this script.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image

HOLDOUT = ('DSC_0254.JPG', 'DSC_0255.JPG')


def digest(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images', type=Path, required=True)
    p.add_argument('--cameras', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    paths = sorted(a.images.glob('*.JPG'))
    if len(paths) != 26 or not all((a.images/name).is_file() for name in HOLDOUT):
        raise ValueError('expected 26 ETH3D office photographs and the fixed holdouts')
    lines = [line.split() for line in a.cameras.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if len(lines) != 1 or lines[0][1] != 'PINHOLE' or len(lines[0]) != 8:
        raise ValueError('expected one PINHOLE source calibration')
    _, model, width, height, fx, fy, cx, cy = lines[0]
    width,height=int(width),int(height)
    calibration={'model':model,'width':width,'height':height,'fx':float(fx),'fy':float(fy),
        'cx':float(cx),'cy':float(cy),'source_sha256':digest(a.cameras),
        'source':'ETH3D office undistorted cameras.txt, intrinsics only; no source camera poses', 'confirmed':True}
    for path in paths:
        if path.is_symlink():raise ValueError('source image cannot be a symlink')
        with Image.open(path) as image:
            if image.size != (width,height) or image.getexif().get(274,1)!=1:
                raise ValueError(f'image dimensions or orientation do not match calibration: {path.name}')
    a.output.mkdir(parents=True);inputs=a.output/'input'/'photos';held=a.output/'reference'/'heldout-photos'
    inputs.mkdir(parents=True);held.mkdir(parents=True)
    records=[];held_records=[]
    for path in paths:
        item={'file':path.name,'sha256':digest(path),'bytes':path.stat().st_size}
        if path.name in HOLDOUT:
            shutil.copy2(path,held/path.name);held_records.append(item)
        else:
            shutil.copy2(path,inputs/path.name);records.append(item)
    manifest={'schema':'worldstate-eth3d-office-photo-input/0.1','dataset':'ETH3D office, non-commercial development',
        'license':'CC BY-NC-SA 4.0; research only','source':'https://www.eth3d.net/datasets',
        'modeling_images':records,'camera_calibration':calibration,'scale':'UNKNOWN',
        'reference_policy':'No scan, source camera pose, held-out image or wall reference is a photo-only modeling input.'}
    reference={'schema':'worldstate-eth3d-office-holdout/0.1','images':held_records,
               'note':'Held-out images; not a WS-RealRoom formal acceptance set.'}
    (a.output/'input'/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (a.output/'reference'/'heldout-manifest.json').write_text(json.dumps(reference,indent=2)+'\n')
    print(json.dumps({'modeling_photos':len(records),'heldout_photos':len(held_records),
                      'scale':'UNKNOWN','calibration_source_sha256':calibration['source_sha256']},indent=2))


if __name__ == '__main__':main()
