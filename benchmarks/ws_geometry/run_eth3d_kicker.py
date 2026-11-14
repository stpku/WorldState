"""Prepare ETH3D kicker, then run photo-only CPU reconstruction.

The two fixed held-out images go to a separate reference directory. Preparation
reads only RGB images and intrinsics; it never opens scanner data, source poses,
or source point tracks. All raw data and outputs stay outside the repository.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
from PIL import Image
from products.worldstate_bim.colmap_provider import reconstruct_uncalibrated_images

HOLDOUT = {'DSC_6519.JPG', 'DSC_6520.JPG'}


def sha(path: Path) -> str:
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(images: Path, cameras: Path, output: Path) -> None:
    if output.exists(): raise FileExistsError('choose a new output directory')
    paths = sorted(images.glob('*.JPG'))
    if len(paths) != 31 or not HOLDOUT.issubset({p.name for p in paths}): raise ValueError('unexpected kicker images')
    lines = [line.split() for line in cameras.read_text().splitlines() if line.strip() and not line.startswith('#')]
    if len(lines) != 1 or len(lines[0]) != 8 or lines[0][1] != 'PINHOLE': raise ValueError('unsupported calibration')
    _, model, w, h, fx, fy, cx, cy = lines[0]; w = int(w); h = int(h)
    calibration = {'model':model, 'width':w, 'height':h, 'fx':float(fx), 'fy':float(fy), 'cx':float(cx), 'cy':float(cy),
        'source_sha256':sha(cameras), 'source':'ETH3D kicker undistorted cameras.txt; intrinsics only', 'confirmed':True}
    for path in paths:
        if path.is_symlink(): raise ValueError('source image is a symlink')
        with Image.open(path) as image:
            if image.size != (w,h) or image.getexif().get(274,1) != 1: raise ValueError('image calibration mismatch: '+path.name)
    inputs=output/'input'/'photos'; held=output/'reference'/'heldout-photos'; inputs.mkdir(parents=True); held.mkdir(parents=True)
    records=[]; held_records=[]
    for path in paths:
        record={'file':path.name,'sha256':sha(path),'bytes':path.stat().st_size}
        if path.name in HOLDOUT: shutil.copy2(path,held/path.name); held_records.append(record)
        else: shutil.copy2(path,inputs/path.name); records.append(record)
    manifest={'schema':'worldstate-eth3d-kicker-photo-input/0.1', 'dataset':'ETH3D kicker development',
        'license':'CC BY-NC-SA 4.0; non-commercial research only', 'source':'https://www.eth3d.net/datasets',
        'modeling_images':records, 'camera_calibration':calibration, 'scale':'UNKNOWN',
        'reference_policy':'No scan, source pose, source tracks, or held-out photo is a photo-only input.'}
    (output/'input'/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (output/'reference'/'heldout-manifest.json').write_text(json.dumps({'schema':'worldstate-eth3d-kicker-holdout/0.1',
        'images':held_records,'note':'Development holdout; not WS-RealRoom acceptance.'},indent=2)+'\n')
    print(json.dumps({'modeling_photos':len(records),'heldout_photos':len(held_records),'scale':'UNKNOWN'},indent=2))


def reconstruct(input_dir: Path, output: Path, threads: int, max_image_size: int) -> None:
    manifest=json.loads((input_dir/'manifest.json').read_text()); images=input_dir/'photos'
    if manifest.get('schema')!='worldstate-eth3d-kicker-photo-input/0.1' or manifest.get('scale')!='UNKNOWN':
        raise ValueError('unexpected modeling manifest')
    names=[]
    for item in manifest['modeling_images']:
        name=item['file'];path=images/name
        if Path(name).name!=name or name in names or path.is_symlink() or not path.is_file() or sha(path)!=item['sha256'] or path.stat().st_size!=item['bytes']:
            raise ValueError('invalid photo or input hash')
        names.append(name)
    c=manifest['camera_calibration']
    if c['model']!='PINHOLE':raise ValueError('only PINHOLE intrinsics are supported')
    calibration={k:c[k] for k in ('fx','fy','cx','cy','source','source_sha256','confirmed')}
    result=reconstruct_uncalibrated_images(images,names,output,threads=threads,calibration=calibration,max_image_size=max_image_size)
    result['input_mode']='PHOTO_ONLY_INTRINSICS_ALLOWED_NO_REFERENCE_POSES_OR_SCAN'
    result['dataset_license']='CC BY-NC-SA 4.0; non-commercial development'
    (output/'geometry.json').write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'mode':result['input_mode'],'status':result['status'],'input_photos':len(names),
        'registered_photos':len(result['registered_cameras']),'sparse_points':result['sparse_points'],
        'mean_reprojection_error_px':result.get('mean_reprojection_error_px'),'scale':result['scale'],
        'timing_seconds':result['timing_seconds']},indent=2))


def known_pose(input_dir: Path, sfm: Path, poses: Path, cameras: Path, output: Path, selection: Path | None) -> None:
    """Run the existing fixed-pose solver and correct its office-only label.

    The shared solver's count and selected photos are correct, but its human
    readable feature-database note is hardcoded to 24 (the office input size).
    Keep its solver unchanged, and record this metadata correction explicitly.
    """
    from benchmarks.ws_geometry import run_eth3d_known_pose
    manifest=json.loads((input_dir/'manifest.json').read_text())
    if manifest.get('schema')!='worldstate-eth3d-kicker-photo-input/0.1':raise ValueError('unexpected kicker input')
    previous=sys.argv
    try:
        sys.argv=['run_eth3d_known_pose.py','--input',str(input_dir),'--sfm',str(sfm),'--source-poses',str(poses),
                  '--source-cameras',str(cameras),'--output',str(output)]
        if selection is not None:sys.argv.extend(['--selection',str(selection)])
        with contextlib.redirect_stdout(io.StringIO()):run_eth3d_known_pose.main()
    finally:sys.argv=previous
    path=output/'known-pose-summary.json';summary=json.loads(path.read_text());count=len(manifest['modeling_images'])
    selected=count if selection is None else len(json.loads(selection.read_text())['photos'])
    if summary['input_photos']!=selected or len(summary['selected_photos'])!=selected:
        raise ValueError('fixed-pose result differs from declared inputs')
    summary['feature_database_scope']=(f'All {count} inputs; only selected registered cameras and their pairwise '
                                       'matches enter this triangulation.')
    summary['metadata_correction']='Shared solver hardcodes 24 in this text field; corrected to the verified input count.'
    path.write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:summary[k] for k in ('input_photos','supplied_camera_poses','triangulated_points',
        'mean_reprojection_error_px','max_pose_matrix_difference','triangulation_seconds','metadata_correction')},indent=2))


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--images',type=Path,required=True);a.add_argument('--cameras',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    b=sub.add_parser('reconstruct');b.add_argument('--input',type=Path,required=True);b.add_argument('--output',type=Path,required=True);b.add_argument('--threads',type=int,default=4);b.add_argument('--max-image-size',type=int,default=1600)
    c=sub.add_parser('known-pose');c.add_argument('--input',type=Path,required=True);c.add_argument('--sfm',type=Path,required=True);c.add_argument('--poses',type=Path,required=True);c.add_argument('--cameras',type=Path,required=True);c.add_argument('--selection',type=Path);c.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.command=='prepare':prepare(args.images,args.cameras,args.output)
    elif args.command=='reconstruct':reconstruct(args.input,args.output,args.threads,args.max_image_size)
    else:known_pose(args.input,args.sfm,args.poses,args.cameras,args.output,args.selection)


if __name__=='__main__': main()
