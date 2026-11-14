"""Render real track observations and projected 3D surface hypotheses on photos."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fusion',type=Path,required=True)
    p.add_argument('--images',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--surface',action='append',required=True);p.add_argument('--photo',action='append',required=True)
    a=p.parse_args();f=json.loads(a.fusion.read_text());surfaces={x['id']:x for x in f['wall_surfaces']};tracks={x['id']:x for x in f['tracks']}
    if any(x not in surfaces for x in a.surface):raise ValueError('unknown surface')
    a.output.mkdir(parents=True,exist_ok=True);colors=[(0,165,255),(235,100,50),(70,200,60),(230,70,220)];out=[]
    for name in a.photo:
        camera=next((c for c in f['cameras'] if c['photo']==name),None)
        if camera is None or Path(name).name!=name:raise ValueError('photo is not registered')
        source=a.images/name;raw=source.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=camera['sha256']:raise ValueError('photo hash mismatch')
        image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR);R=np.asarray(camera['rotation_camera_from_world']);t=np.asarray(camera['translation_camera_from_world']);params=camera['intrinsics']
        if camera['camera_model']=='SIMPLE_PINHOLE':fx=fy=params[0];cx,cy=params[1:]
        elif camera['camera_model']=='PINHOLE':fx,fy,cx,cy=params
        else:raise ValueError('unsupported camera')
        def project(p):
            q=R@np.asarray(p)+t
            if q[2]<=0:return None
            x=fx*q[0]/q[2]+cx;y=fy*q[1]/q[2]+cy
            return [int(round(x)),int(round(y))]
        counts={}
        for index,surface_id in enumerate(a.surface):
            surface=surfaces[surface_id];color=colors[index%len(colors)];count=0
            for point_id in surface['support_point_ids']:
                for obs in tracks[point_id]['observations']:
                    if obs['image_id']==camera['image_id'] and obs['usable'] and obs['semantic_class']==0:
                        xy=tuple(int(round(v)) for v in obs['pixel_xy']);cv2.circle(image,xy,4,color,-1);count+=1
            v=surface.get('visible_candidate');up=np.asarray(f['floor_up'])
            if v:
                lo,hi=v['visible_height_range_arbitrary'];start=np.asarray(v['floor_line_start']);end=np.asarray(v['floor_line_end'])
                polygon=[project(start+up*lo),project(end+up*lo),project(end+up*hi),project(start+up*hi)]
                if all(q is not None for q in polygon):cv2.polylines(image,[np.asarray(polygon,np.int32)],True,color,2,cv2.LINE_AA)
            counts[surface_id]=count
            cv2.putText(image,f'{surface_id[-6:]}: {count} tracks; outline is inferred',(15,30+30*index),cv2.FONT_HERSHEY_SIMPLEX,.52,color,2,cv2.LINE_AA)
        dest=a.output/(Path(name).stem+'-3d-evidence.png');cv2.imwrite(str(dest),image)
        out.append({'photo':name,'photo_sha256':camera['sha256'],'observations':counts,'overlay_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    (a.output/'manifest.json').write_text(json.dumps({'renders':out,'warning':'Projected sparse-support plane outlines are inferred, not observed wall boundaries.'},indent=2)+'\n')
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()
