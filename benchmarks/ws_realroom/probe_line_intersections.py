"""Test unreviewed line intersections with the existing multiview Modeler.

The Modeler currently accepts wall hypotheses only. Here that type is a
required solver placeholder for a geometric experiment, not a semantic wall
classification; this script never imports or exports an IFC. A successful
fit still needs independent physical-feature and object review.
"""
import argparse
from datetime import datetime, timezone
import itertools
import json
from pathlib import Path

import numpy as np

from benchmarks.ws_realroom.compare_visual_correspondence import load_inputs, point_diagnostics, sha
from products.worldstate_bim.general_modeler import SCHEMA_INPUT, camera_digest, solve_modeler


def intersection(a,b):
    x,y=a[1]-a[0],b[1]-b[0]
    cross=lambda u,v:float(u[0]*v[1]-u[1]*v[0])
    denominator=cross(x,y)
    if abs(denominator)<.25*np.linalg.norm(x)*np.linalg.norm(y):return None
    delta=b[0]-a[0];t=cross(delta,y)/denominator;u=cross(delta,x)/denominator
    if not(-.06<=t<=1.06 and -.06<=u<=1.06):return None
    return a[0]+t*x


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',type=Path,required=True)
    p.add_argument('--masks',type=Path,required=True);p.add_argument('--matching',type=Path,required=True)
    p.add_argument('--images',type=int,nargs=2,required=True);p.add_argument('--features',nargs=4,required=True,
        help='Four ordered matched-line intersections, each written as i:j; selections are unreviewed')
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output file')
    state,views=load_inputs(a.workspace,a.images,a.masks)
    matching=json.loads((a.matching/'result.json').read_text())
    if matching.get('mode')!='gluestick' or [(x['id'],x['sha256']) for x in matching['images']] != [(v['camera']['image_id'],v['camera']['sha256']) for v in views]:
        raise ValueError('matching output and registered photos differ')
    lines=np.load(a.matching/'lines.npz',allow_pickle=False);A,B=lines['a'],lines['b']
    candidates={}
    for i,j in itertools.combinations(range(len(A)),2):
        x,y=intersection(A[i],A[j]),intersection(B[i],B[j])
        if x is None or y is None:continue
        if any(not (0<=p[0]<v['camera']['width_px'] and 0<=p[1]<v['camera']['height_px']) for p,v in ((x,views[0]),(y,views[1]))):continue
        diagnostic=point_diagnostics(np.array([x]),np.array([y]),*views)
        if diagnostic['sampson_px_median']<=3 and diagnostic['ray_angle_deg_median']>=1:
            candidates[(i,j)]={'lines':[i,j],'a':x.tolist(),'b':y.tolist(),
                'sampson_px':diagnostic['sampson_px_median'],'ray_angle_deg':diagnostic['ray_angle_deg_median'],
                'status':'DETERMINISTIC_UNREVIEWED_NOT_HUMAN_CONFIRMED'}
    vertices=[]
    for text in a.features:
        parts=text.split(':')
        if len(parts)!=2 or any(not x.isdigit() for x in parts):raise ValueError('features must be line IDs i:j')
        key=tuple(sorted(map(int,parts)))
        if key not in candidates:raise ValueError(f'feature {text} is not a geometrically plausible matched-line intersection')
        vertices.append(candidates[key])
    nodes=sorted({i for pair in candidates for i in pair});cycles=0
    adjacency={i:set() for i in nodes}
    for i,j in candidates:adjacency[i].add(j);adjacency[j].add(i)
    for x in nodes:
        for y in adjacency[x]:
            for z in adjacency[y]-{x}:
                for w in (adjacency[z] & adjacency[x])-{y}:
                    if x==min(x,y,z,w) and y<w:cycles+=1
    observations=[];now=datetime.now(timezone.utc).isoformat();cameras=[v['camera'] for v in views]
    for index,vertex in enumerate(vertices,1):
        for i,c in enumerate(cameras):
            observations.append({'kind':'point','object_id':'unreviewed-geometric-patch','feature_id':f'p{index}',
                'image_id':c['image_id'],'pixel_xy':vertex['a' if i==0 else 'b'],
                'photo_sha256':c['sha256'],'camera_sha256':camera_digest(c),'origin':'deterministic',
                'confirmation':'automation_unverified','visibility':'visible','sigma_px':3.0,'created_at':now})
    data={'schema':SCHEMA_INPUT,'camera_mode':state['camera_mode'],
          'coordinate_system':{'name':'registered reconstruction','scale_status':'UNKNOWN'},
          'source_reconstruction':state['source_reconstruction'],'cameras':cameras,
          'objects':[{'id':'unreviewed-geometric-patch','ifc_type':'IfcWall',
                      'vertices':['p1','p2','p3','p4'],'surface_kind':'visible_surface_patch'}],
          'observations':observations,'object_constraints':[]}
    report={'status':'NOT_SOLVED','physical_identity':'UNREVIEWED',
            'source_images':[{'image_id':v['camera']['image_id'],'photo_sha256':v['camera']['sha256'],
                              'camera_sha256':camera_digest(v['camera'])} for v in views],
            'matching_result_sha256':sha(a.matching/'result.json'),'matching_lines_sha256':sha(a.matching/'lines.npz'),
            'solver_type_placeholder':'IfcWall is required by the existing Modeler; not a semantic classification',
            'line_matches':len(A),'geometrically_plausible_intersections':len(candidates),'four_line_cycles':cycles,
            'selected':vertices,'candidates':list(candidates.values()),'ifc_export':'NOT_ATTEMPTED_SEMANTICS_UNVERIFIED'}
    try:
        solution=solve_modeler(data)
        report.update(status='UNVERIFIED_GEOMETRIC_PATCH',optimization=solution['optimization'],
                      surface=solution['objects'][0],warning='Not a verified wall, window or full building element.')
    except ValueError as exc:report['rejection']=str(exc)
    a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:report.get(k) for k in ('status','geometrically_plausible_intersections','four_line_cycles','rejection','ifc_export')},ensure_ascii=False))


if __name__=='__main__':main()
