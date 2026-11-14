"""Count sparse tracks in the image-defined local wall patch, not a scan fit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pycolmap

from benchmarks.ws_geometry.run_kicker_model_first import sha, write


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--training',type=Path,required=True)
    parser.add_argument('--reconstruction',type=Path,required=True)
    parser.add_argument('--masks',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    if a.output.exists():raise FileExistsError('choose a new report path')
    data=json.loads(a.training.read_text());manifest=json.loads((a.masks/'manifest.json').read_text())
    bins=[{'file':p.name,'sha256':sha(p)} for p in sorted(a.reconstruction.glob('*.bin'))]
    if bins!=data['source_reconstruction']:raise ValueError('camera reconstruction changed')
    rec=pycolmap.Reconstruction(a.reconstruction);cameras={c['image_id']:c for c in data['cameras']}
    records={r['image_id']:r for r in manifest['images']};masks={}
    for ident,camera in cameras.items():
        record=records[ident];path=a.masks/record['mask_file']
        if Path(record['mask_file']).name!=record['mask_file'] or record['sha256']!=camera['sha256'] or sha(path)!=record['mask_sha256']:
            raise ValueError('mask/photo mismatch')
        with np.load(path,allow_pickle=False) as arrays:masks[ident]=arrays['labels']
        if masks[ident].shape!=(128,128):raise ValueError('unexpected mask dimensions')
    lookup={key:{o['image_id']:o['pixel_xy'] for o in values} for key,values in data['corners'].items()}
    lines={o['image_id']:o['points_px'] for o in data['ceiling_lines']};tracks=[]
    for ident,point in rec.points3D.items():
        observations=[]
        for entry in point.track.elements:
            image_id=entry.image_id
            if image_id not in cameras:continue
            x,y=rec.images[image_id].points2D[entry.point2D_idx].xy
            left,right=np.array(lookup['left_top'][image_id]),np.array(lookup['right_top'][image_id])
            p0,p1=np.array(lines[image_id]);cam=cameras[image_id]
            if not left[0]<=x<=right[0] or not 0<=x<cam['width_px'] or not 0<=y<cam['height_px']:continue
            roof=p0[1]+(p1[1]-p0[1])*(x-p0[0])/(p1[0]-p0[0])
            door=left[1]+(right[1]-left[1])*(x-left[0])/(right[0]-left[0])
            label=masks[image_id][min(127,int(y*128/cam['height_px'])),min(127,int(x*128/cam['width_px']))]
            if roof<=y<=door and label==0:
                observations.append({'image_id':image_id,'pixel_xy':[float(x),float(y)],'photo_sha256':cam['sha256']})
        if len({o['image_id'] for o in observations})>=2:
            tracks.append({'id':int(ident),'xyz':point.xyz.tolist(),'observations':observations})
    result={'schema':'worldstate-local-wall-track-diagnostic/0.1','training_sha256':sha(a.training),
        'mask_manifest_sha256':sha(a.masks/'manifest.json'),'tracks':tracks,'count':len(tracks),
        'method':'At least two distinct registered views with observed track pixel inside the AI-selected door-top/ceiling patch and UPerNet wall class.',
        'limitations':['Development observation ROI, not independently annotated wall boundaries.',
                       'Uncalibrated semantic predictions may exclude valid wall points.',
                       'Zero tracks does not prove the wall is absent; no count threshold was relaxed.']}
    a.output.parent.mkdir(parents=True,exist_ok=True);write(a.output,result)
    print(json.dumps({'selected_tracks':len(tracks),'output':str(a.output)},indent=2))


if __name__=='__main__':main()
