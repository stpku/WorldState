"""Overlay an unverified PixCuboid result on its real source photographs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import pycolmap

EDGES=((0,1),(0,2),(0,4),(1,3),(1,5),(2,3),(2,6),(3,7),(4,5),(4,6),(5,7),(6,7))


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prediction',type=Path,required=True);p.add_argument('--sparse',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    prediction=json.loads(a.prediction.read_text());reconstruction=pycolmap.Reconstruction(str(a.sparse))
    if prediction.get('schema')!='worldstate-pixcuboid-candidate/0.1':raise ValueError('unexpected prediction')
    def sha(path):
        with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
    if [{'file':path.name,'sha256':sha(path)} for path in sorted(a.sparse.glob('*.bin'))] != prediction['source_reconstruction']:
        raise ValueError('camera reconstruction hash mismatch')
    cameras={im.name:im for im in reconstruction.images.values()};corners=np.asarray(prediction['output']['corners_world'],float)
    if corners.shape!=(8,3) or not np.isfinite(corners).all():raise ValueError('invalid cuboid corners')
    a.output.mkdir(parents=True)
    for entry in prediction['photos']:
        name=entry['file'];source=a.images/name
        if Path(name).name!=name or source.is_symlink() or not source.is_file() or sha(source)!=entry['sha256']:
            raise ValueError('photo hash mismatch')
        image=cameras[name];camera=image.camera;transform=image.cam_from_world()
        xyz=(transform.rotation.matrix()@corners.T).T+transform.translation
        raw=cv2.imread(str(source))
        if raw is None or raw.shape[:2]!=(camera.height,camera.width):raise ValueError('photo size does not match camera')
        height,width=raw.shape[:2];scale=1200/width
        preview=cv2.resize(raw,(1200,round(height*scale)));h,w=preview.shape[:2];count=0
        for i,j in EDGES:
            first,last=xyz[i].copy(),xyz[j].copy();near=.02
            if first[2]<=near and last[2]<=near:continue
            if first[2]<=near:first=first+(last-first)*((near-first[2])/(last[2]-first[2]))
            if last[2]<=near:last=last+(first-last)*((near-last[2])/(first[2]-last[2]))
            pa=np.asarray(camera.img_from_cam(first))*scale;pb=np.asarray(camera.img_from_cam(last))*scale
            if not np.isfinite(pa).all() or not np.isfinite(pb).all() or np.max(np.abs(np.r_[pa,pb]))>1e7:continue
            ok,x,y=cv2.clipLine((0,0,w,h),tuple(np.round(pa).astype(int)),tuple(np.round(pb).astype(int)))
            if ok:cv2.line(preview,x,y,(0,0,255),3);count+=1
        cv2.putText(preview,'PixCuboid prior; unverified; not observed hidden walls',(15,35),cv2.FONT_HERSHEY_SIMPLEX,.65,(0,0,255),2)
        if not cv2.imwrite(str(a.output/(Path(image.name).stem+'-pixcuboid.jpg')),preview):raise OSError('failed to save overlay')
        print(image.name,'visible projected edges',count)


if __name__=='__main__':main()
