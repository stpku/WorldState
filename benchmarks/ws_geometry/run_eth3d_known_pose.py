"""Triangulate the same ETH3D photos with provided camera poses, not SfM.

Reads official images.txt pose headers only and discards its feature tracks;
no laser scan is read. Camera poses are additional data and correlated with the
source scan registration, not independent camera/scale accuracy.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import time
from pathlib import Path
import pycolmap


def sha(path: Path) -> str:
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def read_poses(path: Path) -> dict:
    result={}
    with path.open() as stream:
        while True:
            line=stream.readline()
            if not line:break
            if not line.strip() or line.startswith('#'):continue
            parts=line.split(maxsplit=9)
            if len(parts)!=10:raise ValueError('invalid COLMAP image-pose header')
            _,qw,qx,qy,qz,tx,ty,tz,camera_id,name=parts
            name=Path(name.strip()).name
            if name in result:raise ValueError('duplicate source photo')
            result[name]={'camera_id':int(camera_id),'quat_xyzw':[float(qx),float(qy),float(qz),float(qw)],
                          'translation':[float(tx),float(ty),float(tz)]}
            if stream.readline()=='':raise ValueError('missing COLMAP observation line')
    return result


def rigid_pose(pose: dict) -> pycolmap.Rigid3d:
    # ETH3D's text quaternions are rounded; normalize before comparison with
    # COLMAP's normalized in-memory representation.
    quat=pose['quat_xyzw'];length=math.sqrt(sum(x*x for x in quat))
    if not math.isfinite(length) or length<1e-12:raise ValueError('invalid source quaternion')
    return pycolmap.Rigid3d(pycolmap.Rotation3d([x/length for x in quat]),pose['translation'])


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--sfm',type=Path,required=True)
    p.add_argument('--source-poses',type=Path,required=True);p.add_argument('--source-cameras',type=Path,required=True)
    p.add_argument('--selection',type=Path,help='Optional PixCuboid result selecting the same named and hashed photos')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    m=json.loads((a.input/'manifest.json').read_text());geometry=json.loads((a.sfm/'geometry.json').read_text())
    if geometry.get('input_mode')!='PHOTO_ONLY_INTRINSICS_ALLOWED_NO_REFERENCE_POSES_OR_SCAN':raise ValueError('not a photo-only source run')
    all_names={x['file']:x['sha256'] for x in m['modeling_images']}
    if all_names!={x['file']:x['sha256'] for x in geometry['inputs']}:raise ValueError('photo-only inputs differ')
    names=all_names
    if a.selection is not None:
        selection=json.loads(a.selection.read_text())
        if selection.get('schema')!='worldstate-pixcuboid-candidate/0.1' or selection.get('input_mode')!='KNOWN_POSE_ADDITIONAL_REFERENCE_POSES':
            raise ValueError('unexpected selection source')
        names={x['file']:x['sha256'] for x in selection['photos']}
        if len(names)<3 or any(all_names.get(name)!=digest for name,digest in names.items()):
            raise ValueError('selected photos do not match the modeling inputs')
    if sha(a.source_cameras)!=m['camera_calibration']['source_sha256']:raise ValueError('source calibration hash mismatch')
    for name,digest in names.items():
        path=a.input/'photos'/name
        if Path(name).name!=name or path.is_symlink() or not path.is_file() or sha(path)!=digest:raise ValueError('input photo hash mismatch')
    poses=read_poses(a.source_poses)
    if not set(names)<=set(poses) or {poses[x]['camera_id'] for x in names}!={0}:raise ValueError('source poses do not match the one input camera')
    with pycolmap.Database.open(a.sfm/'database.db') as db:
        images=db.read_all_images();cameras=db.read_all_cameras()
    if len(cameras)!=1 or {im.name for im in images}!=set(all_names):raise ValueError('feature database differs from input')
    images=[im for im in images if im.name in names]
    expected=[m['camera_calibration'][k] for k in ('fx','fy','cx','cy')]
    if cameras[0].model_name!='PINHOLE' or any(abs(float(x)-float(y))>1e-8 for x,y in zip(cameras[0].params,expected)):
        raise ValueError('database calibration differs from input')
    initial=pycolmap.Reconstruction();initial.add_camera_with_trivial_rig(cameras[0])
    for image in images:
        pose=poses[image.name];rigid=rigid_pose(pose)
        initial.add_image_with_trivial_frame(pycolmap.Image(name=image.name,image_id=image.image_id,camera_id=image.camera_id),rigid)
    a.output.mkdir(parents=True);start=time.monotonic()
    options=pycolmap.IncrementalPipelineOptions()
    options.mapper.fix_existing_frames=True
    options.ba_refine_sensor_from_rig=False
    result=pycolmap.triangulate_points(initial,a.sfm/'database.db',a.input/'photos',a.output,
        clear_points=True,refine_intrinsics=False,options=options)
    if result.num_reg_images()!=len(names):raise ValueError('known pose triangulation lost an input camera')
    max_pose_delta=0.
    for image in result.images.values():
        expected_pose=rigid_pose(poses[image.name])
        delta=abs(image.cam_from_world().matrix()-expected_pose.matrix()).max()
        max_pose_delta=max(max_pose_delta,float(delta))
    if max_pose_delta>1e-7:raise ValueError('triangulation modified an official input pose')
    summary={'schema':'worldstate-eth3d-known-pose/0.1','mode':'KNOWN_POSE_ADDITIONAL_REFERENCE_POSES',
        'status':'UNVERIFIED_DEVELOPMENT_CANDIDATE','input_photos':len(names),'supplied_camera_poses':result.num_reg_images(),
        'triangulated_points':result.num_points3D(),'mean_reprojection_error_px':result.compute_mean_reprojection_error() if result.num_points3D() else None,
        'source_pose_sha256':sha(a.source_poses),'source_camera_sha256':sha(a.source_cameras),
        'coordinate_frame':'ETH3D official global frame; scanner-registered poses; metric convention not independent verification',
        'max_pose_matrix_difference':max_pose_delta,'fixed_existing_frames':True,
        'triangulation_seconds':round(time.monotonic()-start,3),
        'selected_photos':[{'file':name,'sha256':names[name]} for name in sorted(names)],
        'feature_database_scope':'All 24 inputs; only the selected registered cameras and their pairwise matches enter this triangulation.',
        'limitations':['Provided source poses are additional inputs; not automatic camera recovery.',
            'Source pose and scan registration are correlated; no claim of independent camera or metric-scale error.',
            'Source feature tracks and source point cloud were not used; matching database comes from the same photo-only run.']}
    (a.output/'known-pose-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
