"""Export registered COLMAP cameras and photo hashes for local Studio import."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pycolmap


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reconstruction',type=Path,required=True);p.add_argument('--images',type=Path,required=True)
    p.add_argument('--camera-mode',choices=('known-pose','photo-only'),required=True)
    p.add_argument('--include-tracks',action='store_true',help='Include unconfirmed COLMAP pixel correspondences as suggestions')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output')
    reconstruction=pycolmap.Reconstruction(a.reconstruction);cameras=[]
    for ident in sorted(reconstruction.reg_image_ids()):
        image=reconstruction.image(ident);name=image.name;path=a.images/name
        if Path(name).name!=name or path.is_symlink() or not path.is_file():raise ValueError('source image missing or unsafe')
        camera=image.camera;pose=image.cam_from_world()
        cameras.append({'image_id':ident,'photo':name,'sha256':sha(path),'width_px':camera.width,'height_px':camera.height,
            'camera_model':camera.model_name,'intrinsics':camera.params.tolist(),
            'rotation_camera_from_world':pose.rotation.matrix().tolist(),'translation_camera_from_world':pose.translation.tolist(),
            'registration_status':'REGISTERED_NOT_INDEPENDENTLY_VERIFIED'})
    if len(cameras)<2:raise ValueError('at least two registered photos required')
    result={'schema':'worldstate-modeler-cameras/0.1','camera_mode':a.camera_mode,
        'source_reconstruction':[{'file':p.name,'sha256':sha(p)} for p in sorted(a.reconstruction.glob('*.bin'))],
        'cameras':cameras,'warning':'Camera and image identity is bound by hash; registration and physical scale remain unverified.'}
    if a.include_tracks:
        tracks=[];registered={c['image_id'] for c in cameras}
        for ident,point in reconstruction.points3D.items():
            if point.error>3.:continue
            observations=[]
            for entry in point.track.elements:
                if entry.image_id not in registered:continue
                xy=reconstruction.image(entry.image_id).points2D[entry.point2D_idx].xy
                observations.append({'image_id':entry.image_id,'pixel_xy':xy.tolist()})
            if len({o['image_id'] for o in observations})>=2:
                tracks.append({'id':int(ident),'observations':observations,'status':'UNVERIFIED_COLMAP_TRACK'})
        if len(tracks)>20000:raise ValueError('track manifest exceeds 20000 candidates')
        result['tracks']=tracks
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x') as stream:json.dump(result,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'registered':len(cameras),'output':str(a.output)}))


if __name__=='__main__':main()
