"""Multiview building-surface candidates and bounded Room IR compilation.

The solver consumes declared pixel correspondences rather than scene-specific
detectors. Coordinates remain in the source reconstruction frame until an
explicit scale is applied. Pixel agreement does not establish wall identity,
registration quality, physical dimensions, or engineering fitness.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from typing import Any

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from .multiview_fusion import _camera_matrix, triangulate_observations
from .room_ir import SCHEMA, geometry_issues, quantity, validate_room


SCHEMA_INPUT = 'worldstate-bim-modeler-observations/0.1'
ORIGINS = {'ai_suggested', 'deterministic', 'user', 'automation', 'physical_measurement', 'assumption'}
CONFIRMATIONS = {'user_confirmed', 'accepted_unverified', 'automation_unverified', 'proposed', 'rejected'}


def digest(value: Any) -> str:
    """Return a replayable digest of a JSON observation or camera snapshot."""
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def camera_digest(camera: dict) -> str:
    """Bind a pixel to the source photo and the actual intrinsics and pose."""
    fields=('image_id','sha256','width_px','height_px','camera_model','intrinsics',
            'rotation_camera_from_world','translation_camera_from_world')
    return digest({name:camera[name] for name in fields})


def _project(point: np.ndarray, camera: dict) -> np.ndarray:
    k,r,t=_camera_matrix(camera);p=r@point+t
    if p[2]<=1e-8:raise ValueError('point is behind the registered camera')
    out=k@p;return out[:2]/out[2]


def _point(obs: dict, camera: dict) -> np.ndarray:
    xy=np.asarray(obs.get('pixel_xy'),dtype=float)
    if xy.shape!=(2,) or not np.isfinite(xy).all() or not (0<=xy[0]<camera['width_px'] and 0<=xy[1]<camera['height_px']):
        raise ValueError('point observation is outside its original photo')
    return xy


def _plane(points: np.ndarray) -> tuple[np.ndarray,float,float]:
    center=points.mean(axis=0);_,s,v=np.linalg.svd(points-center,full_matrices=False)
    if len(s)<2 or s[1]<1e-8 or s[0]/s[1]>1e5:raise ValueError('surface points are collinear or poorly conditioned')
    normal=v[-1];normal=normal if normal[np.argmax(np.abs(normal))]>=0 else -normal
    return normal,-float(normal@center),float(s[0]/s[1])


def _line(points: list) -> np.ndarray:
    if len(points)!=2:raise ValueError('line needs two original-image pixels')
    a,b=np.asarray(points,dtype=float)
    if np.linalg.norm(a-b)<10:raise ValueError('image line is too short')
    out=np.cross(np.r_[a,1.],np.r_[b,1.]);return out/np.linalg.norm(out[:2])


def _validate(data: dict) -> tuple[dict[int,dict],dict[str,dict],dict[tuple[str,str],list[dict]],list[dict]]:
    if data.get('schema')!=SCHEMA_INPUT:raise ValueError('unsupported modeler input schema')
    cameras={};objects={};groups={};lines=[]
    for camera in data.get('cameras',[]):
        ident=camera.get('image_id');sha=camera.get('sha256')
        if isinstance(ident,bool) or not isinstance(ident,int) or ident in cameras or not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{64}',sha):
            raise ValueError('invalid or duplicate camera')
        if not all(isinstance(camera.get(k),int) and camera[k]>0 for k in ('width_px','height_px')):raise ValueError('invalid photo dimensions')
        _camera_matrix(camera);cameras[ident]=camera
    if len(cameras)<2:raise ValueError('at least two registered cameras are required')
    for obj in data.get('objects',[]):
        ident=obj.get('id');vertices=obj.get('vertices')
        if not isinstance(ident,str) or not ident or ident in objects or obj.get('ifc_type')!='IfcWall':raise ValueError('invalid wall identity')
        if not isinstance(vertices,list) or not 3<=len(vertices)<=12 or any(not isinstance(x,str) or not x for x in vertices) or len(set(vertices))!=len(vertices):
            raise ValueError('a visible polygon needs 3–12 distinct ordered vertex identities')
        if obj.get('surface_kind') not in {'visible_surface_patch','wall_center_plane','full_wall_unverified'}:
            raise ValueError('wall surface and completeness must be explicit')
        objects[ident]=obj
        construction=obj.get('construction',{'kind':'polygon'})
        if not isinstance(construction,dict) or construction.get('kind') not in {'polygon','edge_to_line'}:
            raise ValueError('unsupported surface construction')
        if construction['kind']=='edge_to_line':
            direction=construction.get('direction_feature')
            if len(vertices)!=4 or not isinstance(direction,str) or not direction or direction in vertices:
                raise ValueError('edge-to-line construction requires four vertices and one separate direction feature')
            features=vertices[:2]+[direction]
        else:features=vertices
        for vertex in features:groups[(ident,vertex)]=[]
    if not objects:raise ValueError('at least one wall candidate is required')
    seen=set();pixel_owners={}
    for obs in data.get('observations',[]):
        if not isinstance(obs,dict):raise ValueError('invalid observation')
        camera=cameras.get(obs.get('image_id'));obj=objects.get(obs.get('object_id'))
        if camera is None or obj is None or obs.get('photo_sha256')!=camera['sha256'] or obs.get('camera_sha256')!=camera_digest(camera):
            raise ValueError('observation photo or camera version mismatch')
        if obs.get('origin') not in ORIGINS or obs.get('confirmation') not in CONFIRMATIONS or obs.get('visibility') not in {'visible','occluded','unknown'}:
            raise ValueError('observation origin, confirmation and visibility must be explicit')
        if obs['origin']!='user' and obs['confirmation']=='user_confirmed':raise ValueError('non-user observation cannot be human confirmed')
        if not isinstance(obs.get('created_at'),str) or not obs['created_at'].strip():raise ValueError('observation timestamp is required')
        sigma=obs.get('sigma_px')
        if isinstance(sigma,bool) or not isinstance(sigma,(int,float)) or not math.isfinite(sigma) or sigma<=0:raise ValueError('positive declared pixel uncertainty required')
        if obs['visibility']!='visible' or obs['confirmation'] in {'proposed','rejected'}:continue
        kind=obs.get('kind')
        if kind=='point':
            feature=obs.get('feature_id');key=(obj['id'],feature)
            if key not in groups or (key,obs['image_id']) in seen:raise ValueError('unknown vertex or duplicate observation')
            xy=_point(obs,camera);pixel_key=(obs['image_id'],round(float(xy[0]),6),round(float(xy[1]),6))
            prior=pixel_owners.get(pixel_key)
            if prior is not None and prior!=key:
                linked=any(c.get('kind') in {'coincident','intersection'} and
                    ((c.get('a'),c.get('vertex_a'),c.get('b'),c.get('vertex_b'))==(prior[0],prior[1],key[0],key[1]) or
                     (c.get('b'),c.get('vertex_b'),c.get('a'),c.get('vertex_a'))==(prior[0],prior[1],key[0],key[1]))
                    for c in data.get('object_constraints',[]))
                if not linked:raise ValueError('the same image pixel is assigned to multiple vertices without an explicit shared-corner constraint')
            pixel_owners[pixel_key]=key;groups[key].append(obs);seen.add((key,obs['image_id']))
        elif kind=='line':
            pair=obs.get('feature_ids')
            if not isinstance(pair,list) or len(pair)!=2 or pair[0]==pair[1] or any(x not in obj['vertices'] for x in pair):
                raise ValueError('line must identify two wall vertices')
            pixels=obs.get('points_px')
            if not isinstance(pixels,list) or len(pixels)!=2:raise ValueError('line needs two pixels')
            for xy in pixels:_point({**obs,'pixel_xy':xy},camera)
            _line(pixels);lines.append(obs)
        elif kind=='plane':
            # Retain proposed semantic evidence but do not imply an unimplemented loss.
            if not isinstance(obs.get('semantic_label'),str):raise ValueError('plane observation needs a semantic label')
            polygon=obs.get('polygon_px')
            if not isinstance(polygon,list) or not 3<=len(polygon)<=128:raise ValueError('plane observation needs a visible image polygon')
            for xy in polygon:_point({**obs,'pixel_xy':xy},camera)
        else:raise ValueError('unsupported observation kind')
    for key,group in groups.items():
        if len(group)<2:raise ValueError(f'{key[0]}:{key[1]} needs observations in at least two views')
    return cameras,objects,groups,lines


def _constraint_data(data: dict, objects: dict) -> list[dict]:
    constraints=data.get('object_constraints',[])
    if not isinstance(constraints,list):raise ValueError('constraints must be a list')
    for c in constraints:
        if c.get('kind') not in {'parallel','perpendicular','coplanar','coincident','intersection'}:
            raise ValueError('unsupported object constraint')
        a,b=c.get('a'),c.get('b')
        if a not in objects or b not in objects or a==b:raise ValueError('object constraint references invalid walls')
        if c.get('origin') not in ORIGINS or c.get('confirmation') not in {'user_confirmed','accepted_unverified','automation_unverified'}:
            raise ValueError('object constraint needs accepted provenance')
        if c['origin']!='user' and c['confirmation']=='user_confirmed':raise ValueError('constraint cannot impersonate a human')
        if not isinstance(c.get('created_at'),str) or not c['created_at'].strip():raise ValueError('constraint timestamp required')
        refs=c.get('evidence_refs')
        if not isinstance(refs,list) or not refs:raise ValueError('constraint must cite photo observations')
        for ref in refs:
            if not isinstance(ref,dict) or not any(o.get('object_id')==ref.get('object_id') and o.get('image_id')==ref.get('image_id')
                and o.get('visibility')=='visible' and o.get('confirmation') not in {'proposed','rejected'} for o in data['observations']):
                raise ValueError('constraint references a missing visible photo observation')
        if not {a,b}<={ref.get('object_id') for ref in refs}:raise ValueError('constraint needs evidence for both objects')
        uncertainty=c.get('uncertainty')
        needed=(['angle_rad'] if c['kind'] in {'parallel','perpendicular'} else
                ['angle_rad','distance_source'] if c['kind']=='coplanar' else ['distance_source'])
        if not isinstance(uncertainty,dict) or any(isinstance(uncertainty.get(k),bool) or not isinstance(uncertainty.get(k),(int,float))
            or not math.isfinite(uncertainty[k]) or uncertainty[k]<=0 for k in needed):
            raise ValueError('constraint needs positive declared uncertainty')
        if c['kind'] in {'coincident','intersection'} and (c.get('vertex_a') not in objects[a]['vertices'] or c.get('vertex_b') not in objects[b]['vertices']):
            raise ValueError('coincident or intersection constraint needs two vertex identities')
    return constraints


def _perturbed_cameras(cameras: dict[int,dict], rng: np.random.Generator, config: dict) -> dict[int,dict]:
    out=copy.deepcopy(cameras)
    for camera in out.values():
        _,r,t=_camera_matrix(camera);center=-r.T@t
        center+=rng.normal(0,config['camera_position_sigma_source'],3)
        dr=Rotation.from_rotvec(rng.normal(0,math.radians(config['camera_rotation_sigma_deg']),3)).as_matrix()
        r=dr@r;camera['rotation_camera_from_world']=r.tolist();camera['translation_camera_from_world']=(-r@center).tolist()
        factor=1.+float(rng.normal(0,config['focal_sigma_fraction']))
        camera['intrinsics'][0]*=factor
        if camera['camera_model']=='PINHOLE':camera['intrinsics'][1]*=factor
    return out


def _sensitivity(cameras: dict[int,dict], groups: dict, solved: dict, config: dict) -> dict:
    required=('samples','camera_position_sigma_source','camera_rotation_sigma_deg','focal_sigma_fraction')
    if not isinstance(config,dict) or any(key not in config for key in required):
        return {'status':'NOT_RUN_NO_DECLARED_PERTURBATIONS'}
    count=config['samples']
    if isinstance(count,bool) or not isinstance(count,int) or not 2<=count<=200:raise ValueError('sensitivity sample count must be 2–200')
    for key in required[1:]:
        if isinstance(config[key],bool) or not isinstance(config[key],(int,float)) or not math.isfinite(config[key]) or config[key]<0:
            raise ValueError('sensitivity perturbation must be finite and non-negative')
    rng=np.random.default_rng(41731);output={}
    for mode in ('pixel_only','camera_only','combined'):
        changes={key:[] for key in groups};rejected=0
        for _ in range(count):
            perturbed=_perturbed_cameras(cameras,rng,config) if mode!='pixel_only' else cameras
            trial={}
            try:
                for key,obs in groups.items():
                    pert=copy.deepcopy(obs)
                    if mode!='camera_only':
                        for item in pert:item['pixel_xy']=(np.asarray(item['pixel_xy'])+rng.normal(0,item['sigma_px'],2)).tolist()
                    point=triangulate_observations(list(perturbed.values()),pert)['xyz']
                    trial[key]=float(np.linalg.norm(np.asarray(point)-solved[key]))
            except ValueError:
                rejected+=1
                continue
            for key,value in trial.items():changes[key].append(value)
        details=[]
        for (obj,vertex),values in changes.items():
            details.append({'object_id':obj,'feature_id':vertex,'accepted':len(values),
                'median_displacement_source_units':float(np.median(values)) if values else None,
                'p90_displacement_source_units':float(np.percentile(values,90)) if values else None})
        output[mode]={'attempted':count,'rejected':rejected,'vertices':details}
    return {'status':'WHAT_IF_ONLY_NOT_CALIBRATED_UNCERTAINTY','seed':41731,'assumptions':config,'modes':output,
            'limitations':['Point triangulation is perturbed without rerunning the joint optimizer or image detector.',
                           'The supplied perturbation scales are assumptions, not measured camera calibration uncertainty.',
                           'Rejected samples include visibility and existing reprojection/parallax gates.',
                           'Percentiles use only accepted samples and can be strongly selection-biased.']}


def _solve_edge_to_line(data: dict, cameras: dict, objects: dict, groups: dict, lines: list, sensitivity: dict | None) -> dict:
    """Solve a declared rectangle from an edge, direction point and image line.

    Its opposite two vertices are inferred line intersections, never direct
    pixel observations. This first adapter handles one object at a time.
    """
    from .model_first import _basis, solve_local_wall
    if len(objects)!=1 or data.get('object_constraints'):raise ValueError('edge-to-line currently supports one object without cross-object constraints')
    ident,obj=next(iter(objects.items()));vertices=obj['vertices'];direction=obj['construction']['direction_feature']
    opposite=[o for o in lines if o['object_id']==ident and set(o['feature_ids'])==set(vertices[2:])]
    if len(opposite)<2:raise ValueError('opposite boundary needs line observations in at least two views')
    if len(opposite)!=len(lines):raise ValueError('edge-to-line cannot use other line constraints; review or remove them explicitly')
    legacy={'schema':'worldstate-local-wall-observations/0.1','operator':'source_observation_origins_preserved_in_modeler_input',
        'camera_mode':'KNOWN_POSE_UNVERIFIED','source_reconstruction':data.get('source_reconstruction',[]),
        'cameras':list(cameras.values()),'corners':{'left_top':groups[(ident,vertices[0])],
            'right_top':groups[(ident,vertices[1])],'right_bottom':groups[(ident,direction)]},'ceiling_lines':opposite}
    solved=solve_local_wall(legacy);parameters=np.asarray(solved['optimized_parameters'])
    left,right,bottom=parameters[:3],parameters[3:6],parameters[6:9];_,up,_,_=_basis(left,right,bottom)
    xyz=np.array([left,right,right+parameters[9]*up,left+parameters[9]*up]);normal,offset,condition=_plane(xyz)
    projections=[]
    for image_id,camera in cameras.items():
        try:polygon=[_project(point,camera).tolist() for point in xyz]
        except ValueError:continue
        projections.append({'image_id':image_id,'photo_sha256':camera['sha256'],'polygon_px':polygon})
    observed=[]
    for label,legacy_key in ((vertices[0],'left_top'),(vertices[1],'right_top'),(direction,'right_bottom')):
        for item in solved['after']['corner_observations']:
            if item['corner']==legacy_key:observed.append({'feature_id':label,**item})
    by_key={(ident,vertices[0]):left,(ident,vertices[1]):right,(ident,direction):bottom}
    candidate={'id':ident,'ifc_type':'IfcWall','surface_kind':obj['surface_kind'],
        'vertices':[{'id':name,'xyz_source':point.tolist(),
            'status':'triangulated_observation' if i<2 else 'inferred_line_intersection',
            'parallax_deg':solved['triangulated'][('left_top','right_top')[i]]['max_parallax_degrees'] if i<2 else None}
            for i,(name,point) in enumerate(zip(vertices,xyz))],
        'plane':{'normal':normal.tolist(),'offset_source':offset,'condition_number':condition,
                 'fit_rms_source':float(np.sqrt(np.mean(np.square(xyz@normal+offset))))},
        'observations':observed,'projections':projections,'scale_status':'UNKNOWN',
        'unknown':['wall identity and wall/feature coplanarity unconfirmed','two opposite vertices inferred from direction and line',
                   'rectangularity assumed','complete boundary and occlusion','wall thickness','metric scale','uncertainty not calibrated']}
    return {'schema':'worldstate-bim-modeler-solution/0.1','input_sha256':digest(data),'objects':[candidate],
        'camera_mode':data.get('camera_mode','UNSPECIFIED'),'source_coordinate_system':data.get('coordinate_system',{}),
        'optimization':{'method':'edge-to-line multiview soft_l1 with explicit rectangularity assumption',
            'point_max_px':solved['after']['maximum_px'],'point_rms_px':solved['after']['rms_px'],
            'metric_scope':'combined point distances and line-endpoint distances in pixels',
            'jacobian_condition_number':solved['optimization']['jacobian_condition_number'],
            'line_observation_count':len(opposite),'plane_semantics':'NOT_USED',
            'limitations':['Pixel weighting currently uses a shared 3 px robust scale; per-observation sigma is retained but not applied.',
                           'The opposite endpoints and rectangularity are inferred, not observed.']},
        'sensitivity':_sensitivity(cameras,groups,by_key,sensitivity),'status':'UNVERIFIED_VISIBLE_SURFACE_CANDIDATE',
        'limitations':['Feature-to-wall coplanarity and physical wall classification are not verified.',
            'Two vertices are inferred from a rectangular construction and cannot be treated as physical corners.',
            'Reprojection residual is not independent geometric accuracy.']}


def solve_modeler(data: dict, *, sensitivity: dict | None = None) -> dict:
    """Solve general planar wall polygons jointly from version-bound pixels.

    Rectangular, vertical and inter-object assumptions are never implicit.
    Three or more points may describe a nonrectangular partial visible surface.
    """
    cameras,objects,groups,lines=_validate(data);constraints=_constraint_data(data,objects)
    if any(obj.get('construction',{}).get('kind')=='edge_to_line' for obj in objects.values()):
        return _solve_edge_to_line(data,cameras,objects,groups,lines,sensitivity)
    keys=list(groups);index={key:i for i,key in enumerate(keys)};initial=[];triangulated={}
    for key in keys:
        result=triangulate_observations(list(cameras.values()),groups[key]);initial.extend(result['xyz']);triangulated[key]=result
    initial=np.asarray(initial,dtype=float).reshape(-1,3)
    slices={ident:[index[(ident,v)] for v in obj['vertices']] for ident,obj in objects.items()}
    diameters={ident:max(float(np.linalg.norm(initial[i]-initial[j])) for i in ids for j in ids) for ident,ids in slices.items()}
    for ident,ids in slices.items():
        if diameters[ident]<1e-7:raise ValueError('candidate surface is too small')
        _plane(initial[ids])
    def residual(vector):
        points=vector.reshape(-1,3);values=[]
        try:
            for key,obs_list in groups.items():
                for obs in obs_list:values.extend(((_project(points[index[key]],cameras[obs['image_id']])-_point(obs,cameras[obs['image_id']]))/obs['sigma_px']).tolist())
            for obs in lines:
                line=_line(obs['points_px']);camera=cameras[obs['image_id']]
                for feature in obs['feature_ids']:
                    values.append(float(line@np.r_[_project(points[index[(obs['object_id'],feature)]],camera),1.])/obs['sigma_px'])
            planes={}
            for ident,ids in slices.items():
                normal,offset,_=_plane(points[ids]);planes[ident]=(normal,offset)
                # Coplanarity is an explicit surface-model prior, not independent measurement.
                values.extend(((points[ids]@normal+offset)/(diameters[ident]*.005)).tolist())
            for c in constraints:
                na,da=planes[c['a']];nb,db=planes[c['b']];kind=c['kind']
                if kind=='parallel':values.append(float(np.linalg.norm(np.cross(na,nb))/c['uncertainty']['angle_rad']))
                elif kind=='perpendicular':values.append(float((na@nb)/c['uncertainty']['angle_rad']))
                elif kind=='coplanar':
                    values.append(float(np.linalg.norm(np.cross(na,nb))/c['uncertainty']['angle_rad']))
                    values.append(float((points[slices[c['a']][0]]@nb+db)/c['uncertainty']['distance_source']))
                else:
                    a=points[index[(c['a'],c['vertex_a'])]];b=points[index[(c['b'],c['vertex_b'])]]
                    values.extend(((a-b)/c['uncertainty']['distance_source']).tolist())
        except ValueError:
            # Finite-difference optimization must not silently accept invalid geometry.
            raise ValueError('candidate projection or plane became degenerate')
        return np.asarray(values,dtype=float)
    result=least_squares(residual,initial.ravel(),loss='soft_l1',f_scale=3.,x_scale='jac',max_nfev=400)
    if not result.success or not np.isfinite(result.x).all():raise ValueError('joint model optimization failed')
    points=result.x.reshape(-1,3);singular=np.linalg.svd(result.jac,compute_uv=False)
    if len(singular)<len(result.x) or singular[-1]<1e-8:raise ValueError('model parameters are not identifiable')
    output=[];all_errors=[]
    for ident,obj in objects.items():
        ids=slices[ident];normal,offset,condition=_plane(points[ids]);observations=[];views={}
        plane_rms=float(np.sqrt(np.mean(np.square(points[ids]@normal+offset))))
        if plane_rms>diameters[ident]*.02:raise ValueError(f'{ident}: image observations conflict with a planar surface')
        for vertex in obj['vertices']:
            key=(ident,vertex)
            for obs in groups[key]:
                predicted=_project(points[index[key]],cameras[obs['image_id']]);error=float(np.linalg.norm(predicted-_point(obs,cameras[obs['image_id']])));all_errors.append(error)
                observations.append({'feature_id':vertex,'image_id':obs['image_id'],'photo_sha256':obs['photo_sha256'],
                    'observed_pixel_xy':obs['pixel_xy'],'projected_pixel_xy':predicted.tolist(),'error_px':error})
                views[obs['image_id']]=cameras[obs['image_id']]
        projections=[]
        for ident_view,cam in views.items():
            try:poly=[_project(points[i],cam).tolist() for i in ids]
            except ValueError:continue
            projections.append({'image_id':ident_view,'photo_sha256':cam['sha256'],'polygon_px':poly})
        output.append({'id':ident,'ifc_type':'IfcWall','surface_kind':obj['surface_kind'],
            'vertices':[{'id':v,'xyz_source':points[index[(ident,v)]].tolist(),
                         'parallax_deg':triangulated[(ident,v)]['max_parallax_degrees']} for v in obj['vertices']],
            'plane':{'normal':normal.tolist(),'offset_source':offset,'condition_number':condition,
                     'fit_rms_source':plane_rms},
            'observations':observations,'projections':projections,'scale_status':'UNKNOWN',
            'unknown':['physical wall identity unconfirmed','occluded and complete boundaries','wall thickness',
                       'metric scale','camera and spatial uncertainty not calibrated']})
    # Refuse ambiguous overlapping patches rather than counting one physical
    # surface twice. Adjacent coplanar patches with disjoint support remain.
    from shapely.geometry import Polygon
    polygons={}
    for ident,ids in slices.items():
        normal,offset,_=_plane(points[ids]);axis=np.eye(3)[int(np.argmin(np.abs(normal)))]
        x=axis-normal*(axis@normal);x/=np.linalg.norm(x);y=np.cross(normal,x)
        polygon=Polygon([(float(p@x),float(p@y)) for p in points[ids]])
        if not polygon.is_valid or polygon.area<1e-12:raise ValueError(f'{ident}: visible boundary is invalid or self-intersecting')
        polygons[ident]=(normal,offset,x,y,polygon)
    names=list(objects)
    for i,a in enumerate(names):
        for b in names[i+1:]:
            normal,offset,x,y,first=polygons[a];other=polygons[b][0]
            if abs(float(normal@other))<math.cos(math.radians(3)):continue
            if max(abs(float(points[j]@normal+offset)) for j in slices[b])>min(diameters[a],diameters[b])*.02:continue
            second=Polygon([(float(points[j]@x),float(points[j]@y)) for j in slices[b]])
            if second.is_valid and first.intersection(second).area/min(first.area,second.area)>.5:
                raise ValueError(f'{a} and {b}: overlapping coplanar surfaces may be duplicates; review association')
    for c in constraints:
        na,da,_=_plane(points[slices[c['a']]]);nb,db,_=_plane(points[slices[c['b']]])
        angular=abs(float(na@nb));kind=c['kind'];limit=math.sin(math.radians(3))
        if kind in {'parallel','coplanar'} and np.linalg.norm(np.cross(na,nb))>limit:raise ValueError('parallel or coplanar constraint conflicts with observations')
        if kind=='perpendicular' and angular>limit:raise ValueError('perpendicular constraint conflicts with observations')
        extent=max(diameters[c['a']],diameters[c['b']])
        if kind=='coplanar' and abs(float(points[slices[c['a']][0]]@nb+db))>extent*.02:
            raise ValueError('coplanar constraint conflicts with observations')
        if kind in {'coincident','intersection'}:
            a=points[index[(c['a'],c['vertex_a'])]];b=points[index[(c['b'],c['vertex_b'])]]
            if np.linalg.norm(a-b)>extent*.02:raise ValueError('coincident constraint conflicts with observations')
    line_errors=[]
    for obs in lines:
        line=_line(obs['points_px']);camera=cameras[obs['image_id']]
        for feature in obs['feature_ids']:
            line_errors.append(float(abs(line@np.r_[_project(points[index[(obs['object_id'],feature)]],camera),1.])))
    if not all_errors or max(all_errors)>3.:raise ValueError('optimized point observations exceed the existing 3 px consistency gate')
    if line_errors and max(line_errors)>3.:raise ValueError('line observation conflicts with the 3 px consistency gate')
    by_key={key:points[index[key]] for key in keys}
    return {'schema':'worldstate-bim-modeler-solution/0.1','input_sha256':digest(data),'objects':output,
            'camera_mode':data.get('camera_mode','UNSPECIFIED'),'source_coordinate_system':data.get('coordinate_system',{}),
            'optimization':{'method':'joint SciPy soft_l1 over 3D vertices','explicit_constraints':constraints,
                'coplanarity':'surface-model prior at 0.5% candidate diameter; not an independent measurement',
                'line_observation_count':len(lines),'plane_semantics':'RECORDED_NOT_OPTIMIZED',
                'line_max_px':max(line_errors) if line_errors else None,
                'point_max_px':max(all_errors),'point_rms_px':float(np.sqrt(np.mean(np.square(all_errors)))),
                'jacobian_condition_number':float(singular[0]/singular[-1]),'evaluations':result.nfev},
            'sensitivity':_sensitivity(cameras,groups,by_key,sensitivity),
            'status':'UNVERIFIED_VISIBLE_SURFACE_CANDIDATE',
            'limitations':['Low reprojection error is not independent geometric accuracy.',
                'Camera registration, physical correspondence, visibility and wall identity require review.',
                'Coplanarity is a prior; no rectangularity, shared corners or room closure is inferred.']}


def build_room_ir(data: dict, solution: dict, *, project_id: str, scale: dict, thickness_m: float,
                  up_source: list[float], allow_rectangular_approximation: bool) -> dict:
    """Compile explicitly accepted rectangular vertical patches in a common frame.

    Nonrectangular surfaces remain valid candidates but are not silently
    converted to rectangles. The chosen source up direction, scale and unknown
    thickness must be explicit and remain part of the evidence.
    """
    if solution.get('input_sha256')!=digest(data):raise ValueError('observations or cameras changed; solve again')
    if allow_rectangular_approximation is not True:raise ValueError('rectangular IFC approximation requires explicit acceptance')
    if not isinstance(project_id,str) or not project_id.strip():raise ValueError('project identity required')
    if not isinstance(scale,dict):raise ValueError('explicit scale or multiview physical anchor required')
    if scale.get('basis')=='assumed':
        factor=scale.get('metres_per_source_unit')
        if isinstance(factor,bool) or not isinstance(factor,(int,float)) or not math.isfinite(factor) or factor<=0:
            raise ValueError('a positive assumed scale is required')
        scale_evidence={'kind':'scale_assumption',**scale,'independent_measurement':False}
    elif scale.get('schema')=='worldstate-multiview-scale-anchor/0.1':
        from .multiview_fusion import solve_multiview_scale
        fusion={'cameras':data['cameras'],'source_reconstruction':data.get('source_reconstruction'),
                'coordinate_system':{'name':'modeler source','scale_status':'UNKNOWN'}}
        solved_scale=solve_multiview_scale(fusion,scale);factor=solved_scale['metres_per_sfm_unit']
        scale_evidence={'kind':'multiview_metric_anchor','anchor':scale,'solution':solved_scale,
                        'independent_measurement':('DECLARED_NOT_INDEPENDENTLY_VERIFIED'
                            if scale['basis']=='independent_user_declared' else False)}
    else:raise ValueError('use a bound multiview anchor or explicitly assumed scale')
    factor=float(factor)
    if isinstance(thickness_m,bool) or not isinstance(thickness_m,(int,float)) or not math.isfinite(thickness_m) or thickness_m<=0:
        raise ValueError('positive explicit assumed wall thickness required')
    up=np.asarray(up_source,dtype=float)
    if up.shape!=(3,) or not np.isfinite(up).all() or np.linalg.norm(up)<1e-8:raise ValueError('explicit source up direction required')
    up/=np.linalg.norm(up);ref=np.eye(3)[int(np.argmin(np.abs(up)))];x=ref-up*(ref@up);x/=np.linalg.norm(x);y=np.cross(up,x)
    frame=np.column_stack((x,y,up));nodes=[];elements=[];fit=[]
    for obj in solution['objects']:
        vertices=np.array([v['xyz_source'] for v in obj['vertices']])@frame*factor
        if len(vertices)!=4:raise ValueError(f"{obj['id']}: IFC requires a four-vertex candidate; polygon remains a surface candidate")
        zorder=np.argsort(vertices[:,2]);lower=vertices[zorder[:2]];upper=vertices[zorder[2:]]
        delta=lower[1]-lower[0];width=float(np.linalg.norm(delta[:2]))
        if width<1e-6:raise ValueError('wall base edge is degenerate')
        direction=delta[:2]/width;ordered_upper=sorted(upper,key=lambda p:float((p[:2]-lower[0,:2])@direction))
        height=float((ordered_upper[0][2]+ordered_upper[1][2]-lower[0,2]-lower[1,2])/2)
        if height<=0:raise ValueError('wall height is not identifiable')
        base_z=float(np.mean(lower[:,2]));base=np.array([lower[0,0],lower[0,1],base_z]);end=np.array([lower[1,0],lower[1,1],base_z])
        ideal=np.array([base,end,end+[0,0,height],base+[0,0,height]])
        actual=np.array([lower[0],lower[1],ordered_upper[1],ordered_upper[0]])
        errors=np.linalg.norm(actual-ideal,axis=1);limit=.02*max(width,height)
        if max(errors)>limit:raise ValueError(f"{obj['id']}: nonrectangular or nonvertical surface cannot be exported as an IfcWall")
        fit.append({'object_id':obj['id'],'max_corner_adjustment_m':float(max(errors)),'limit_m':limit,
                    'status':'EXPLICIT_UNVERIFIED_RECTANGULAR_APPROXIMATION'})
        refids=['observations','frame','scale','rectangular-approximation'];start=obj['id']+'-start';finish=obj['id']+'-end'
        for ident,p in ((start,base),(finish,end)):
            nodes.append({'id':ident,'x':float(p[0]),'y':float(p[1]),'status':'inferred','evidence_refs':refids})
        elements.append({'id':obj['id'],'ifc_type':'IfcWall','start':start,'end':finish,'storey':'local-storey','axis_reference':'face',
            'classification':{'status':'inferred','evidence_refs':['observations']},'parameters':{
              'height':quantity(height,'inferred',refids,'Visible patch height; not necessarily complete wall height'),
              'base_elevation':quantity(base_z,'inferred',refids,'Visible patch lower boundary; not necessarily a floor'),
              'thickness':quantity(thickness_m,'assumed',['thickness'],'Unobserved assumed wall thickness')},
            'unknown':obj['unknown']+['rectangular and vertical approximation unverified','not a complete wall']})
    evidence=[{'id':'observations','kind':'multiview_modeler_observations','data':data,'solution_input_sha256':solution['input_sha256']},
        {'id':'frame','kind':'declared_source_up','up_source':up.tolist(),'frame_source':frame.tolist(),'status':'assumed_or_user_declared_unverified'},
        {'id':'scale',**scale_evidence},
        {'id':'thickness','kind':'thickness_assumption','value_m':thickness_m,'status':'assumed'},
        {'id':'rectangular-approximation','kind':'explicit_geometry_approximation','details':fit,'status':'assumed'}]
    model={'schema':SCHEMA,'project_id':project_id,'mode':'assisted','revision':1,
        'coordinate_system':{'name':'modeler shared source frame, unverified metric','unit':'m',
             'source_to_metres':factor,'axes_in_source':frame.tolist(),'georeferencing':'UNKNOWN'},
        'evidence':evidence,'nodes':nodes,'storeys':[{'id':'local-storey','elevation':quantity(0.,'assumed',['frame'],'Local datum; not surveyed floor')}],
        'elements':elements,'constraints':[],'scale':scale_evidence,
        'validation':{'status':'UNVERIFIED_DRAFT','scope':'PARTIAL_OPEN',
                      'warning':'Only visible patches; up and wall thickness are assumed; scale is not independently verified.'}}
    validate_room(model);issues=geometry_issues(model)
    if issues:raise ValueError('model geometry conflicts: '+str(issues))
    return model
