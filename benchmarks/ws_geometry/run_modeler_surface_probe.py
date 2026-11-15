"""Probe the same general solver on semantic photo-track plane proposals.

Candidate edges are convex hulls of actual feature points, not observed wall
boundaries. No person has reviewed these semantic labels or correspondences.
This development diagnostic deliberately does not open a laser scan or create
IFC solids from unverified, nonrectangular feature hulls.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from scipy.spatial import ConvexHull

from products.worldstate_bim.general_modeler import SCHEMA_INPUT, build_room_ir, camera_digest, solve_modeler
from products.worldstate_bim.multiview_fusion import _plane_fit


def area(points: np.ndarray) -> float:
    return abs(float(np.sum(points[:,0]*np.roll(points[:,1],-1)-points[:,1]*np.roll(points[:,0],-1))))/2


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fusion',type=Path,required=True);p.add_argument('--images',type=Path,required=True)
    p.add_argument('--up',type=float,nargs=3,required=True,help='Explicit unverified search direction in source coordinates')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose new output')
    fusion=json.loads(a.fusion.read_text());cameras={c['image_id']:c for c in fusion['cameras']}
    supported=[t for t in fusion['tracks'] if t['status']=='SUPPORTED' and t['semantic_class']==0]
    # Fixed pre-existing 10-track / 3-view support and gravity-direction check;
    # the z-up direction is an explicit unverified scene assumption.
    up=np.asarray(a.up,dtype=float)
    if not np.isfinite(up).all() or np.linalg.norm(up)<1e-8:raise ValueError('invalid search direction')
    up/=np.linalg.norm(up);planes,threshold=_plane_fit(supported,10,7,up)
    by_id={t['id']:t for t in supported};candidates=[];logs=[]
    for plane in planes:
        tracks=[];seen=set()
        for ident in plane['support_point_ids']:
            track=by_id[ident];obs=[o for o in track['observations'] if o['usable'] and o['semantic_class']==0]
            signature=tuple(sorted((o['image_id'],*o['pixel_xy']) for o in obs))
            if len({o['image_id'] for o in obs})<2 or signature in seen:continue
            tracks.append(track);seen.add(signature)
        try:
            xyz=np.array([t['xyz'] for t in tracks]);normal=np.asarray(plane['normal']);axis=np.eye(3)[int(np.argmin(np.abs(normal)))];x=axis-normal*(axis@normal);x/=np.linalg.norm(x);y=np.cross(normal,x)
            projected=np.column_stack((xyz@x,xyz@y));hull=ConvexHull(projected).vertices
            if len(hull)<4:raise ValueError('fewer than four independent boundary feature tracks')
            choices=(list(combo) for combo in itertools.combinations(hull,4))
            pick=max(choices,key=lambda idx:area(projected[idx]))
            objects=[{'id':plane['id'],'ifc_type':'IfcWall','vertices':['p1','p2','p3','p4'],
                      'surface_kind':'visible_surface_patch',
                      'boundary_note':'CONVEX_HULL_OF_FEATURES_NOT_OBSERVED_WALL_BOUNDARY'}]
            observations=[]
            for vertex,index in zip(objects[0]['vertices'],pick):
                track=tracks[index]
                for o in track['observations']:
                    if o['usable'] and o['semantic_class']==0:
                        cam=cameras[o['image_id']]
                        observations.append({'kind':'point','object_id':objects[0]['id'],'feature_id':vertex,
                            'image_id':cam['image_id'],'photo_sha256':cam['sha256'],'camera_sha256':camera_digest(cam),
                            'pixel_xy':o['pixel_xy'],'origin':'deterministic','confirmation':'accepted_unverified',
                            'visibility':'visible','sigma_px':2.,'created_at':datetime.now(timezone.utc).isoformat(),
                            'source_track_id':track['id']})
            used={o['image_id'] for o in observations}
            data={'schema':SCHEMA_INPUT,'camera_mode':'KNOWN_POSE_SCANNER_REGISTERED_DEVELOPMENT',
                  'coordinate_system':fusion['coordinate_system'],'source_reconstruction':fusion['source_reconstruction'],
                  'cameras':[cameras[i] for i in sorted(used)],'objects':objects,'observations':observations,'object_constraints':[]}
            solution=solve_modeler(data,sensitivity={'samples':12,'camera_position_sigma_source':.002,
                                    'camera_rotation_sigma_deg':.05,'focal_sigma_fraction':.001})
            try:
                build_room_ir(data,solution,project_id='unreviewed-probe',scale={'basis':'assumed','metres_per_source_unit':1.},
                              thickness_m=.1,up_source=up.tolist(),allow_rectangular_approximation=True)
                export_check={'status':'GEOMETRICALLY_ELIGIBLE_SEMANTICALLY_UNVERIFIED_NO_IFC_WRITTEN'}
            except ValueError as exc:export_check={'status':'REJECTED','reason':str(exc)}
            candidates.append((data,solution));logs.append({'plane_id':plane['id'],'status':'SOLVED_UNVERIFIED_FEATURE_HULL',
                'support_tracks':plane['support_count'],'feature_track_ids':[tracks[i]['id'] for i in pick],
                'point_rms_px':solution['optimization']['point_rms_px'],'ifc_gate':export_check})
        except (ValueError,RuntimeError) as exc:
            logs.append({'plane_id':plane['id'],'status':'REJECTED','reason':str(exc),'support_tracks':plane['support_count']})
    a.output.mkdir(parents=True)
    for index,(data,solution) in enumerate(candidates,1):
        for name,value in (('input',data),('solution',solution)):
            (a.output/f'{index}-{name}.json').write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
        views=solution['objects'][0]['projections'][:3]
        for view in views:
            cam=cameras[view['image_id']];path=a.images/cam['photo']
            if Path(cam['photo']).name!=cam['photo'] or path.is_symlink():raise ValueError('unsafe source image')
            with path.open('rb') as stream:image_sha=hashlib.file_digest(stream,'sha256').hexdigest()
            if image_sha!=cam['sha256']:raise ValueError('source image hash changed')
            raw=cv2.imread(str(path))
            if raw is None:raise ValueError('source photo missing')
            im=cv2.resize(raw,(1553,1034));s=np.array([1553/cam['width_px'],1034/cam['height_px']]);poly=np.rint(np.asarray(view['polygon_px'])*s).astype(np.int32)
            cv2.polylines(im,[poly],True,(0,255,255),3)
            cv2.putText(im,'Unreviewed feature hull; NOT a physical wall boundary',(20,35),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,0,255),2)
            cv2.imwrite(str(a.output/f'{index}-{Path(cam["photo"]).stem}.jpg'),im)
    joint={'status':'NOT_RUN_INSUFFICIENT_VALID_CANDIDATES'}
    if len(candidates)>=2:
        all_cameras={c['image_id']:c for data,_ in candidates for c in data['cameras']}
        joint_input={'schema':SCHEMA_INPUT,'camera_mode':'KNOWN_POSE_SCANNER_REGISTERED_DEVELOPMENT',
            'coordinate_system':fusion['coordinate_system'],'source_reconstruction':fusion['source_reconstruction'],
            'cameras':list(all_cameras.values()),'objects':[o for data,_ in candidates for o in data['objects']],
            'observations':[o for data,_ in candidates for o in data['observations']],'object_constraints':[]}
        try:
            combined=solve_modeler(joint_input,sensitivity={'samples':12,'camera_position_sigma_source':.002,
                                   'camera_rotation_sigma_deg':.05,'focal_sigma_fraction':.001})
            (a.output/'joint-input.json').write_text(json.dumps(joint_input,indent=2,allow_nan=False)+'\n')
            (a.output/'joint-solution.json').write_text(json.dumps(combined,indent=2,allow_nan=False)+'\n')
            joint={'status':'SOLVED_UNVERIFIED','objects':len(combined['objects']),'point_rms_px':combined['optimization']['point_rms_px']}
        except (ValueError,RuntimeError) as exc:joint={'status':'REJECTED','reason':str(exc)}
    summary={'schema':'worldstate-general-modeler-surface-probe/0.1','status':'DEVELOPMENT_NOT_WALL_ACCEPTANCE',
        'input_track_count':len(supported),'plane_threshold_source':threshold,'assumed_up_source':up.tolist(),
        'candidates':logs,'joint':joint,
        'limitations':['The search up direction is assumed, not independently measured.',
          'These are unreviewed wall-semantic SIFT feature hulls; furniture, doors and duplicate walls may be mislabeled.',
          'Hull edges are not observed physical wall boundaries and cannot establish completeness or precise dimensions.',
          'No human annotation or independent test is represented; no IFC is generated from the unreviewed hulls.']}
    (a.output/'report.json').write_text(json.dumps(summary,indent=2,allow_nan=False)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
