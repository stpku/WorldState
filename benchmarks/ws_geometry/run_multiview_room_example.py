"""Real-data development example: multiview surfaces to editable IFC.

No physical ruler was measured. This script derives an *assumed* scale from a
correlated reconstruction of the same photographs and chooses matched feature
points programmatically. It is NOT independent measurement or acceptance.
"""
from __future__ import annotations
import argparse
import copy
import itertools
import json
import math
from pathlib import Path
import numpy as np
from products.worldstate_bim.multiview_fusion import triangulate_observations,solve_multiview_scale,build_multiview_room
from products.worldstate_bim.room_ifc import export_room


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--fusion',type=Path,required=True);p.add_argument('--correlated-reference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new output directory')
    fusion=json.loads(a.fusion.read_text());reference=json.loads(a.correlated_reference.read_text())
    if reference.get('status')!='DEVELOPMENT_DIAGNOSTIC_NOT_GROUND_TRUTH':raise ValueError('reference must be explicitly correlated')
    factor=float(reference['scale_reference_units_per_sfm_unit']);cams={c['image_id']:c for c in fusion['cameras']};groups={}
    for track in fusion['tracks']:
        if track['status']!='SUPPORTED' or track['semantic_class']!=0:continue
        obs=[o for o in track['observations'] if o['usable'] and o['semantic_class']==0 and o['reprojection_error_px']<1.5]
        for x,y in itertools.combinations(obs,2):
            va=np.asarray(track['xyz'])-cams[x['image_id']]['center_world'];vb=np.asarray(track['xyz'])-cams[y['image_id']]['center_world']
            angle=math.degrees(math.acos(float(np.clip(va@vb/np.linalg.norm(va)/np.linalg.norm(vb),-1,1))))
            if angle>=2:groups.setdefault(tuple(sorted((x['image_id'],y['image_id']))),[]).append((track,x,y))
    best=None
    for pair,items in groups.items():
        for x,y in itertools.combinations(items,2):
            distance=float(np.linalg.norm(np.asarray(x[0]['xyz'])-y[0]['xyz']))
            if 1<distance<5 and (best is None or distance>best[0]):best=(distance,pair,x,y)
    if best is None:raise ValueError('no matching tracked features with adequate baseline')
    endpoints=[]
    for label,item in zip(('debug-feature-a','debug-feature-b'),best[2:]):
        observations=[{'image_id':o['image_id'],'photo_sha256':o['photo_sha256'],'pixel_xy':o['pixel_xy']} for o in item[1:]]
        endpoints.append({'id':label,'source':'automatically selected feature; not a measured ruler endpoint',
                          'track_id':item[0]['id'],'observations':observations})
    xyz=[np.asarray(triangulate_observations(fusion['cameras'],e['observations'])['xyz']) for e in endpoints]
    anchor={'schema':'worldstate-multiview-scale-anchor/0.1','confirmed':True,'basis':'assumed',
        'distance_m':float(np.linalg.norm(xyz[1]-xyz[0])*factor),'measurement_uncertainty_m':None,
        'description':'DEBUG ONLY: scale assumed from correlated Metashape reconstruction of the same photos; endpoints are tracked features, not independently measured ruler endpoints; uncertainty unknown',
        'endpoints':endpoints}
    solution=solve_multiview_scale(fusion,anchor)
    walls=sorted(fusion['wall_surfaces'],key=lambda x:-x['support_count']);selected=[]
    for wall in walls:
        if not selected or all(abs(float(np.dot(wall['normal'],x['normal'])))<math.cos(math.radians(35)) for x in selected):selected.append(wall)
        if len(selected)==2:break
    if len(selected)<2:raise ValueError('fewer than two sufficiently different surface hypotheses')
    ids=[s['id'] for s in selected]
    kwargs={'project_id':'eyeful-room-dev-multiview','assumed_thickness_m':.12,'confirmed_candidates':True,
            'allow_assumed_scale':True,'operator_kind':'automation'}
    model=build_multiview_room(fusion,anchor,solution,ids,**kwargs)
    a.output.mkdir(parents=True)
    def save(name,value): (a.output/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')
    save('anchor-assumed.json',anchor);save('scale-solution.json',solution);save('original.json',model)
    export_room(model,a.output/'original.ifc')
    changed=copy.deepcopy(anchor);changed['distance_m']*=1.2
    try:build_multiview_room(fusion,changed,solution,ids,**kwargs)
    except ValueError as exc:stale=str(exc)
    else:raise RuntimeError('changed anchor did not invalidate scale')
    new_solution=solve_multiview_scale(fusion,changed);revised=build_multiview_room(fusion,changed,new_solution,ids,**kwargs);revised['revision']=2
    save('scale-counterfactual.json',revised);export_room(revised,a.output/'scale-counterfactual.ifc')
    save('run-summary.json',{'operator':'automation','selected_surface_ids':ids,'wall_candidates':len(ids),
       'selection':'two different plane orientations; NOT independent physical wall verification',
       'anchor_basis':'assumed from correlated same-photo reconstruction; not a ruler measurement',
       'anchor_physical_uncertainty':'UNKNOWN','scale_factor':solution['metres_per_sfm_unit'],
       'endpoint_reprojection_px':[e['max_reprojection_error_px'] for e in solution['endpoint_solutions']],
       'endpoint_parallax_degrees':[e['max_parallax_degrees'] for e in solution['endpoint_solutions']],
       'counterfactual_scale_ratio':new_solution['metres_per_sfm_unit']/solution['metres_per_sfm_unit'],
       'changed_anchor_with_old_solution':stale,'scope':'PARTIAL_OPEN','real_room_accuracy':'NOT_MEASURED'})
    print(json.dumps(json.loads((a.output/'run-summary.json').read_text()),indent=2))

if __name__=='__main__':main()
