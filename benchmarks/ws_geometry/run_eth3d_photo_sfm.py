"""Run ETH3D photo-only CPU SfM with intrinsics but no reference poses/scans."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from products.worldstate_bim.colmap_provider import reconstruct_uncalibrated_images


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--max-image-size',type=int,default=1600);p.add_argument('--threads',type=int,default=4)
    a=p.parse_args();manifest=json.loads((a.input/'manifest.json').read_text());images=a.input/'photos'
    if manifest.get('schema')!='worldstate-eth3d-office-photo-input/0.1' or manifest.get('scale')!='UNKNOWN':
        raise ValueError('invalid photo-only input manifest')
    names=[]
    for item in manifest['modeling_images']:
        name=item['file'];path=images/name
        if Path(name).name!=name or name in names or path.is_symlink() or not path.is_file():raise ValueError('invalid source image')
        with path.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
        if sha!=item['sha256'] or path.stat().st_size!=item['bytes']:raise ValueError('input image hash mismatch')
        names.append(name)
    c=manifest['camera_calibration']
    if c.get('model')!='PINHOLE':raise ValueError('only declared PINHOLE calibration is supported')
    calibration={k:c[k] for k in ('fx','fy','cx','cy','source','source_sha256','confirmed')}
    result=reconstruct_uncalibrated_images(images,names,a.output,threads=a.threads,calibration=calibration,
                                            max_image_size=a.max_image_size)
    result['input_mode']='PHOTO_ONLY_INTRINSICS_ALLOWED_NO_REFERENCE_POSES_OR_SCAN'
    result['dataset_license']='CC BY-NC-SA 4.0; non-commercial development'
    (a.output/'geometry.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'mode':result['input_mode'],'status':result['status'],'input_photos':len(names),
        'registered_photos':len(result['registered_cameras']),'sparse_points':result['sparse_points'],
        'mean_reprojection_error_px':result.get('mean_reprojection_error_px'),
        'scale':result['scale'],'timing_seconds':result['timing_seconds']},indent=2))


if __name__=='__main__':main()
