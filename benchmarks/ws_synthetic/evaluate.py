"""Evaluate submitted artifacts against separately stored synthetic truth.

This is a synthetic-only development/research metric, not real-room accuracy.
The evaluator checks the frozen artifact hashes and never fills missing outputs.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import tempfile

import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.spatial import cKDTree
from shapely.geometry import Polygon
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.validate

from products.worldstate_bim.room_ifc import export_room
from products.worldstate_bim.room_ir import geometry_issues, revise_element, validate_room


def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def verify_freeze(dataset: Path) -> dict:
    manifest=json.loads((dataset/'manifest.json').read_text())
    if manifest.get('schema')!='ws-synthetic-freeze/0.1':raise ValueError('invalid frozen manifest')
    for name,value in manifest['files'].items():
        item=dataset/name
        if (not item.resolve().is_relative_to(dataset) or item.is_symlink() or
            not item.is_file() or sha(item)!=value):raise ValueError('frozen artifact mismatch: '+name)
    return manifest


def walls(model):return [e for e in model['elements'] if e['ifc_type']=='IfcWall']


def wall_values(model,e):
    nodes={n['id']:n for n in model['nodes']};a=np.array([nodes[e['start']]['x'],nodes[e['start']]['y']],float)
    b=np.array([nodes[e['end']]['x'],nodes[e['end']]['y']],float);delta=b-a;length=float(np.linalg.norm(delta))
    return {'a':a,'b':b,'center':(a+b)/2,'length':length,'height':e['parameters']['height']['value'],
            'thickness':e['parameters']['thickness']['value'],'direction':delta/length}


def pr(tp,pred,total):
    return {'matched':int(tp),'predicted':int(pred),'reference':int(total),
            'precision':float(tp/pred) if pred else None,'recall':float(tp/total) if total else None}


def match_walls(ref,pred,threshold=.15,angle_deg=10.):
    rw,pw=walls(ref),walls(pred);cost=np.full((len(rw),len(pw)),1e6)
    for i,r in enumerate(rw):
        x=wall_values(ref,r)
        for j,p in enumerate(pw):
            y=wall_values(pred,p);angle=math.degrees(math.acos(float(np.clip(abs(x['direction']@y['direction']),0,1))))
            dist=float(np.linalg.norm(x['center']-y['center']))
            if dist<=threshold and angle<=angle_deg:cost[i,j]=dist+abs(x['length']-y['length'])*.05
    rows,cols=linear_sum_assignment(cost) if cost.size else ([],[])
    match=[(rw[i],pw[j]) for i,j in zip(rows,cols) if cost[i,j]<1e5]
    return rw,pw,match


def layout(model):
    nodes={n['id']:n for n in model['nodes']}
    slab=next((e for e in model['elements'] if e['ifc_type']=='IfcSlab'),None)
    if not slab:return None
    polygon=Polygon([(nodes[n]['x'],nodes[n]['y']) for n in slab['outline']])
    return polygon if polygon.is_valid and polygon.area>0 else None


def topology(model, allowed):
    items={e['id']:e for e in walls(model)};result=set()
    keys=list(items)
    for i,left in enumerate(keys):
        for right in keys[i+1:]:
            if {items[left]['start'],items[left]['end']} & {items[right]['start'],items[right]['end']}:
                result.add(frozenset((allowed.get(left,'unmatched:'+left),allowed.get(right,'unmatched:'+right))))
    return result


def room_metrics(ref,pred):
    validate_room(pred);issues=geometry_issues(pred)
    if issues:raise ValueError('candidate has conflicting/unknown geometry: '+str(issues[:5]))
    rw,pw,matched=match_walls(ref,pred);details=[]
    for r,p in matched:
        a,b=wall_values(ref,r),wall_values(pred,p)
        error=lambda x,y:abs(x-y) if x is not None and y is not None else None
        details.append({'reference':r['id'],'candidate':p['id'],'length_abs_m':error(a['length'],b['length']),
          'height_abs_m':error(a['height'],b['height']),'thickness_abs_m':error(a['thickness'],b['thickness']),
          'center_xy_m':float(np.linalg.norm(a['center']-b['center']))})
    pmap={p['id']:r['id'] for r,p in matched};rmap={r['id']:r['id'] for r in rw}
    ra,pa=topology(ref,rmap),topology(pred,pmap);rp,pp=layout(ref),layout(pred)
    iou=None if rp is None or pp is None else float(rp.intersection(pp).area/rp.union(pp).area)
    def openings(model):
        items={e['id']:e for e in model['elements']}
        return [(e,items[e['fill']]['ifc_type'] if e.get('fill') else None) for e in model['elements'] if e['ifc_type']=='IfcOpeningElement']
    ro,po=openings(ref),openings(pred);used=set();hits=0
    for a,kind in ro:
        for index,(b,bkind) in enumerate(po):
            if index in used or kind!=bkind or pmap.get(b['host'])!=a['host']:continue
            ap,bp=a['parameters'],b['parameters']
            if all(abs(ap[x]['value']-bp[x]['value'])<=.1 for x in ('offset','width','height','sill')):
                hits+=1;used.add(index);break
    return {'wall_instances':pr(len(matched),len(pw),len(rw)),'wall_matching_threshold_center_m':.15,
            'wall_matching_threshold_angle_deg':10.,'wall_errors':details,'layout_iou':iou,
            'wall_topology':pr(len(ra&pa),len(pa),len(ra)),
            'opening_host_and_fill':pr(hits,len(po),len(ro)),
            'limitations':['Wall matching uses center and angle; openings use 0.1 m parameter gate.',
                           'Topology here is shared wall endpoints, not complete BIM topology.']}


def mesh_samples(ifc_path: Path,n=16000):
    model=ifcopenshell.open(str(ifc_path));settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True)
    triangles=[]
    for wall in model.by_type('IfcWall'):
        shape=ifcopenshell.geom.create_shape(settings,wall);verts=np.asarray(shape.geometry.verts).reshape(-1,3)
        faces=np.asarray(shape.geometry.faces,dtype=int).reshape(-1,3);triangles.extend(verts[faces])
    if not triangles:raise ValueError('no candidate wall geometry')
    tri=np.asarray(triangles);area=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)/2
    if float(area.sum())<=0:raise ValueError('no wall surface area')
    rng=np.random.default_rng(12345);idx=rng.choice(len(tri),size=n,p=area/area.sum());uv=rng.random((n,2));root=np.sqrt(uv[:,0])
    return (1-root)[:,None]*tri[idx,0]+(root*(1-uv[:,1]))[:,None]*tri[idx,1]+(root*uv[:,1])[:,None]*tri[idx,2]


def ifc_metrics(ref_ifc,pred,output_dir):
    path=output_dir/'candidate.ifc';export_room(pred,path);f=ifcopenshell.open(str(path));logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger)
    settings=ifcopenshell.geom.settings();checks=[]
    for typ in ('IfcWall','IfcSlab','IfcDoor','IfcWindow'):
        for obj in f.by_type(typ):
            try:shape=ifcopenshell.geom.create_shape(settings,obj);ok=bool(shape.geometry.verts)
            except Exception:ok=False
            checks.append({'type':typ,'guid':obj.GlobalId,'geometry':ok})
    ar=mesh_samples(ref_ifc);ap=mesh_samples(path);dpr=cKDTree(ar).query(ap)[0];drp=cKDTree(ap).query(ar)[0]
    testwall=walls(pred)[0];old=testwall['parameters']['height']['value']
    modified,_=revise_element(pred,testwall['id'],'height',old+.1,reason='automated synthetic edit check',operator='analyst')
    edited=output_dir/'candidate-edited.ifc';export_room(modified,edited);new=ifcopenshell.open(str(edited))
    before={x.GlobalId for x in f.by_type('IfcProduct')};after={x.GlobalId for x in new.by_type('IfcProduct')}
    return {'schema':f.schema,'schema_errors':len(logger.statements),'geometry_ok':sum(x['geometry'] for x in checks),
      'geometry_total':len(checks),'edit_export_ok':True,'all_product_guids_stable':before==after,
      'surface':{'candidate_to_reference_mean_m':float(dpr.mean()),'reference_to_candidate_mean_m':float(drp.mean()),
        'chamfer_l1_mean_m':float((dpr.mean()+drp.mean())/2),'accuracy_at_0_05m':float((dpr<=.05).mean()),
        'completeness_at_0_05m':float((drp<=.05).mean()),'samples_per_side':len(ar),
        'scope':'Monte Carlo samples of IFC wall surfaces; holes included; not real-world accuracy.'}}


def intrinsics(camera):
    values=camera['intrinsics']
    if camera['camera_model']=='SIMPLE_PINHOLE':f,cx,cy=values;return f,f,cx,cy
    if camera['camera_model']=='PINHOLE':return values
    raise ValueError('unsupported synthetic camera model')


def correspondence_metrics(ref: Path,pairs_path: Path,image_a:int,image_b:int):
    data=np.load(pairs_path,allow_pickle=False);aa=np.asarray(data['a'],float);bb=np.asarray(data['b'],float)
    if aa.shape!=bb.shape or aa.ndim!=2 or aa.shape[1]!=2 or not np.isfinite(aa).all() or len(aa)>100000:
        raise ValueError('matches must be finite Nx2 arrays a and b')
    cameras={c['image_id']:c for c in json.loads((ref/'cameras-exact.json').read_text())['cameras']};a,b=cameras[image_a],cameras[image_b]
    ta=np.load(ref/f'view-{image_a:03}-truth.npz');tb=np.load(ref/f'view-{image_b:03}-truth.npz')
    fx,fy,cx,cy=intrinsics(a);gx,gy,dx,dy=intrinsics(b);ra=np.asarray(a['rotation_camera_from_world']);rb=np.asarray(b['rotation_camera_from_world'])
    trans_a=np.asarray(a['translation_camera_from_world']);trans_b=np.asarray(b['translation_camera_from_world']);checked=correct=occluded=out=invalid=wall_checked=wall_correct=0
    errors=[]
    for x,y in zip(aa,bb):
        ix,iy=np.rint(x).astype(int)
        if not (0<=ix<a['width_px'] and 0<=iy<a['height_px']):invalid+=1;continue
        z=float(ta['depth_z_m'][iy,ix]);instance=int(ta['instance'][iy,ix])
        if not np.isfinite(z) or z<=0 or instance==0:invalid+=1;continue
        local=np.array([(ix-cx)*z/fx,(iy-cy)*z/fy,z]);world=ra.T@(local-trans_a);target=rb@world+trans_b
        if target[2]<=0:out+=1;continue
        expected=np.array([gx*target[0]/target[2]+dx,gy*target[1]/target[2]+dy]);jx,jy=np.rint(expected).astype(int)
        if not(0<=jx<b['width_px'] and 0<=jy<b['height_px']):out+=1;continue
        target_z=float(tb['depth_z_m'][jy,jx]);target_instance=int(tb['instance'][jy,jx])
        if not np.isfinite(target_z) or abs(target_z-target[2])>.05 or target_instance!=instance:occluded+=1;continue
        error=float(np.linalg.norm(y-expected));checked+=1;errors.append(error);correct+=int(error<=3.)
        if int(ta['semantic'][iy,ix])==1:wall_checked+=1;wall_correct+=int(error<=3.)
    evaluated=checked+occluded+out
    return {'submitted':len(aa),'checked_visible':checked,'correct_at_3px':correct,'visible_accuracy_at_3px':correct/checked if checked else None,
      'strict_evaluated':evaluated,'strict_accuracy_at_3px':correct/evaluated if evaluated else None,
      'wall_checked':wall_checked,'wall_correct_at_3px':wall_correct,'wall_accuracy_at_3px':wall_correct/wall_checked if wall_checked else None,
      'occluded_or_instance_mismatch':occluded,'outside_target':out,'invalid_source':invalid,
      'median_error_px':float(np.median(errors)) if errors else None,
      'scope':'Synthetic exact-pose RGB-D oracle; 0.05 m visibility tolerance. Strict accuracy counts occluded/out-of-frame as failures; invalid source is excluded.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--dataset',type=Path,required=True);p.add_argument('--scene',required=True)
    p.add_argument('--model',type=Path);p.add_argument('--matches',type=Path);p.add_argument('--images',type=int,nargs=2,default=[1,2]);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    dataset=a.dataset.resolve(strict=True);verify_freeze(dataset)
    if not re.fullmatch(r'[0-9a-f]{12}',a.scene):raise ValueError('invalid scene ID')
    ref=dataset/'reference'/a.scene
    if not ref.is_dir() or not (dataset/'input'/a.scene).is_dir():raise ValueError('scene does not exist')
    for source in (a.model,a.matches):
        if source and (source.is_symlink() or source.resolve(strict=True).is_relative_to(dataset/'reference')):
            raise ValueError('submitted artifact must be separate from reference')
    if a.output.resolve().is_relative_to(dataset):raise ValueError('evaluation output must be outside the frozen dataset')
    if a.output.exists():raise FileExistsError('choose a new output directory')
    a.output.mkdir(parents=True);report={'split':json.loads((dataset/'manifest.json').read_text())['split'],
       'scene':a.scene,'model':'NOT_SUBMITTED','correspondence':'NOT_SUBMITTED','scope':'SYNTHETIC_ONLY'}
    if a.model:
        pred=json.loads(a.model.read_text());truth=json.loads((ref/'ifc'/'model.json').read_text())
        report['model']=room_metrics(truth,pred)
        try:report['ifc']=ifc_metrics(ref/'ifc'/'model.ifc',pred,a.output)
        except (ValueError,RuntimeError,IndexError) as error:report['ifc']={'status':'FAILED','reason':str(error)}
    if a.matches:report['correspondence']=correspondence_metrics(ref,a.matches,*a.images)
    (a.output/'report.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n');print(json.dumps(report,allow_nan=False))


if __name__=='__main__':main()
