"""Generate seeded, simulated IFC rooms and calibrated Blender observations.

The destination must not exist. References are private to the evaluator, not
algorithm input; this local filesystem boundary does not stop a malicious user.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys

import numpy as np
from scipy.spatial.transform import Rotation
import ifcopenshell
import ifcopenshell.geom

from examples.bim_synthetic_room_round3.generate import synthetic_room
from products.worldstate_bim.room_cli import save_version
from products.worldstate_bim.room_ir import geometry_issues

HERE = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    with path.open('rb') as stream:return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def room(seed: int, shape: str) -> dict:
    rng = random.Random(seed);model = synthetic_room()
    width, depth = round(rng.uniform(4.2, 5.2), 3), round(rng.uniform(3.3, 4.2), 3)
    height, thickness = round(rng.uniform(2.65, 3.05), 3), round(rng.uniform(.10, .16), 3)
    if shape == 'rectangle':points = [(0,0),(width,0),(width,depth),(0,depth)]
    elif shape == 'l-shape':points = [(0,0),(width,0),(width,depth*.4),(width*.56,depth*.4),(width*.56,depth),(0,depth)]
    else:raise ValueError('unsupported synthetic shape')
    template=copy.deepcopy(model['nodes'][0]);model['nodes']=[]
    for i,(x,y) in enumerate(points,1):
        node=copy.deepcopy(template);node.update(id=f'n{i}',x=round(x,5),y=round(y,5));model['nodes'].append(node)
    oldwalls=[e for e in model['elements'] if e['ifc_type']=='IfcWall']
    walls=[]
    for i in range(len(points)):
        wall=copy.deepcopy(oldwalls[i%len(oldwalls)]);wall.update(id=f'wall-{i+1}',start=f'n{i+1}',end=f'n{(i+1)%len(points)+1}',axis_reference='centerline')
        wall['parameters']['height']['value']=height;wall['parameters']['thickness']['value']=thickness;walls.append(wall)
    rest=[e for e in model['elements'] if e['ifc_type']!='IfcWall']
    for e in rest:
        if e['ifc_type']=='IfcSlab':e['outline']=[n['id'] for n in model['nodes']]
        if e['ifc_type']=='IfcSpace':e['boundary_walls']=[w['id'] for w in walls]
        if e['id']=='opening-window':e['parameters']['offset']['value']=.35 if shape=='l-shape' else 1.
    model['elements']=walls+rest
    model['constraints']=[{'id':f'right-{i+1}','kind':'perpendicular','a':f'wall-{i+1}',
        'b':f'wall-{(i+1)%len(walls)+1}','status':'simulated','evidence_refs':['synthetic-design']} for i in range(len(walls))]
    model['project_id']='synthetic-'+hashlib.sha256(f'{seed}-{shape}'.encode()).hexdigest()[:12]
    model['evidence'][0]['source']='Procedurally generated; no real-world observations or measurements'
    if geometry_issues(model):raise ValueError('generated IR has conflicts')
    return model


def mesh_from_ifc(path: Path) -> tuple[list[dict],dict]:
    f=ifcopenshell.open(str(path));settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True)
    meshes=[];labels={};classes={'IfcWall':1,'IfcSlab':2,'IfcDoor':3,'IfcWindow':4}
    for idx,obj in enumerate([x for x in f.by_type('IfcProduct') if x.is_a() in classes],1):
        shape=ifcopenshell.geom.create_shape(settings,obj);verts=np.asarray(shape.geometry.verts,dtype=float).reshape(-1,3).tolist()
        faces=np.asarray(shape.geometry.faces,dtype=int).reshape(-1,3).tolist()
        meshes.append({'id':idx,'name':obj.Name,'ifc_type':obj.is_a(),'vertices':verts,'faces':faces})
        labels[str(idx)]={'object_id':obj.Name,'ifc_type':obj.is_a(),'semantic_id':classes[obj.is_a()]}
    return meshes,labels


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,required=True);p.add_argument('--split',choices=['dev','frozen-test'],required=True)
    p.add_argument('--blender',type=Path,required=True);p.add_argument('--xvfb',action='store_true')
    p.add_argument('--width',type=int,default=384);p.add_argument('--height',type=int,default=288)
    p.add_argument('--samples',type=int,default=4);p.add_argument('--threads',type=int,default=2);a=p.parse_args()
    if a.output.exists():raise FileExistsError('choose a new directory; never overwrite a frozen dataset')
    if not a.blender.is_file() or not (128<=a.width<=2048 and 128<=a.height<=2048 and 1<=a.samples<=128):raise ValueError('invalid render settings')
    a.output.mkdir(parents=True,mode=0o700);(a.output/'reference').mkdir(mode=0o700);(a.output/'input').mkdir()
    # Hidden seed and scene type never appear in algorithm input filenames.
    rng=random.Random(a.seed);scene_ids=[hashlib.sha256(f'{a.seed}-{i}'.encode()).hexdigest()[:12] for i in range(2)]
    records=[]
    for index,(ident,shape) in enumerate(zip(scene_ids,['rectangle','l-shape'])):
        ref=a.output/'reference'/ident;inp=a.output/'input'/ident;ref.mkdir();inp.mkdir();(inp/'images').mkdir()
        model=room(rng.randrange(2**32),shape);save_version(model,ref/'ifc')
        meshes,labels=mesh_from_ifc(ref/'ifc'/'model.ifc')
        nodes=model['nodes'];height=model['elements'][0]['parameters']['height']['value']
        spec={'mesh':meshes,'nodes':[[n['x'],n['y']] for n in nodes],'height':height,'seed':rng.randrange(2**32),
              'width':a.width,'height_px':a.height,'samples':a.samples,'furniture':True,
              'low_texture':index==1,'illumination':.65 if index==1 else 1.15}
        write(ref/'render-spec.json',spec);write(ref/'labels.json',labels)
        command=(["xvfb-run","-a","-s","-screen 0 1024x768x24"] if a.xvfb else [])+[str(a.blender),'-b','-t',str(a.threads),'--python-exit-code','1','--python',str(HERE/'render_blender.py'),'--',str(ref/'render-spec.json'),str(inp),str(ref)]
        with (ref/'render.log').open('w') as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False,env=os.environ.copy())
        if result.returncode:raise RuntimeError(f'Blender failed ({result.returncode}); see {ref/"render.log"}')
        import OpenEXR
        camera_data=json.loads((ref/'cameras-exact.json').read_text());cameras=[]
        semantic_map={int(k):v['semantic_id'] for k,v in labels.items()};semantic_map.update({900:5,901:6})
        for camera in camera_data['cameras']:
            ident_img=camera['image_id'];name=f'view-{ident_img:03}.png';camera['sha256']=sha(inp/'images'/name)
            for pass_name in ('depth','instance'):
                file=ref/f'{pass_name}-{ident_img:03}.exr';data=OpenEXR.File(str(file)).channels()['value.V'].pixels.copy()
                if pass_name=='depth':depth=np.where(np.isfinite(data)&(data<1e9),data,np.nan).astype(np.float32)
                else:instance=np.rint(data).astype(np.uint16)
                file.unlink()
            semantic=np.zeros(instance.shape,dtype=np.uint8)
            for number,label in semantic_map.items():semantic[instance==number]=label
            np.savez_compressed(ref/f'view-{ident_img:03}-truth.npz',depth_z_m=depth,instance=instance,semantic=semantic)
            candidate=copy.deepcopy(camera);candidate['photo']=name
            # Simulated calibrated/noisy camera input; the exact poses stay in reference.
            pos_sigma=0. if index==0 else .006;rot_sigma=0. if index==0 else .12
            if pos_sigma:
                nr=np.array([[rng.gauss(0,rot_sigma) for _ in range(3)]])[0]
                rr=Rotation.from_rotvec(np.radians(nr)).as_matrix()@np.array(candidate['rotation_camera_from_world'])
                tt=np.array(candidate['translation_camera_from_world'])+np.array([rng.gauss(0,pos_sigma) for _ in range(3)])
                candidate['rotation_camera_from_world']=rr.tolist();candidate['translation_camera_from_world']=tt.tolist()
            candidate['registration_status']='SIMULATED_CAMERA_INPUT_NOT_REAL_CALIBRATION'
            cameras.append(candidate)
        write(ref/'cameras-exact.json',camera_data)
        write(inp/'cameras.json',{'schema':'worldstate-modeler-cameras/0.1','camera_mode':'known-pose',
             'cameras':cameras,'source_reconstruction':[{'kind':'synthetic_blender_render',
                 'sha256':sha(HERE/'render_blender.py'),'status':'SIMULATED'}],
             'warning':'Synthetic cameras; poses may be perturbed. No real measurement.'})
        records.append({'id':ident,'shape':shape,'views':len(cameras),'camera_translation_sigma_m':pos_sigma,
                        'camera_rotation_sigma_deg':rot_sigma,'low_texture':index==1,'furniture_occluder':True})
    write(a.output/'reference'/'generation.json',{'seed':a.seed,'split':a.split,'scenes':records,
          'semantics':{'0':'background','1':'wall','2':'floor/slab','3':'door','4':'window','5':'furniture','6':'ceiling'},
          'depth':'Camera Z in metres; NaN means no surface; instance and semantic masks use render pass object index.'})
    # Commit to every immutable data artifact, including renderer source and generated truth.
    hashes={str(f.relative_to(a.output)):sha(f) for f in sorted(a.output.rglob('*')) if f.is_file()}
    write(a.output/'manifest.json',{'schema':'ws-synthetic-freeze/0.1','split':a.split,'source_sha256':{'generate.py':sha(HERE/'generate.py'),'render_blender.py':sha(HERE/'render_blender.py')},
          'files':hashes,'warning':'Synthetic-only data. Hashes detect subsequent changes; they do not hide references from a privileged local user.'})
    print(json.dumps({'status':'GENERATED_SYNTHETIC','split':a.split,'scenes':len(records),'views':sum(x['views'] for x in records),'output':str(a.output)}))


if __name__=='__main__':main()
